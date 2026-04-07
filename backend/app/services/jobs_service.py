from app.core.database import SessionLocal
from app.repositories.story_final_repository import get_final_by_job_id, save_final_story
import asyncio

_job_results = {}
_lock = asyncio.Lock()
_pending_jobs = {}


async def get_job_state(job_id: str):
    """Récupère l'état d'un job"""
    async with _lock:
        result = _job_results.get(job_id)
        if result:
            return _format_job_result(result)
    
    async with SessionLocal() as db:
        from app.repositories.story_final_repository import get_final_by_job_id
        final = await get_final_by_job_id(db, job_id)
        if final:
            return {
                "status": "completed",
                "job_id": final.job_id,
                "jira_id": final.issue_key,
                "improved_story": final.improved_story,
                "acceptance_criteria": final.acceptance_criteria,
                "score_before": final.score_before,
                "score_after": final.score_after,
                "delta": final.delta,
                "iteration": final.iteration,
                "outcome": final.outcome,
            }
    
    return {"status": "not_found"}

async def get_running_jobs() -> dict:
    """Récupère les jobs en cours (uniquement en mémoire)"""
    async with _lock:
        running = {}
        for job_id, result in _job_results.items():
            current_step = result.get("current_step", "")
            if current_step not in ["job_completed", "prepare_skip_done"]:
                running[result.get("jira_id")] = {
                    "job_id": job_id,
                    "issue_key": result.get("jira_id"),
                    "status": "running",
                    "current_step": current_step,
                    "iteration": result.get("iteration", 0),
                }
        return running


async def get_pending_jobs() -> dict:
    """Récupère les jobs terminés depuis la DB"""
    from app.repositories.story_final_repository import get_all_completed_jobs
    
    async with SessionLocal() as db:
        finals = await get_all_completed_jobs(db)
        
        pending = {}
        for final in finals:
            pending[final.issue_key] = {
                "job_id": final.job_id,
                "issue_key": final.issue_key,
                "story_id": final.user_story_id,
                "status": "completed",
                "score_before": final.score_before,
                "score_after": final.score_after,
                "delta": final.delta,
                "iteration": final.iteration,
            }
        return pending
    
def _format_job_result(result: dict) -> dict:
    """Formate le résultat temporaire pour l'API"""
    initial = result.get("initial_score") or 0
    final = result.get("final_score") or 0
    
    return {
        "status": "processing",
        "job_id": result.get("job_id"),
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
        "current_step": result.get("current_step"),
        "llm_score": result.get("llm_score", 0),
        "rule_score": result.get("rule_score", 0),
        "nlp_score": result.get("nlp_score", 0),
        "llm_issues": result.get("llm_issues", []),
        "llm_suggestions": result.get("llm_suggestions", []),
        "timing": result.get("timing", {}),
        "trace": result.get("trace", []),
        "events": result.get("events", []),
    }


async def store_job_result(job_id: str, result: dict):
    
    # 1. STOCKAGE MÉMOIRE (toujours - état temporaire)
    async with _lock:
        _job_results[job_id] = result
        jira_id = result.get("jira_id")
        if jira_id:
            _pending_jobs[jira_id] = job_id

    # 2. PERSISTANCE DB - UNIQUEMENT À LA FIN
    current_step = result.get("current_step", "")
    
    if current_step == "job_completed":
        outcome = result.get("outcome")
        
        if not outcome:
            if result.get("consecutive_llm_failures", 0) >= 2:
                outcome = "no_improvement"
            else:
                outcome = "processing"
        
        async with SessionLocal() as db:
            # save_final_story existe déjà et utilise UserStoryFinal
            await save_final_story(
                db,
                result.get("jira_id"),
                result.get("improved_story") or result.get("raw_story"),
                outcome,
                result  # ← le state complet est passé mais seule une partie est stockée
            )
        
        async with _lock:
            _job_results.pop(job_id, None)
            if jira_id and _pending_jobs.get(jira_id) == job_id:
                _pending_jobs.pop(jira_id, None)


async def apply_decision(job_id: str, choice: str):
    """Applique une décision humaine sur un job terminé"""
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

    # build state pour la DB
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

    # Persistance DB
    async with SessionLocal() as db:
        success = await save_final_story(
            db, jira_id, final_story, outcome, state
        )

        if not success:
            return {"status": "error", "message": "Failed to save"}

    # Cleanup mémoire
    async with _lock:
        _job_results.pop(job_id, None)
        if jira_id and _pending_jobs.get(jira_id) == job_id:
            _pending_jobs.pop(jira_id, None)

    return {
        "status": "ok",
        "choice": choice,
        "issue_key": jira_id,
    }