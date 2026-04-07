import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_story import UserStory
from app.repositories.story_final_repository import get_finals_by_story_ids
from app.repositories.story_repository import (
    create_story,
    get_all_stories,
    get_stories_by_project_id,
)

from app.utils.common.mapper_utils import map_jira_issue

# =========================
# MAPPERS
# =========================
def _story_to_dict(story):
    return {
        "id": story.id,
        "issue_key": story.issue_key,
        "jira_project_id": story.jira_project_id,
        "title": story.title,
        "description": story.description,
        "acceptance_criteria": story.acceptance_criteria or [],
        "issue_type": story.issue_type,
        "status": story.status,
        "priority": story.priority,
        "story_points": story.story_points,
        "assignee": story.assignee,
        "reporter": story.reporter,
        "epic_key": story.epic_key,
        "epic_name": story.epic_name,
        "sprint": story.sprint,
        "labels": story.labels or [],
        "components": story.components or [],
        "fix_version": story.fix_version,
    }


def _final_to_dict(final):
    return {
        "improved_story": final.improved_story,
        "acceptance_criteria": final.acceptance_criteria or [],
        "score_before": final.score_before,
        "score_after": final.score_after,
        "delta": final.delta,
        "iteration": final.iteration,
        "outcome": final.outcome,
        "human_choice": final.human_choice,
        "job_id": final.job_id,
    }


# =========================
# ENRICH STORIES
# =========================
async def _enrich_with_finals(db: AsyncSession, stories):
    if not stories:
        return []

    story_ids = [s.id for s in stories]
    finals = await get_finals_by_story_ids(db, story_ids)
    finals_map = {f.user_story_id: f for f in finals}

    result = []
    for story in stories:
        item = _story_to_dict(story)
        final = finals_map.get(story.id)
        item["final"] = _final_to_dict(final) if final else None
        result.append(item)

    return result


# =========================
# LIST STORIES
# =========================
async def list_stories(db: AsyncSession):
    stories = await get_all_stories(db)
    return await _enrich_with_finals(db, stories)


async def list_stories_by_project(db: AsyncSession, project_id: str):
    stories = await get_stories_by_project_id(db, project_id)
    return await _enrich_with_finals(db, stories)


# =========================
# IMPORT STORIES
# =========================
async def import_project_stories(
    db: AsyncSession,
    project,
    jira_issues: list,
) -> dict:
    """
    Importe les stories Jira dans la base de données.
    Retourne le nombre de stories importées et ignorées.
    """
    count = 0
    skipped = 0

    # 1. Extraire les clés des issues Jira
    issue_keys = [i.get("key") for i in jira_issues if i.get("key")]

    if not issue_keys:
        return {"imported": 0, "skipped": 0}

    # 2. Vérifier quelles stories existent déjà
    result = await db.execute(
        select(UserStory.issue_key).where(UserStory.issue_key.in_(issue_keys))
    )
    existing_keys = {row[0] for row in result.all()}

    # 3. Filtrer les nouvelles stories
    new_stories = []

    for issue in jira_issues:
        try:
            # Mapper l'issue Jira vers le format UserStory
            mapped = map_jira_issue(issue)
            key = mapped.get("issue_key")

            if not key or key in existing_keys:
                skipped += 1
                continue

            # Ajouter l'ID du projet
            mapped["jira_project_id"] = project.id
            new_stories.append(mapped)

        except Exception as e:
            print(f"[IMPORT ERROR] Issue {issue.get('key', 'unknown')}: {e}")
            skipped += 1

    # 4. Créer les nouvelles stories
    for story_data in new_stories:
        try:
            await create_story(db, story_data)
            count += 1
        except Exception as e:
            print(f"[CREATE STORY ERROR] {story_data.get('issue_key', 'unknown')}: {e}")
            skipped += 1

    # 5. Commit une seule fois à la fin
    await db.commit()

    return {
        "imported": count,
        "skipped": skipped,
        "total": len(jira_issues)
    }