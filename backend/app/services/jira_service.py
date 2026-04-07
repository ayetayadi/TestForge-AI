import urllib.parse

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.utils.mapper_utils import extract_text_from_adf
from datetime import datetime, timedelta

ATLASSIAN_AUTH_URL = "https://auth.atlassian.com/authorize"
ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ATLASSIAN_API_URL = "https://api.atlassian.com"


def get_oauth_url(state: str) -> str:
    params = {
        "audience": "api.atlassian.com",
        "client_id": settings.JIRA_CLIENT_ID,
        "scope": "read:jira-work read:jira-user offline_access",
        "redirect_uri": settings.JIRA_REDIRECT_URI,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }
    return f"{ATLASSIAN_AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_code_for_token(code: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            ATLASSIAN_TOKEN_URL,
            json={
                "grant_type": "authorization_code",
                "client_id": settings.JIRA_CLIENT_ID,
                "client_secret": settings.JIRA_CLIENT_SECRET,
                "code": code,
                "redirect_uri": settings.JIRA_REDIRECT_URI,
            },
            headers={"Content-Type": "application/json"},
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to exchange code for token: {response.text}",
        )

    return response.json()


async def refresh_access_token(refresh_token: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            ATLASSIAN_TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "client_id": settings.JIRA_CLIENT_ID,
                "client_secret": settings.JIRA_CLIENT_SECRET,
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/json"},
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to refresh Jira token: {response.text}",
        )

    return response.json()


async def get_cloud_id(access_token: str) -> str:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{ATLASSIAN_API_URL}/oauth/token/accessible-resources",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch accessible resources: {response.text}",
        )

    resources = response.json()
    if not resources:
        raise HTTPException(status_code=400, detail="No Atlassian sites found")

    return resources[0]["id"]


def _jira_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


async def fetch_jira_projects(access_token: str, cloud_id: str) -> list:
    url = f"{ATLASSIAN_API_URL}/ex/jira/{cloud_id}/rest/api/3/project/search"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, headers=_jira_headers(access_token))

    if response.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch Jira projects: {response.text}",
        )

    data = response.json()
    projects = data.get("values", [])

    return [
        {
            "id": p.get("id", ""),
            "key": p.get("key", ""),
            "name": p.get("name", ""),
            "lead": (p.get("lead") or {}).get("displayName"),
            "type": p.get("projectTypeKey"),
            "avatar": (p.get("avatarUrls") or {}).get("48x48", ""),
        }
        for p in projects
    ]


async def fetch_user_stories(
    access_token: str,
    cloud_id: str,
    project_key: str,
) -> list:

    if not access_token:
        raise HTTPException(status_code=400, detail="Missing access_token")

    if not cloud_id:
        raise HTTPException(status_code=400, detail="Missing cloud_id")

    url = f"{ATLASSIAN_API_URL}/ex/jira/{cloud_id}/rest/api/3/search/jql"
    jql = f'project = "{project_key}" AND issuetype = "Story" ORDER BY created DESC'

    fields_list = [
        "summary", "description", "priority", "status",
        "issuetype", "story_points", "customfield_10028",
        "assignee", "reporter",
        "epic", "customfield_10014", "customfield_10015",
        "sprint", "labels", "components",
        "fixVersions", "created", "updated"
    ]

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                url,
                headers=_jira_headers(access_token),
                params={
                    "jql": jql,
                    "maxResults": 100,
                    "fields": ",".join(fields_list),
                },
            )

        # 🔴 Token expiré
        if response.status_code == 401:
            raise HTTPException(status_code=401, detail="Jira token expired")

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Jira API error: {response.text}",
            )

        issues = response.json().get("issues", []) or []
        stories = []

        for issue in issues:
            fields = issue.get("fields") or {}

            # 🔹 description ADF safe
            try:
                description = extract_text_from_adf(fields.get("description"))
            except Exception:
                description = ""

            # 🔹 objets simples
            status = (fields.get("status") or {}).get("name", "")
            priority = (fields.get("priority") or {}).get("name", "")
            issuetype = (fields.get("issuetype") or {}).get("name", "")

            assignee = (fields.get("assignee") or {}).get("displayName", "Unassigned")
            reporter = (fields.get("reporter") or {}).get("displayName", "")

            story_points = fields.get("story_points") or fields.get("customfield_10028")

            epic = fields.get("epic") or fields.get("customfield_10014")

            sprint = fields.get("sprint") or fields.get("customfield_10015")

            labels = fields.get("labels") or []
            components = [c.get("name") for c in (fields.get("components") or [])]

            fix_versions = [v.get("name") for v in (fields.get("fixVersions") or [])]

            stories.append({
                "id": issue.get("id", ""),
                "key": issue.get("key", ""),

                # contenu
                "summary": fields.get("summary", ""),
                "description": description,

                # metadata
                "status": status,
                "priority": priority,
                "issue_type": issuetype,
                "story_points": story_points,

                # personnes
                "assignee": assignee,
                "reporter": reporter,

                # agile
                "epic": epic,
                "sprint": sprint,
                "labels": labels,
                "components": components,
                "fix_versions": fix_versions,

                # dates
                "created": fields.get("created", ""),
                "updated": fields.get("updated", ""),
            })

        return stories

    except httpx.RequestError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Network error: {str(e)}"
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )

async def ensure_valid_token(db: AsyncSession, jira_connection):

    if (
        jira_connection.token_expires_at
        and jira_connection.refresh_token
    ):
        if datetime.utcnow() >= jira_connection.token_expires_at - timedelta(minutes=5):

            try:
                new_tokens = await refresh_access_token(
                    jira_connection.refresh_token
                )

                jira_connection.access_token = new_tokens["access_token"]
                jira_connection.refresh_token = new_tokens.get(
                    "refresh_token",
                    jira_connection.refresh_token
                )

                jira_connection.token_expires_at = datetime.utcnow() + timedelta(
                    seconds=new_tokens["expires_in"]
                )

                await db.commit()

                return jira_connection.access_token

            except Exception as e:
                await db.rollback()
                raise HTTPException(401, f"Token refresh failed: {str(e)}")

    return jira_connection.access_token