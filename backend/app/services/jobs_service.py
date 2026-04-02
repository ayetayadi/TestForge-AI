import threading
from app.core.database import SessionLocal
from app.repositories.story_final_repository import save_final_story
import asyncio

# In-memory store for completed job results
_job_results = {}
_lock = asyncio.Lock()

_pending_jobs = {}

async def get_job_state(job_id: str):
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
        "current_step": result.get("current_step"),
        "events": result.get("events", []),
    }

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

async def apply_decision(job_id: str, choice: str):
    async with _lock:
        result = _job_results.get(job_id)

    if not result:
        return {"status": "error", "message": "Job not found"}

    if choice not in ("approve", "reject_keep", "reject_relaunch"):
        return {"status": "error", "message": "Invalid choice"}

    jira_id = result.get("jira_id")

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

    # ===== build state =====
    final_story = (
        result.get("improved_story")
        if choice == "approve"
        else result.get("raw_story")
    )

    outcome = "approved" if choice == "approve" else "reject_keep"

    state = {
        "acceptance_criteria": result.get("acceptance_criteria", []) if choice == "approve" else result.get("existing_ac", []),
        "initial_score": result.get("initial_score", 0),
        "best_score": result.get("best_score") or result.get("final_score", 0),
        "score_after": result.get("final_score", 0),
        "delta": round((result.get("final_score") or 0) - (result.get("initial_score") or 0), 2),
        "iteration": result.get("iteration", 0),
        "human_choice": choice,
        "job_id": job_id,
    }

    # ===== FIX ICI =====
    async with SessionLocal() as db:
        success = await save_final_story(
            db, jira_id, final_story, outcome, state
        )

        if not success:
            return {"status": "error", "message": "Failed to save"}

    # ===== cleanup =====
    async with _lock:
        _job_results.pop(job_id, None)
        if jira_id and _pending_jobs.get(jira_id) == job_id:
            _pending_jobs.pop(jira_id, None)

    return {
        "status": "ok",
        "choice": choice,
        "issue_key": jira_id,
    }

async def store_job_result(job_id: str, result: dict):

    async with _lock:
        _job_results[job_id] = result
        jira_id = result.get("jira_id")
        if jira_id:
            _pending_jobs[jira_id] = job_id

    if result.get("current_step") == "job_completed":
    
        outcome = result.get("outcome")
    
        if not outcome:
            if result.get("consecutive_llm_failures", 0) >= 2:
                outcome = "no_improvement"
            else:
                outcome = "processing"
    
        async with SessionLocal() as db:
            await save_final_story(
                db,
                result.get("jira_id"),
                result.get("improved_story") or result.get("raw_story"),
                outcome,
                result
            )