import urllib.parse

import httpx
from fastapi import HTTPException

from app.core.config import settings

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
            "avatar": (p.get("avatarUrls") or {}).get("48x48", ""),
        }
        for p in projects
    ]


async def fetch_user_stories(access_token: str, cloud_id: str, project_key: str) -> list:
    url = f"{ATLASSIAN_API_URL}/ex/jira/{cloud_id}/rest/api/3/search/jql"
    jql = f'project = "{project_key}" AND issuetype = "Story" ORDER BY created DESC'

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            url,
            headers=_jira_headers(access_token),
            params={
                "jql": jql,
                "maxResults": 100,
                "fields": ",".join([
                    "summary",
                    "description",
                    "status",
                    "priority",
                    "assignee",
                    "created",
                    "updated",
                    "issuetype",
                ]),
            },
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch user stories: {response.text}",
        )

    issues = response.json().get("issues", []) or []
    stories = []

    for issue in issues:
        fields = issue.get("fields", {}) or {}

        description = _extract_text_from_adf(fields.get("description"))

        status_obj = fields.get("status") or {}
        priority_obj = fields.get("priority") or {}
        assignee_obj = fields.get("assignee") or {}
        issuetype_obj = fields.get("issuetype") or {}

        stories.append({
            "id": issue.get("id", ""),
            "key": issue.get("key", ""),
            "summary": fields.get("summary", ""),
            "description": description,
            "status": status_obj.get("name", ""),
            "priority": priority_obj.get("name", ""),
            "assignee": assignee_obj.get("displayName", "Unassigned"),
            "created": fields.get("created", ""),
            "updated": fields.get("updated", ""),
            "issue_type": issuetype_obj.get("name", ""),
        })

    return stories


def _extract_text_from_adf(adf: dict | None) -> str:
    if not adf:
        return ""

    if isinstance(adf, str):
        return adf

    text_parts = []

    if adf.get("type") == "text":
        text_parts.append(adf.get("text", ""))

    for child in adf.get("content", []):
        text_parts.append(_extract_text_from_adf(child))

    return " ".join(filter(None, text_parts)).strip()