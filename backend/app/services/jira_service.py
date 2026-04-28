import urllib.parse
import httpx
from fastapi import HTTPException
from app.core.config import settings

ATLASSIAN_AUTH_URL  = "https://auth.atlassian.com/authorize"
ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ATLASSIAN_API_URL   = "https://api.atlassian.com"


def get_oauth_url(state: str) -> str:
    params = {
        "audience":      "api.atlassian.com",
        "client_id":     settings.JIRA_CLIENT_ID,
        "scope":         "read:jira-work write:jira-work read:jira-user offline_access",
        "redirect_uri":  settings.JIRA_REDIRECT_URI,
        "state":         state,
        "response_type": "code",
        "prompt":        "consent",
    }
    return f"{ATLASSIAN_AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_code_for_token(code: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(
            ATLASSIAN_TOKEN_URL,
            json={
                "grant_type":    "authorization_code",
                "client_id":     settings.JIRA_CLIENT_ID,
                "client_secret": settings.JIRA_CLIENT_SECRET,
                "code":          code,
                "redirect_uri":  settings.JIRA_REDIRECT_URI,
            },
        )

    if res.status_code != 200:
        raise HTTPException(400, f"Token exchange failed: {res.text}")

    return res.json()


async def refresh_access_token(refresh_token: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(
            ATLASSIAN_TOKEN_URL,
            json={
                "grant_type":    "refresh_token",
                "client_id":     settings.JIRA_CLIENT_ID,
                "client_secret": settings.JIRA_CLIENT_SECRET,
                "refresh_token": refresh_token,
            },
        )

    if res.status_code != 200:
        raise HTTPException(400, f"Token refresh failed: {res.text}")

    return res.json()


async def get_accessible_resources(access_token: str) -> list[dict]:
    """Return all Jira Cloud workspaces the token can access."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.get(
            f"{ATLASSIAN_API_URL}/oauth/token/accessible-resources",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if res.status_code != 200:
        raise HTTPException(400, f"Failed to fetch Jira workspaces: {res.text}")

    data = res.json()
    if not data:
        raise HTTPException(
            400,
            "No Jira sites found. Make sure your account has access to at least one Jira project."
        )

    return data


async def get_cloud_id(access_token: str) -> str:
    """Return the cloud ID of the first accessible workspace."""
    resources = await get_accessible_resources(access_token)
    return resources[0]["id"]
