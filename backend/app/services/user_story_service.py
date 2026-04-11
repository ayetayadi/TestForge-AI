from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user_story import UserStory
from app.repositories.user_story_repository import (
    get_all_user_stories,
    get_user_stories_by_project_id,
    get_user_story_by_id,
    create_user_story,
    get_user_story_by_issue_key
)
from app.repositories.user_story_version_repository import get_latest_version, get_selected_version, get_versions_by_story_id, get_versions_by_story_ids
from app.utils.mapper_utils import map_jira_issue
from app.models.enums import StoryDecision


# =========================
# MAPPERS
# =========================
def _story_to_dict(story):
    return {
        "id": story.id,
        "issue_key": story.issue_key,
        "project_id": story.project_id,
        "title": story.title,
        "description": story.description,
        "acceptance_criteria": story.acceptance_criteria or [],
        "issue_type": story.issue_type,
        "status": story.jira_status,
        "priority": story.priority,
        "story_points": story.story_points,
        "assignee": story.assignee,
        "reporter": story.reporter,
        "epic_key": story.epic_key,
        "sprint": story.sprint,
        "labels": story.labels or [],
        "components": story.components or [],
        "fix_version": story.fix_version,
    }


def _version_to_dict(version):
    if not version:
        return None
    return {
        "id": version.id,
        "user_story_id": version.user_story_id,
        "job_id": version.job_id,
        "improved_story": version.improved_story,
        "generated_acceptance_criteria": version.generated_acceptance_criteria or [],
        "initial_score": version.initial_score,
        "final_score": version.final_score,
        "iteration": version.iteration,
        "llm_calls": version.llm_calls,
        "duration": version.duration,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "decision_status": version.decision_status.value if version.decision_status else "pending",
    }


async def _enrich_with_versions(db: AsyncSession, stories):
    if not stories:
        return []

    story_ids = [s.id for s in stories]
    versions = await get_versions_by_story_ids(db, story_ids)

    # group versions
    versions_map = {}
    for v in versions:
        versions_map.setdefault(v.user_story_id, []).append(v)

    result = []

    for story in stories:
        story_versions = versions_map.get(story.id, [])

        # =========================
        # SELECTED (approved)
        # =========================
        selected = next(
            (v for v in story_versions if v.decision_status == StoryDecision.APPROVED),
            None
        )

        # =========================
        # LATEST
        # =========================
        latest = None
        if story_versions:
            latest = max(story_versions, key=lambda v: (v.iteration or 0, v.created_at.timestamp() if v.created_at else 0))

        # =========================
        # DISPLAY
        # =========================
        display = selected or latest

        result.append({
            **_story_to_dict(story),
            "selected_version": _version_to_dict(selected),
            "latest_version": _version_to_dict(latest),
            "display_version": _version_to_dict(display),
            "versions": [_version_to_dict(v) for v in story_versions],
        })

    return result


# =========================
# LIST
# =========================
async def list_stories(db: AsyncSession):
    stories = await get_all_user_stories(db)
    return await _enrich_with_versions(db, stories)


async def list_stories_by_project(db: AsyncSession, project_id: str):
    stories = await get_user_stories_by_project_id(db, project_id)
    return await _enrich_with_versions(db, stories)


# =========================
# DETAILS
# =========================
async def get_user_story_details(db: AsyncSession, user_story_id: str):
    story = await get_user_story_by_id(db, user_story_id)

    if not story:
        raise ValueError("User story not found")

    enriched = await _enrich_with_versions(db, [story])
    return enriched[0]


# =========================
# IMPORT STORIES
# =========================
async def import_project_stories(
    db: AsyncSession,
    project,
    jira_issues: list,
) -> dict:

    count = 0
    skipped = 0

    issue_keys = [i.get("key") for i in jira_issues if i.get("key")]

    if not issue_keys:
        return {"imported": 0, "skipped": 0}

    result = await db.execute(
        select(UserStory.issue_key).where(UserStory.issue_key.in_(issue_keys))
    )
    existing_keys = {row[0] for row in result.all()}

    for issue in jira_issues:
        try:
            mapped = map_jira_issue(issue)
            key = mapped.get("issue_key")

            if not key or key in existing_keys:
                skipped += 1
                continue

            mapped["project_id"] = project.id

            await create_user_story(db, **mapped)

            count += 1

        except Exception as e:
            print(f"[CREATE STORY ERROR] {issue.get('key')}: {e}")
            skipped += 1

    await db.commit()

    return {
        "imported": count,
        "skipped": skipped,
        "total": len(jira_issues)
    }


# =========================
# GET BY ISSUE KEY
# =========================
async def get_story_by_issue_key(db: AsyncSession, issue_key: str):
    user_story = await get_user_story_by_issue_key(db, issue_key)

    if not user_story:
        raise ValueError("User story not found")

    # Réutiliser _enrich_with_versions pour la cohérence
    enriched = await _enrich_with_versions(db, [user_story])
    return enriched[0]