import uuid
import traceback
from fastapi import HTTPException

from app.repositories.story_repository import (
    get_story_by_issue_key,
    get_stories_by_project_id
)

from app.utils.common.ac_utils import normalize_ac
from app.utils.common.story_utils import parse_story

from app.core.job_queue import job_queue


# ─────────────────────────────────────────
# HELPER (ANTI BUG GLOBAL)
# ─────────────────────────────────────────
def ensure_string(value):
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value or "")


# ─────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────
def start_pipeline(db, jira_project_id=None, issue_keys=None):
    try:
        print("[PIPELINE] start_pipeline called", {
            "jira_project_id": jira_project_id,
            "issue_keys": issue_keys
        })

        stories = []

        # ─────────────────────────────────────────
        # FETCH STORIES
        # ─────────────────────────────────────────
        if issue_keys:
            for key in issue_keys:
                us = get_story_by_issue_key(db, key)

                if not us:
                    print(f"[PIPELINE WARNING] Story not found: {key}")
                    continue

                stories.append(us)

        elif jira_project_id:
            stories = get_stories_by_project_id(db, jira_project_id)

        else:
            raise HTTPException(
                status_code=400,
                detail="No input provided"
            )

        if not stories:
            print("[PIPELINE] No stories found")
            return []

        # ─────────────────────────────────────────
        # CREATE JOBS
        # ─────────────────────────────────────────
        results = []

        for us in stories:
            job_id = str(uuid.uuid4())

            try:
                print(f"\n[PIPELINE] Processing {us.issue_key}")

                # ───────── PARSE STORY ─────────
                parsed = parse_story(
                    description=us.description,
                    acceptance_criteria=us.acceptance_criteria,
                )

                # ───────── FIX STORY TYPE ─────────
                raw_story = ensure_string(parsed.clean_story)

                if isinstance(parsed.clean_story, list):
                    print(f"[TYPE FIX] raw_story was list for {us.issue_key}")

                # ───────── FIX AC TYPE ─────────
                raw_ac = parsed.existing_ac or []

                if isinstance(raw_ac, str):
                    raw_ac = [raw_ac]

                # flatten nested lists
                normalized_ac = []
                for a in raw_ac:
                    if isinstance(a, list):
                        normalized_ac.extend(a)
                    else:
                        normalized_ac.append(a)

                existing_ac = normalize_ac(normalized_ac)

                # ───────── BUILD STATE ─────────
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

                # ───────── ENQUEUE ─────────
                job_queue.put(state)

                print(f"[PIPELINE] Job queued: {us.issue_key} | job_id={job_id}")

                results.append({
                    "issue_key": us.issue_key,
                    "job_id": job_id,
                    "story_source": parsed.source,
                })

            except Exception as e:
                print(f"\n[PIPELINE ERROR] Failed for {us.issue_key}")
                print("Error:", str(e))
                traceback.print_exc()
                continue

        return results

    finally:
        db.close()