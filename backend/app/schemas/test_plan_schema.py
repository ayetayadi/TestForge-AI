"""Pydantic schemas for TestPlan — generation, validation, export, sharing."""

from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


# ============================================================
# BASE / CRUD SCHEMAS
# ============================================================

class TestPlanBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    objective: Optional[str] = None
    scope_type: Optional[str] = None
    scope_refs: List[str] = Field(default_factory=list)
    in_scope: Optional[str] = None
    out_of_scope: Optional[str] = None
    environment: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    entry_criteria: Optional[str] = None
    exit_criteria: Optional[str] = None
    approach: Optional[str] = None
    assumptions: Optional[str] = None
    constraints: Optional[str] = None
    stakeholders: Optional[str] = None
    communication: Optional[str] = None

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str) -> str:
        return v.strip()


class TestPlanCreate(TestPlanBase):
    project_id: str = Field(..., min_length=36, max_length=36)
    
    sprint_ids: Optional[List[str]] = Field(None, description="Filter by sprint IDs")
    epic_keys: Optional[List[str]] = Field(None, description="Filter by epic keys")
    require_accepted_risks: bool = Field(True, description="Require accepted risks before creation")
    
    # AI-generated fields
    risk_analysis: Optional[dict] = None      


class TestPlanUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    objective: Optional[str] = None
    scope_type: Optional[str] = None
    scope_refs: Optional[List[str]] = None
    in_scope: Optional[str] = None
    out_of_scope: Optional[str] = None
    environment: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    entry_criteria: Optional[str] = None
    exit_criteria: Optional[str] = None
    approach: Optional[str] = None
    assumptions: Optional[str] = None
    constraints: Optional[str] = None
    stakeholders: Optional[str] = None
    communication: Optional[str] = None


class TestPlanResponse(TestPlanBase):
    id: str
    project_id: str
    project_name: Optional[str] = None
    project_key: Optional[str] = None
    status: str
    ai_draft_generated_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    generation_completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    risk_analysis: Optional[dict] = Field(
        None,
        description="Analyse des risques : distribution, formules, mapping US→Risque"
    )


    class Config:
        from_attributes = True


class TestPlanListResponse(BaseModel):
    items: List[TestPlanResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============================================================
# AI GENERATION
# ============================================================

class GenerateTestPlanRequest(BaseModel):
    project_id: str = Field(..., min_length=36, max_length=36)
    scope_type: str = Field("manual", description="epic | sprint | release | manual")
    scope_refs: List[str] = Field(default_factory=list)
    environment: Optional[str] = None
    limit_risks: int = Field(50, ge=1, le=200)
    limit_stories: int = Field(30, ge=1, le=100)
    
    # ✅ Nouveaux champs pour filtrage
    sprint_ids: Optional[List[str]] = Field(None, description="Filter User Stories by sprint")
    epic_keys: Optional[List[str]] = Field(None, description="Filter User Stories by epic")


class GenerateTestPlanResponse(BaseModel):
    test_plan: TestPlanResponse
    recommendations: Optional[dict] = None
    workflow_status: str


# ============================================================
# EMAIL SHARING
# ============================================================

class EmailRecipient(BaseModel):
    email: str = Field(..., description="Recipient email address")
    role: str = Field(..., description="e.g. Product Owner, Tech Lead, QA Engineer, Developer")
    name: Optional[str] = None


class SendEmailRequest(BaseModel):
    recipients: List[EmailRecipient] = Field(..., min_length=1)
    subject: Optional[str] = None
    body: Optional[str] = None
    generate_body: bool = Field(True, description="Let AI generate subject + body if not provided")
    sender_name: Optional[str] = None


class GenerateEmailBodyRequest(BaseModel):
    recipients: List[EmailRecipient] = Field(..., min_length=1)
    additional_context: Optional[str] = None


class GenerateEmailBodyResponse(BaseModel):
    subject: str
    body: str


# ============================================================
# JIRA NOTIFICATION
# ============================================================

class JiraNotificationRequest(BaseModel):
    project_key: str = Field(..., description="Jira project key, e.g. SCRUM")
    summary: Optional[str] = Field(None, description="If None, derived from test plan title")
    description: Optional[str] = Field(None, description="If None, derived from test plan content")
    issue_type: str = Field("Task", description="Jira issue type: Task, Story, Bug")
    priority: str = Field("Medium", description="Highest | High | Medium | Low")


class JiraNotificationResponse(BaseModel):
    issue_key: str
    issue_url: str
    summary: str
    message: str