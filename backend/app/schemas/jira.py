from pydantic import BaseModel

class JiraConnectRequest(BaseModel):
    jira_url: str
    jira_email: str
    jira_api_token: str

class JiraStatusResponse(BaseModel):
    connected: bool
    jira_url: str | None = None
    jira_email: str | None = None

class JiraProject(BaseModel):
    id: str
    key: str
    name: str
    avatar: str | None = None

class UserStory(BaseModel):
    id: str
    key: str
    summary: str
    description: str
    status: str
    priority: str
    assignee: str
    created: str
    updated: str