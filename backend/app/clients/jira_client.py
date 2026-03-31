import requests
import base64
import os
from app.core.config import settings

def get_headers():
    token = f"{os.getenv('JIRA_EMAIL')}:{os.getenv('JIRA_API_TOKEN')}"
    encoded = base64.b64encode(token.encode()).decode()

    return {
        "Authorization": f"Basic {encoded}",
        "Accept": "application/json"
    }

def fetch_projects() -> list:
    url = f"{os.getenv('JIRA_URL')}/rest/api/3/project"

    response = requests.get(url, headers=get_headers())
    response.raise_for_status()

    projects = response.json()

    return [
        {
            "key": p.get("key"),
            "name": p.get("name"),
            "lead": (p.get("lead") or {}).get("displayName"),
            "type": p.get("projectTypeKey"),
        }
        for p in projects
    ]

def fetch_stories(project_key: str):
    url = f"{os.getenv('JIRA_URL')}/rest/api/3/search/jql"

    params = {
        "jql": f'project="{project_key}" AND issuetype="Story"',
        "maxResults": 50,
        "fields": ",".join([
            "summary", "description", "priority", "status",
            "issuetype", "story_points", "customfield_10028",
            "assignee", "reporter",
            "epic", "customfield_10014", "customfield_10015",
            "sprint", "labels", "components",
            "fixVersions", "created", "updated"
        ])
    }

    response = requests.get(url, headers=get_headers(), params=params)

    if response.status_code != 200:
        raise Exception(f"Jira API error: {response.text}")

    return response.json()