import uuid
import traceback
import asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.story_repository import (
    get_story_by_issue_key,
    get_stories_by_project_id,
)
from app.utils.common.ac_utils import normalize_ac
from app.utils.common.story_utils import parse_story, ensure_string
from app.core.job_queue import job_queue

# =========================
# PIPELINE START
# =========================
async def start_pipeline(
    db: AsyncSession,
    jira_project_id: str | None = None,
    issue_keys: list[str] | None = None,
):
    try:
        # =========================
        # FETCH STORIES
        # =========================
        if issue_keys:
            tasks = [
                get_story_by_issue_key(db, key)
                for key in issue_keys
            ]
            stories = [s for s in await asyncio.gather(*tasks) if s]

        elif jira_project_id:
            stories = await get_stories_by_project_id(db, jira_project_id)

        else:
            raise HTTPException(status_code=400, detail="No input provided")

        if not stories:
            return []

        # =========================
        # PROCESS STORIES
        # =========================
        results = []

        for us in stories:
            job_id = str(uuid.uuid4())

            try:
                parsed = parse_story(
                    description=us.description,
                    acceptance_criteria=us.acceptance_criteria,
                )

                raw_story = ensure_string(parsed.clean_story)

                raw_ac = parsed.existing_ac or []
                if isinstance(raw_ac, str):
                    raw_ac = [raw_ac]

                # flatten AC
                normalized_ac = []
                for a in raw_ac:
                    if isinstance(a, list):
                        normalized_ac.extend(a)
                    else:
                        normalized_ac.append(a)

                existing_ac = normalize_ac(normalized_ac)

                state = {
                    "raw_story": raw_story,
                    "jira_id": us.issue_key,
                    "job_id": job_id,
                    "domain": "default",
                    "iteration": 0,
                    "existing_ac": existing_ac,
                    "trace": [],
                    "initial_score": None,
                    "best_score": 0.0,
                    "is_reanalysis": False,
                    "skip_reanalysis": False,
                }

                # =========================
                # NON-BLOCKING QUEUE
                # =========================
                await job_queue.put(state)

                results.append(
                    {
                        "issue_key": us.issue_key,
                        "job_id": job_id,
                        "story_source": parsed.source,
                    }
                )

            except Exception as e:
                print(f"[PIPELINE ERROR] {e}")
                traceback.print_exc()
                continue

        return results

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))