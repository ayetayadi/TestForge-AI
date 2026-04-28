import httpx
from typing import Callable, Awaitable, Optional
from fastapi import HTTPException

ATLASSIAN_API_URL = "https://api.atlassian.com"


class JiraClient:
    """
    Thin async HTTP client for the Atlassian REST API v3.

    Pass a `token_refresher` coroutine to enable automatic token rotation:
    if Atlassian returns 401, the client refreshes once and retries before
    raising an error.
    """

    def __init__(
        self,
        access_token: str,
        cloud_id: str,
        token_refresher: Optional[Callable[[], Awaitable[str]]] = None,
    ):
        self.access_token = access_token
        self.cloud_id = cloud_id
        self._token_refresher = token_refresher

    # ------------------------------------------------------------------
    # Internal HTTP
    # ------------------------------------------------------------------

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        _retried: bool = False,
    ) -> dict:
        async with httpx.AsyncClient(timeout=20.0) as http:
            res = await http.request(
                method, url,
                headers=self._headers(),
                params=params,
                json=json,
            )

        if res.status_code == 401:
            if not _retried and self._token_refresher:
                self.access_token = await self._token_refresher()
                return await self._request(
                    method, url, params=params, json=json, _retried=True
                )
            raise HTTPException(400, "Jira token expired. Please reconnect Jira.")

        if res.status_code not in (200, 201):
            raise HTTPException(res.status_code, res.text)

        return res.json()

    # ------------------------------------------------------------------
    # Projects  (offset-based pagination)
    # ------------------------------------------------------------------

    async def get_projects(self) -> list[dict]:
        """Return every project the token can see, handling pagination."""
        url = f"{ATLASSIAN_API_URL}/ex/jira/{self.cloud_id}/rest/api/3/project/search"
        projects: list[dict] = []
        start_at = 0
        page_size = 50

        while True:
            data = await self._request("GET", url, params={
                "startAt": start_at,
                "maxResults": page_size,
                "orderBy": "name",
            })
            values = data.get("values", [])
            projects.extend(
                {
                    "id":     p.get("id"),
                    "key":    p.get("key"),
                    "name":   p.get("name"),
                    "avatar": (p.get("avatarUrls") or {}).get("48x48"),
                }
                for p in values
            )

            if data.get("isLast", True) or len(values) < page_size:
                break
            start_at += len(values)

        return projects

    # ------------------------------------------------------------------
    # Stories  (cursor-based pagination via nextPageToken)
    # ------------------------------------------------------------------

    async def _search_jql(
        self,
        jql: str,
        fields: list[str],
        max_results: int = 500,
    ) -> list[dict]:
        """Page through POST /search/jql using Atlassian cursor pagination."""
        url = f"{ATLASSIAN_API_URL}/ex/jira/{self.cloud_id}/rest/api/3/search/jql"
        issues: list[dict] = []
        next_page_token: str | None = None
        batch_size = 100

        while len(issues) < max_results:
            body: dict = {
                "jql": jql,
                "maxResults": min(batch_size, max_results - len(issues)),
                "fields": fields,
            }
            if next_page_token:
                body["nextPageToken"] = next_page_token

            data = await self._request("POST", url, json=body)
            batch = data.get("issues", [])
            issues.extend(batch)

            next_page_token = data.get("nextPageToken")
            if not next_page_token or len(batch) < batch_size:
                break

        return issues

    @staticmethod
    def _map_issue(i: dict) -> dict:
        """Flatten a raw Jira issue into the format map_jira_issue() expects."""
        fields = i.get("fields") or {}

        def _name(obj: dict | None) -> str | None:
            if not obj:
                return None
            return obj.get("displayName") or obj.get("name")

        def _sprint(f: dict) -> str | None:
            sprint = f.get("customfield_10020")
            if isinstance(sprint, list) and sprint:
                return sprint[0].get("name")
            if isinstance(sprint, dict):
                return sprint.get("name")
            return None

        return {
            "id":           i.get("id"),
            "key":          i.get("key"),
            "summary":      fields.get("summary"),
            "description":  fields.get("description"),
            "issue_type":   _name(fields.get("issuetype")),
            "status":       _name(fields.get("status")),
            "priority":     _name(fields.get("priority")),
            "story_points": fields.get("customfield_10016"),
            "assignee":     _name(fields.get("assignee")),
            "reporter":     _name(fields.get("reporter")),
            "epic":         fields.get("customfield_10014") or (
                (fields.get("parent") or {}).get("key")
                if ((fields.get("parent") or {}).get("fields") or {}).get("issuetype", {}).get("name") == "Epic"
                else None
            ),
            "epic_name":    fields.get("customfield_10008") or (
                ((fields.get("parent") or {}).get("fields") or {}).get("summary")
                if ((fields.get("parent") or {}).get("fields") or {}).get("issuetype", {}).get("name") == "Epic"
                else None
            ),
            "sprint":       _sprint(fields),
            "labels":       fields.get("labels") or [],
            "components":   [
                c.get("name") for c in fields.get("components") or []
                if c.get("name")
            ],
            "fix_versions": [
                v.get("name") for v in fields.get("fixVersions") or []
                if v.get("name")
            ],
            "created":      fields.get("created"),
            "updated":      fields.get("updated"),
        }

    _FULL_FIELDS = [
        "summary", "description", "status", "priority", "assignee", "reporter",
        "issuetype", "customfield_10016", "customfield_10014", "customfield_10020",
        "labels", "components", "fixVersions", "created", "updated", "parent",
        "customfield_10008",
    ]

    async def get_stories(
        self,
        project_key: str,
        epic_key: str | None = None,
        sprint_name: str | None = None,
    ) -> list[dict]:
        """Full story data used by the import pipeline.
        Optionally filter by epic_key or sprint_name (client-side after fetch).
        """
        jql = f'project="{project_key}" AND issuetype="Story" ORDER BY created DESC'
        issues = await self._search_jql(jql, self._FULL_FIELDS)
        mapped = [self._map_issue(i) for i in issues]

        if epic_key:
            epic_key_norm = epic_key.strip().upper()
            mapped = [m for m in mapped if (m.get("epic") or "").strip().upper() == epic_key_norm]
        if sprint_name:
            sprint_name_norm = sprint_name.strip().lower()
            mapped = [m for m in mapped if (m.get("sprint") or "").strip().lower() == sprint_name_norm]

        return mapped

    async def get_stories_preview(
        self, project_key: str, limit: int = 50
    ) -> list[dict]:
        """Lightweight list for the settings UI — only what the table needs."""
        jql = f'project="{project_key}" AND issuetype="Story" ORDER BY created DESC'
        issues = await self._search_jql(jql, ["summary", "status"], max_results=limit)
        return [
            {
                "id":      i.get("id"),
                "key":     i.get("key"),
                "summary": (i.get("fields") or {}).get("summary"),
                "status":  ((i.get("fields") or {}).get("status") or {}).get("name"),
            }
            for i in issues
        ]

    # ------------------------------------------------------------------
    # Epics  (issues of type Epic in the project)
    # ------------------------------------------------------------------

    async def get_epics(self, project_key: str) -> list[dict]:
        """Return all epics for a project."""
        jql = f'project="{project_key}" AND issuetype=Epic ORDER BY created DESC'
        issues = await self._search_jql(jql, ["summary", "status"], max_results=500)
        return [
            {
                "key":    i.get("key"),
                "summary": (i.get("fields") or {}).get("summary"),
                "status":  ((i.get("fields") or {}).get("status") or {}).get("name"),
            }
            for i in issues
        ]

    # ------------------------------------------------------------------
    # Sprints  (via Agile REST API)
    # ------------------------------------------------------------------

    async def _get_agile(self, path: str, params: dict | None = None) -> dict:
        url = f"{ATLASSIAN_API_URL}/ex/jira/{self.cloud_id}/rest/agile/1.0{path}"
        return await self._request("GET", url, params=params)

    # ------------------------------------------------------------------
    # Issue creation  (Tech Lead / Defect reporting)
    # ------------------------------------------------------------------

    def _build_adf(self, paragraphs: list[str]) -> dict:
        """Build an Atlassian Document Format body from plain-text paragraphs."""
        return {
            "version": 1,
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": p}],
                }
                for p in paragraphs
            ],
        }

    async def add_comment(self, issue_key: str, paragraphs: list[str]) -> dict:
        """Add a comment (ADF) to an existing Jira issue."""
        url = (
            f"{ATLASSIAN_API_URL}/ex/jira/{self.cloud_id}"
            f"/rest/api/3/issue/{issue_key}/comment"
        )
        body = {"body": self._build_adf(paragraphs)}
        data = await self._request("POST", url, json=body)
        return {"id": data.get("id")}

    async def create_issue(
        self,
        project_key: str,
        summary: str,
        description_paragraphs: list[str],
        issue_type: str = "Bug",
        priority: str = "High",
        labels: list[str] | None = None,
    ) -> dict:
        """Create a Jira issue and return its key and id."""
        url = f"{ATLASSIAN_API_URL}/ex/jira/{self.cloud_id}/rest/api/3/issue"
        body: dict = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "description": self._build_adf(description_paragraphs),
                "issuetype": {"name": issue_type},
                "priority": {"name": priority},
            }
        }
        if labels:
            body["fields"]["labels"] = labels

        data = await self._request("POST", url, json=body)
        return {"key": data.get("key"), "id": data.get("id")}

    async def get_sprints(self, project_key: str) -> list[dict]:
        """Return all sprints for a project across all its Scrum boards."""
        data = await self._get_agile("/board", params={"projectKeyOrId": project_key})
        boards = data.get("values", [])

        seen: dict[int, dict] = {}
        for board in boards:
            board_id = board.get("id")
            try:
                sprint_data = await self._get_agile(f"/board/{board_id}/sprint")
                for s in sprint_data.get("values", []):
                    sid = s.get("id")
                    if sid and sid not in seen:
                        seen[sid] = {
                            "id":         sid,
                            "name":       s.get("name"),
                            "state":      s.get("state"),   # active | closed | future
                            "start_date": s.get("startDate"),
                            "end_date":   s.get("endDate"),
                        }
            except Exception:
                # Kanban boards have no sprints — silently skip
                pass

        return list(seen.values())
