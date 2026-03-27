import httpx
from app.schemas.jira import JiraConnectRequest
from app.core.config import settings

ATLASSIAN_AUTH_URL = "https://auth.atlassian.com/authorize"
ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ATLASSIAN_API_URL = "https://api.atlassian.com"


def get_oauth_url(state: str) -> str:
    params = (
        f"audience=api.atlassian.com"
        f"&client_id={settings.JIRA_CLIENT_ID}"
        f"&scope=read%3Ajira-work%20read%3Ajira-user%20offline_access"
        f"&redirect_uri={settings.JIRA_REDIRECT_URI}"
        f"&state={state}"
        f"&response_type=code"
        f"&prompt=consent"
    )
    return f"{ATLASSIAN_AUTH_URL}?{params}"


async def exchange_code_for_token(code: str) -> dict:
    async with httpx.AsyncClient() as client:
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
            timeout=15,
        )
        response.raise_for_status()
        return response.json()


async def get_cloud_id(access_token: str) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{ATLASSIAN_API_URL}/oauth/token/accessible-resources",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        response.raise_for_status()
        resources = response.json()

        if not resources:
            raise ValueError("No Atlassian sites found")

        return resources[0]["id"]


async def fetch_jira_projects(access_token: str, cloud_id: str) -> list:
    url = f"{ATLASSIAN_API_URL}/ex/jira/{cloud_id}/rest/api/3/project"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            timeout=10,
        )

    if response.status_code != 200:
        raise Exception(f"Failed to fetch Jira projects: {response.text}")

    data = response.json()

    return [
        {
            "id": p["id"],
            "key": p["key"],
            "name": p["name"],
            "avatar": p.get("avatarUrls", {}).get("48x48", ""),
        }
        for p in data
    ]


async def fetch_user_stories(access_token: str, cloud_id: str, project_key: str) -> list:
    """Fetch user stories/issues from a specific Jira project."""
    url = f"{ATLASSIAN_API_URL}/ex/jira/{cloud_id}/rest/api/3/search/jql"
    jql = f'project = "{project_key}" ORDER BY created DESC'

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "jql": jql,
                    "maxResults": 100,
                    "fields": "summary,description,status,priority,assignee,created,updated,issuetype",
                },
                timeout=15,
            )


            if response.status_code != 200:
                return []

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

        except Exception as e:
            print("fetch_user_stories ERROR:", str(e))
            return []

def _extract_text_from_adf(adf: dict | None) -> str:
    """Recursively extract plain text from Atlassian Document Format."""
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


async def test_jira_connection(data: JiraConnectRequest) -> bool:
    url = f"{data.jira_url.rstrip('/')}/rest/api/3/myself"
    auth = (data.jira_email, data.jira_api_token)

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, auth=auth, timeout=10)
            return response.status_code == 200
        except Exception:
            return False