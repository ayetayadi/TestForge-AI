import asyncio

from app.core.database import SessionLocal
from app.repositories.story_final_repository import save_final_story

_job_results = {}
_pending_jobs = {}
_lock = asyncio.Lock()


# =========================
# STORE RESULT
# =========================
async def store_job_result(job_id: str, result: dict) -> None:
    async with _lock:
        _job_results[job_id] = result
        jira_id = result.get("jira_id")
        if jira_id:
            _pending_jobs[jira_id] = job_id


# =========================
# GET JOB STATE
# =========================
async def get_job_state(job_id: str) -> dict:
    async with _lock:
        result = _job_results.get(job_id)

    if not result:
        return {"status": "not_found"}

    initial = result.get("initial_score") or 0
    final = result.get("final_score") or 0

    return {
        "status": "completed",
        "job_id": job_id,
        "jira_id": result.get("jira_id"),
        "raw_story": result.get("raw_story"),
        "initial_story": result.get("initial_story"),
        "improved_story": result.get("improved_story"),
        "existing_ac": result.get("existing_ac", []),
        "acceptance_criteria": result.get("acceptance_criteria", []),
        "initial_score": initial,
        "final_score": final,
        "best_score": result.get("best_score", final),
        "delta": round(final - initial, 2),
        "iteration": result.get("iteration", 0),
        "trace": result.get("trace", []),
        "llm_score": result.get("llm_score", 0),
        "rule_score": result.get("rule_score", 0),
        "nlp_score": result.get("nlp_score", 0),
        "llm_issues": result.get("llm_issues", []),
        "llm_suggestions": result.get("llm_suggestions", []),
        "timing": result.get("timing", {}),
    }


# =========================
# GET PENDING JOBS
# =========================
async def get_pending_jobs() -> dict:
    async with _lock:
        result = {}
        for issue_key, job_id in _pending_jobs.items():
            job_data = _job_results.get(job_id)
            if job_data:
                initial = job_data.get("initial_score") or 0
                final = job_data.get("final_score") or 0

                result[issue_key] = {
                    "job_id": job_id,
                    "issue_key": issue_key,
                    "status": "completed",
                    "score_before": initial,
                    "score_after": final,
                    "delta": round(final - initial, 2),
                    "iteration": job_data.get("iteration", 0),
                }
        return result


# =========================
# APPLY DECISION
# =========================
async def apply_decision(job_id: str, choice: str) -> dict:
    async with _lock:
        result = _job_results.get(job_id)

    if not result:
        return {"status": "error", "message": "Job not found"}

    if choice not in ("approve", "reject_keep", "reject_relaunch"):
        return {"status": "error", "message": "Invalid choice"}

    jira_id = result.get("jira_id")

    # =========================
    # REJECT RELAUNCH
    # =========================
    if choice == "reject_relaunch":
        async with _lock:
            _job_results.pop(job_id, None)
            if jira_id and _pending_jobs.get(jira_id) == job_id:
                _pending_jobs.pop(jira_id, None)

        return {
            "status": "ok",
            "choice": choice,
            "issue_key": jira_id,
        }

    # =========================
    # APPROVE / REJECT KEEP
    # =========================
    if choice == "approve":
        final_story = result.get("improved_story")
        outcome = "approved"
        acceptance_criteria = result.get("acceptance_criteria", [])
    else:
        final_story = result.get("raw_story")
        outcome = "reject_keep"
        acceptance_criteria = result.get("existing_ac", [])

    state = {
        "acceptance_criteria": acceptance_criteria,
        "initial_score": result.get("initial_score", 0),
        "best_score": result.get("best_score") or result.get("final_score", 0),
        "score_after": result.get("final_score", 0),
        "delta": round(
            (result.get("final_score") or 0) - (result.get("initial_score") or 0),
            2,
        ),
        "iteration": result.get("iteration", 0),
        "human_choice": choice,
        "job_id": job_id,
    }

    async with SessionLocal() as db:
        success = await save_final_story(db, jira_id, final_story, outcome, state)
        if not success:
            return {"status": "error", "message": "Failed to save"}

    # cleanup memory
    async with _lock:
        _job_results.pop(job_id, None)
        if jira_id and _pending_jobs.get(jira_id) == job_id:
            _pending_jobs.pop(jira_id, None)

    return {
        "status": "ok",
        "choice": choice,
        "issue_key": jira_id,
    }