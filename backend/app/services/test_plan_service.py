"""TestPlan service — AI generation, approval workflow, email, Jira notification."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.repositories.test_plan_repository import TestPlanRepository
from app.repositories.risk_repository import RiskRepository
from app.repositories.user_story_repository import get_user_stories_by_project_id
from app.schemas.test_plan_schema import (
    TestPlanCreate,
    TestPlanUpdate,
    TestPlanResponse,
    TestPlanListResponse,
    GenerateTestPlanRequest,
    GenerateTestPlanResponse,
    EmailRecipient,
    SendEmailRequest,
    GenerateEmailBodyRequest,
    GenerateEmailBodyResponse,
    JiraNotificationRequest,
    JiraNotificationResponse,
)
from app.models.test_plan import TestPlan
from app.models.jira_project import JiraProject
from app.ai_workflows.test_plan.pipeline import get_pipeline

logger = logging.getLogger(__name__)


class TestPlanService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = TestPlanRepository(db)

    # ============================================================
    # AI GENERATION
    # ============================================================

    async def generate_ai_draft(
        self,
        request: GenerateTestPlanRequest,
    ) -> GenerateTestPlanResponse:
        """
        Generate an AI test plan draft from existing risk analysis results.
        Creates a new TestPlan with status=AI_PROPOSED.
        Supports sprint/epic filtering.
        """
        logger.info(
            f"[TEST PLAN SERVICE] Generating AI draft for project {request.project_id}"
            f" | sprints={request.sprint_ids} | epics={request.epic_keys}"
        )
    
        # --- Fetch project info ---
        project = await self._get_project(request.project_id)
        project_name = project.project_name if hasattr(project, "project_name") else str(request.project_id)
        project_key = project.project_key if hasattr(project, "project_key") else "PROJ"
    
        # --- 1. Fetch accepted risks ---
        risk_repo = RiskRepository(self.db)
        
        # Récupère les risques acceptés du projet
        all_risks = await risk_repo.get_by_project(request.project_id)
        accepted_risks = [r for r in all_risks if r.is_accepted == True]
        
        if not accepted_risks:
            pending_count = sum(1 for r in all_risks if r.is_accepted is None)
            
            if pending_count > 0:
                raise ValueError(
                    f"No accepted risks found. {pending_count} risk(s) are pending review. "
                    "Please review and accept/reject risks before generating a Test Plan. "
                    "Go to Risk Analysis → Review each risk → Click ✓ Accept or ✗ Reject."
                )
            else:
                raise ValueError(
                    "No risk analysis results found for this project. "
                    "Run Risk Analysis first, then review and accept risks before generating a Test Plan."
                )
    
        # --- 2. Convertir les risques en dicts (limités) ---
        risks = [self._risk_to_dict(r) for r in accepted_risks[:request.limit_risks]]
    
        # --- 3. Construire la map risques → user_story_id ---
        risks_map = {}
        for r in accepted_risks:
            if r.user_story_id:
                risks_map[r.user_story_id] = self._risk_to_dict(r)
    
        # --- 4. Récupérer les User Stories liées aux risques acceptés ---
        accepted_user_story_ids = list(set(r.user_story_id for r in accepted_risks if r.user_story_id))
        stories_raw = await get_user_stories_by_project_id(self.db, request.project_id)
        
        # Filtrer par sprint/epic si spécifié
        filtered_stories = []
        for s in stories_raw:
            # ÉTAPE 1 : Filtrer par sprint
            if request.sprint_ids and s.sprint not in request.sprint_ids:
                continue
            
            # ÉTAPE 2 : Filtrer par epic
            if request.epic_keys:
                epic_match = s.epic_key in request.epic_keys or s.epic_name in request.epic_keys
                if not epic_match:
                    continue
            if s.id not in accepted_user_story_ids:
                continue
            filtered_stories.append(s)
        
        user_stories = [
            self._story_to_dict(s, risk_info=risks_map.get(s.id))
            for s in filtered_stories[:request.limit_stories]
        ]
    
        if not user_stories:
            raise ValueError(
                "No user stories found with accepted risks matching the specified filters."
            )
    
        # --- 5. Run AI pipeline ---
        pipeline = get_pipeline()
        result = await pipeline.run(
            project_name=project_name,
            project_key=project_key,
            project_id=request.project_id,
            risks=risks,
            user_stories=user_stories,
            scope_type=request.scope_type,
            scope_refs=request.scope_refs,
            environment=request.environment,
        )
    
        if result.get("workflow_status") == "error":
            raise ValueError(f"AI generation failed: {result.get('error')}")
    
        # --- 6. Persist test plan ---
        create_data = TestPlanCreate(
            project_id=request.project_id,
            sprint_ids=request.sprint_ids,
            epic_keys=request.epic_keys,
            require_accepted_risks=True,
            title=result.get("title") or f"Test Plan — {project_name}",
            description=result.get("description"),
            objective=result.get("objective"),
            scope_type=request.scope_type,
            scope_refs=request.scope_refs or [],
            in_scope=result.get("in_scope"),
            out_of_scope=result.get("out_of_scope"),
            test_types=result.get("test_types") or [],
            test_levels=result.get("test_levels") or [],
            environment=request.environment or result.get("environment"),
            entry_criteria=result.get("entry_criteria"),
            exit_criteria=result.get("exit_criteria"),
            approach=result.get("approach"),
            assumptions=result.get("assumptions"),
            constraints=result.get("constraints"),
            stakeholders=result.get("stakeholders"),
            communication=result.get("communication"),
            risk_analysis=result.get("risk_analysis"),
            estimation=result.get("estimation"),
            recommendations_detail=result.get("recommendations_detail"),
        )
    
        plan = await self.repository.create(create_data)
        
        now = datetime.now(timezone.utc)
        plan.status = "ai_proposed"
        plan.ai_draft_generated_at = now
        await self.db.flush()
        await self.db.refresh(plan)
    
        await self.db.commit()
    
        logger.info(f"[TEST PLAN SERVICE] AI draft created: plan_id={plan.id}")
        return GenerateTestPlanResponse(
            test_plan=TestPlanResponse.model_validate(plan),
            recommendations=result.get("recommendations"),
            workflow_status="success",
        )
    
    async def regenerate_ai_draft(self, plan_id: str) -> GenerateTestPlanResponse:
        """Regenerate AI draft for an existing test plan."""
        plan = await self.repository.get_by_id(plan_id)
        if not plan:
            raise ValueError(f"Test plan {plan_id} not found")

        request = GenerateTestPlanRequest(
            project_id=plan.project_id,
            scope_type=plan.scope_type or "manual",
            scope_refs=plan.scope_refs or [],
            environment=plan.environment,
        )

        await self.repository.delete(plan_id)
        await self.db.commit()

        return await self.generate_ai_draft(request)

    # ============================================================
    # CRUD
    # ============================================================

    async def get_test_plan(self, plan_id: str) -> Optional[TestPlanResponse]:
        plan = await self.repository.get_by_id(plan_id)
        if not plan:
            return None
        return TestPlanResponse.model_validate(plan)

    async def get_test_plans_by_project(
        self,
        project_id: str,
        sprint_ids: Optional[List[str]] = None,
        epic_keys: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> TestPlanListResponse:
        """Récupère les Test Plans avec filtres sprint/epic."""
        items, total = await self.repository.get_by_project(
            project_id, sprint_ids, epic_keys, page, page_size
        )
        pagination = TestPlanRepository.compute_pagination(total, page, page_size)
        return TestPlanListResponse(
            items=[TestPlanResponse.model_validate(p) for p in items],
            **pagination,
        )

    async def get_all_test_plans(
        self,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> TestPlanListResponse:
        """Récupère tous les Test Plans avec filtres."""
        items, total = await self.repository.get_all(project_id, status, page, page_size)
        pagination = TestPlanRepository.compute_pagination(total, page, page_size)
        return TestPlanListResponse(
            items=[TestPlanResponse.model_validate(p) for p in items],
            **pagination,
        )

    async def update_test_plan(
        self,
        plan_id: str,
        data: TestPlanUpdate,
    ) -> Optional[TestPlanResponse]:
        plan = await self.repository.update(plan_id, data)
        if not plan:
            return None
        await self.db.commit()
        return TestPlanResponse.model_validate(plan)

    async def approve_test_plan(self, plan_id: str) -> TestPlanResponse:
        plan = await self.repository.get_by_id(plan_id)
        if not plan:
            raise ValueError(f"Test plan {plan_id} not found")
        if plan.status not in ("ai_proposed", "draft"):
            raise ValueError(f"Cannot approve a plan in status '{plan.status}'")

        now = datetime.now(timezone.utc)
        plan = await self.repository.approve(plan_id, now)
        await self.db.commit()

        logger.info(f"[TEST PLAN SERVICE] Approved plan {plan_id}")
        return TestPlanResponse.model_validate(plan)

    async def reject_test_plan(self, plan_id: str) -> TestPlanResponse:
        """Reset plan back to draft."""
        plan = await self.repository.get_by_id(plan_id)
        if not plan:
            raise ValueError(f"Test plan {plan_id} not found")

        plan = await self.repository.set_status(plan_id, "draft")
        await self.db.commit()

        logger.info(f"[TEST PLAN SERVICE] Rejected / reset plan {plan_id} to draft")
        return TestPlanResponse.model_validate(plan)

    async def delete_test_plan(self, plan_id: str) -> bool:
        deleted = await self.repository.delete(plan_id)
        if deleted:
            await self.db.commit()
        return deleted

    async def delete_test_plans_by_project(self, project_id: str) -> int:
        """Supprime tous les Test Plans d'un projet."""
        count = await self.repository.delete_by_project(project_id)
        await self.db.commit()
        return count
    
    # ============================================================
    # AI EMAIL BODY GENERATION
    # ============================================================

    async def generate_email_body(
        self,
        plan_id: str,
        request: GenerateEmailBodyRequest,
    ) -> GenerateEmailBodyResponse:
        """Use the LLM to generate a professional email subject + body."""
        plan = await self.repository.get_by_id(plan_id)
        if not plan:
            raise ValueError(f"Test plan {plan_id} not found")

        from app.llm.llm_control import create_llm
        from app.ai_workflows.test_plan.config import LLM_MODEL, LLM_TEMPERATURE

        llm = create_llm(temperature=0.6, model=LLM_MODEL, max_tokens=1500)

        recipient_lines = "\n".join(
            f"  - {r.name or r.email} ({r.role})" for r in request.recipients
        )
        test_types_str = ", ".join(plan.test_types) if plan.test_types else "N/A"
        test_levels_str = ", ".join(plan.test_levels) if plan.test_levels else "N/A"

        prompt = f"""You are a QA engineer writing a professional email to share a test plan with stakeholders.

TEST PLAN DETAILS:
- Title: {plan.title}
- Status: {plan.status}
- Description: {plan.description or 'N/A'}
- Objective: {plan.objective or 'N/A'}
- Test Types: {test_types_str}
- Test Levels: {test_levels_str}
- Environment: {plan.environment or 'N/A'}
- Entry Criteria: {plan.entry_criteria or 'N/A'}
- Exit Criteria: {plan.exit_criteria or 'N/A'}

RECIPIENTS:
{recipient_lines}

{"ADDITIONAL CONTEXT: " + request.additional_context if request.additional_context else ""}

Write a professional email with:
1. A concise subject line (start with "Subject: ")
2. A professional body that:
   - Greets recipients by their roles
   - Briefly explains the purpose (sharing the test plan for review/information)
   - Highlights key points (scope, approach, timeline if available)
   - Includes a call-to-action appropriate for each role (e.g., PO for sign-off, Dev for build readiness)
   - Ends with a professional sign-off

Format your response EXACTLY as:
Subject: <subject here>
---
<email body here>"""

        response = await llm.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        # Parse subject and body
        parts = content.split("---", 1)
        subject_line = parts[0].strip()
        body = parts[1].strip() if len(parts) > 1 else content

        subject = subject_line.replace("Subject:", "").strip()
        if not subject:
            subject = f"Test Plan: {plan.title} — Ready for Review"

        logger.info(f"[TEST PLAN SERVICE] Generated email body for plan {plan_id}")
        return GenerateEmailBodyResponse(subject=subject, body=body)

    # ============================================================
    # EMAIL SENDING
    # ============================================================
    async def send_email(
        self,
        plan_id: str,
        request: SendEmailRequest,
    ) -> dict:
        """Send test plan report via email to specified recipients."""
        plan = await self.repository.get_by_id(plan_id)
        if not plan:
            raise ValueError(f"Test plan {plan_id} not found")
    
        subject = request.subject
        body_html = request.body
    
        if request.generate_body or not subject or not body_html:
            gen_req = GenerateEmailBodyRequest(recipients=request.recipients)
            generated = await self.generate_email_body(plan_id, gen_req)
            subject = subject or generated.subject
            if not body_html:
                body_html = self._render_email_html(plan, generated.body, request.recipients)
    
        # ✅ Générer le PDF du Test Plan
        from app.services.test_plan_export_service import TestPlanExportService
        exporter = TestPlanExportService()
        pdf_bytes = exporter.export_pdf(plan)
    
        # ✅ Envoyer l'email avec pièce jointe PDF
        from app.services.mail_service import send_test_plan_email_with_attachment
        recipient_emails = [r.email for r in request.recipients]
    
        await send_test_plan_email_with_attachment(
            recipients=recipient_emails,
            subject=subject,
            html_body=body_html,
            attachments=[
                {
                    "filename": f"Test_Plan_{plan.title.replace(' ', '_')[:50]}.pdf",
                    "content": pdf_bytes,
                    "mime_type": "application/pdf",
                }
            ],
        )
    
        logger.info(
            f"[TEST PLAN SERVICE] Email sent for plan {plan_id} "
            f"to {len(recipient_emails)} recipients with PDF attachment"
        )
        return {
            "sent_to": recipient_emails,
            "subject": subject,
            "message": f"Test plan report sent to {len(recipient_emails)} recipient(s) successfully with PDF attachment.",
        }

    # ============================================================
    # JIRA NOTIFICATION
    # ============================================================

    async def send_jira_notification(
        self,
        plan_id: str,
        request: JiraNotificationRequest,
        user_id: str,
    ) -> JiraNotificationResponse:
        """Create a Jira ticket notifying stakeholders of the test plan."""
        plan = await self.repository.get_by_id(plan_id)
        if not plan:
            raise ValueError(f"Test plan {plan_id} not found")

        from app.services.jira_session_manager import JiraSessionManager
        session_manager = JiraSessionManager(self.db)
        conn = await session_manager.get_connection(user_id)
        client = await session_manager.get_client(conn)

        summary = request.summary or f"[Test Plan] {plan.title}"
        description = request.description or self._build_jira_description(plan)

        issue_data = {
            "fields": {
                "project": {"key": request.project_key},
                "summary": summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": description}],
                        }
                    ],
                },
                "issuetype": {"name": request.issue_type},
                "priority": {"name": request.priority},
            }
        }

        url = (
            f"https://api.atlassian.com/ex/jira/{conn.cloud_id}"
            f"/rest/api/3/issue"
        )
        result = await client._request("POST", url, json=issue_data)

        issue_key = result.get("key", "")
        base_url = conn.jira_url.rstrip("/") if conn.jira_url else "https://atlassian.net"
        issue_url = f"{base_url}/browse/{issue_key}"

        logger.info(
            f"[TEST PLAN SERVICE] Jira ticket created: {issue_key} for plan {plan_id}"
        )
        return JiraNotificationResponse(
            issue_key=issue_key,
            issue_url=issue_url,
            summary=summary,
            message=f"Jira ticket {issue_key} created successfully.",
        )

    # ============================================================
    # STATISTICS
    # ============================================================

    async def get_summary_by_project(self, project_id: str) -> dict:
        return await self.repository.get_summary_by_project(project_id)

    # ============================================================
    # PRIVATE HELPERS
    # ============================================================

    async def _get_project(self, project_id: str) -> JiraProject:
        result = await self.db.execute(
            select(JiraProject).where(JiraProject.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            raise ValueError(f"Project {project_id} not found")
        return project

    @staticmethod
    def _risk_to_dict(risk) -> dict:
        return {
            "id": risk.id,
            "user_story_id": risk.user_story_id,
            "description": risk.description,
            "mitigation": risk.mitigation,
            "probability": risk.probability,
            "impact": risk.impact,
            "risk_score": risk.risk_score,
            "level": risk.level,
            "test_techniques": risk.test_techniques or [],
            "test_depth": risk.test_depth or "standard",
            "effort_allocation": risk.effort_allocation or "N/A",
            "reasoning": risk.reasoning or "",
        }

    @staticmethod
    def _story_to_dict(story, risk_info: dict = None) -> dict:
        result = {
            "issue_key": getattr(story, "issue_key", ""),
            "title": getattr(story, "title", getattr(story, "summary", "")),
            "acceptance_criteria": getattr(story, "acceptance_criteria", []),
        }
        if risk_info:
            result.update({
                "risk_level": risk_info.get("level", "unknown"),
                "risk_score": risk_info.get("risk_score", 0.0),
                "risk_description": risk_info.get("description", ""),
                "risk_mitigation": risk_info.get("mitigation", ""),
                "probability": risk_info.get("probability", None),
                "impact": risk_info.get("impact", None),
                "test_techniques": risk_info.get("test_techniques", []),
                "test_depth": risk_info.get("test_depth", "standard"),
                "effort_allocation": risk_info.get("effort_allocation", "N/A"),
                "reasoning": risk_info.get("reasoning", ""),
            })
        
        return result

    @staticmethod
    def _build_jira_description(plan: TestPlan) -> str:
        lines = [
            f"Test Plan: {plan.title}",
            f"Status: {plan.status}",
            "",
        ]
        if plan.description:
            lines += [f"Description: {plan.description}", ""]
        if plan.objective:
            lines += [f"Objective: {plan.objective}", ""]
        if plan.test_types:
            lines += [f"Test Types: {', '.join(plan.test_types)}", ""]
        if plan.test_levels:
            lines += [f"Test Levels: {', '.join(plan.test_levels)}", ""]
        if plan.environment:
            lines += [f"Environment: {plan.environment}", ""]
        if plan.entry_criteria:
            lines += [f"Entry Criteria:\n{plan.entry_criteria}", ""]
        if plan.exit_criteria:
            lines += [f"Exit Criteria:\n{plan.exit_criteria}", ""]
        if plan.approach:
            lines += [f"Approach:\n{plan.approach}", ""]
        lines.append("Generated by TestForge AI")
        return "\n".join(lines)

    @staticmethod
    def _render_email_html(
        plan: TestPlan,
        text_body: str,
        recipients: List[EmailRecipient],
    ) -> str:
        """Render HTML email with Test Plan details."""
        
        # Helper pour les lignes d'information
        def info_row(label, value):
            if not value:
                return ""
            return (
                '<tr>'
                '<td style="padding: 10px 0; width: 130px; font-weight: 700; color: #6b7280; '
                'text-transform: uppercase; letter-spacing: 0.04em; font-size: 11px; vertical-align: top;">'
                f'{label}</td>'
                '<td style="padding: 10px 0; color: #374151; font-size: 13px; line-height: 1.5;">'
                f'{value}</td>'
                '</tr>'
            )
        
        # Helper pour les paragraphes
        def format_paragraphs(text):
            if not text:
                return ""
            paragraphs = text.split('\n\n')
            return ''.join(
                f'<p style="margin: 0 0 12px 0;">{p.strip()}</p>' 
                for p in paragraphs if p.strip()
            )
        
        test_types = ", ".join(plan.test_types) if plan.test_types else "—"
        test_levels = ", ".join(plan.test_levels) if plan.test_levels else "—"
        scope_refs = ", ".join(plan.scope_refs) if plan.scope_refs else "—"
        
        status_display = plan.status.replace('_', ' ').title() if plan.status else 'Draft'
        status_color = "#059669" if plan.status == "approved" else "#d97706" if plan.status == "ai_proposed" else "#6b7280"
        status_bg = "#f0fdf4" if plan.status == "approved" else "#fffbeb" if plan.status == "ai_proposed" else "#f3f4f6"
        
        # Construire les sections optionnelles
        in_scope_html = ''
        if plan.in_scope:
            in_scope_html = (
                '<div style="margin-top:20px;">'
                '<div style="font-size:12px;font-weight:700;color:#059669;margin-bottom:8px;">✓ In Scope</div>'
                '<div style="font-size:13px;color:#374151;background:#f0fdf4;padding:12px;border-radius:8px;border-left:3px solid #059669;">'
                f'{plan.in_scope}</div></div>'
            )
        
        out_of_scope_html = ''
        if plan.out_of_scope:
            out_of_scope_html = (
                '<div style="margin-top:16px;">'
                '<div style="font-size:12px;font-weight:700;color:#dc2626;margin-bottom:8px;">✗ Out of Scope</div>'
                '<div style="font-size:13px;color:#374151;background:#fef2f2;padding:12px;border-radius:8px;border-left:3px solid #dc2626;">'
                f'{plan.out_of_scope}</div></div>'
            )
        
        # Construire le corps du texte formaté
        body_paragraphs = format_paragraphs(text_body)
        
        # Construire les lignes d'information
        info_rows = (
            info_row("Objective", plan.objective) +
            info_row("Test Types", test_types) +
            info_row("Test Levels", test_levels) +
            info_row("Environment", plan.environment) +
            info_row("Entry Criteria", plan.entry_criteria) +
            info_row("Exit Criteria", plan.exit_criteria) +
            info_row("Approach", plan.approach) +
            info_row("Scope Type", plan.scope_type) +
            info_row("Scope References", scope_refs)
        )
        
        # ============================================================
        # SECTIONS ENRICHIES (Risques, PERT, Recommandations)
        # ============================================================
        
        # 1. SECTION RISQUES
        risks_html = ''
        if plan.risk_analysis:
            mapping = plan.risk_analysis.get('mapping_table', [])
            distribution = plan.risk_analysis.get('distribution', {})
            
            if distribution:
                total = distribution.get('total', 1)
                critical_pct = round(distribution.get('critical', 0) / total * 100) if total > 0 else 0
                high_pct = round(distribution.get('high', 0) / total * 100) if total > 0 else 0
                medium_pct = round(distribution.get('medium', 0) / total * 100) if total > 0 else 0
                low_pct = round(distribution.get('low', 0) / total * 100) if total > 0 else 0
                
                critical_risks = [r for r in mapping if r.get('risk_level') == 'critical']
                high_risks = [r for r in mapping if r.get('risk_level') == 'high']
                
                risks_rows = ''
                for r in (critical_risks + high_risks)[:5]:
                    level_color = "#dc2626" if r.get('risk_level') == 'critical' else "#d97706"
                    level_bg = "#fef2f2" if r.get('risk_level') == 'critical' else "#fffbeb"
                    level_icon = "🔴" if r.get('risk_level') == 'critical' else "🟠"
                    
                    mitigation = r.get('mitigation', 'No mitigation defined')
                    techniques = ', '.join(r.get('test_techniques', []))
                    test_depth = r.get('test_depth', 'N/A')
                    effort = r.get('effort_allocation', 'N/A')
                    
                    risks_rows += f'''
                    <tr>
                        <td style="padding:12px;border-bottom:1px solid #e5e7eb;background:{level_bg};">
                            <div style="font-weight:700;color:{level_color};font-size:13px;margin-bottom:4px;">
                                {level_icon} [{r.get('issue_key')}] {r.get('title', 'N/A')}
                            </div>
                            <div style="font-size:12px;color:#374151;margin-bottom:6px;">
                                <strong>Risk:</strong> {r.get('risk_description', 'N/A')[:120]}
                            </div>
                            <div style="font-size:12px;color:#6b7280;margin-bottom:6px;">
                                <strong>Score:</strong> {r.get('risk_score')} (P{r.get('probability')}×I{r.get('impact')}) 
                                | <strong>Depth:</strong> {test_depth} 
                                | <strong>Effort:</strong> {effort}
                            </div>
                            <div style="font-size:12px;color:#059669;margin-bottom:4px;background:#f0fdf4;padding:6px;border-radius:4px;">
                                <strong>🛡️ Mitigation:</strong> {mitigation[:150]}
                            </div>
                            <div style="font-size:11px;color:#6366f1;">
                                <strong>🧪 Techniques:</strong> {techniques}
                            </div>
                        </td>
                    </tr>'''
                
                risks_html = f'''
                <hr style="border:none;border-top:2px solid #dc2626;margin:24px 0;">
                
                <h2 style="font-size:13px;font-weight:700;color:#dc2626;text-transform:uppercase;letter-spacing:0.04em;margin:0 0 12px 0;">
                    ⚠️ Risk Analysis Summary
                </h2>
                
                <!-- Distribution -->
                <div style="margin-bottom:16px;background:#f9fafb;padding:12px;border-radius:8px;">
                    <div style="font-size:12px;font-weight:600;color:#111827;margin-bottom:8px;">Risk Distribution</div>
                    <div style="display:flex;gap:8px;align-items:stretch;margin-bottom:8px;">
                        <div style="flex:1;text-align:center;background:#fef2f2;padding:8px;border-radius:6px;">
                            <div style="font-size:20px;font-weight:800;color:#dc2626;">{distribution.get('critical', 0)}</div>
                            <div style="font-size:10px;color:#6b7280;">CRITICAL ({critical_pct}%)</div>
                        </div>
                        <div style="flex:1;text-align:center;background:#fffbeb;padding:8px;border-radius:6px;">
                            <div style="font-size:20px;font-weight:800;color:#d97706;">{distribution.get('high', 0)}</div>
                            <div style="font-size:10px;color:#6b7280;">HIGH ({high_pct}%)</div>
                        </div>
                        <div style="flex:1;text-align:center;background:#f0fdf4;padding:8px;border-radius:6px;">
                            <div style="font-size:20px;font-weight:800;color:#059669;">{distribution.get('medium', 0)}</div>
                            <div style="font-size:10px;color:#6b7280;">MEDIUM ({medium_pct}%)</div>
                        </div>
                        <div style="flex:1;text-align:center;background:#f3f4f6;padding:8px;border-radius:6px;">
                            <div style="font-size:20px;font-weight:800;color:#6b7280;">{distribution.get('low', 0)}</div>
                            <div style="font-size:10px;color:#6b7280;">LOW ({low_pct}%)</div>
                        </div>
                    </div>
                    <div style="font-size:11px;color:#6b7280;text-align:center;">
                        High Risk Ratio: {(distribution.get('high_risk_ratio', 0) * 100):.0f}% 
                        ({distribution.get('critical', 0) + distribution.get('high', 0)}/{distribution.get('total', 0)} stories)
                    </div>
                </div>
                
                <!-- Critical & High Risks Table -->
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:12px;">
                    {risks_rows}
                </table>
                '''
        
        # 2. SECTION PERT ESTIMATION
        estimation_html = ''
        if plan.estimation:
            est = plan.estimation
            inputs = est.get('inputs', {})
            
            breakdown_rows = ''
            for item in est.get('breakdown_by_risk', []):
                breakdown_rows += f'''
                <tr>
                    <td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;font-size:12px;font-weight:600;text-transform:uppercase;">
                        {item.get('level', 'N/A')}
                    </td>
                    <td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;font-size:12px;text-align:center;">
                        {item.get('story_count', 0)}
                    </td>
                    <td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;font-size:12px;text-align:center;">
                        {item.get('subtotal_optimistic', 0)}
                    </td>
                    <td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;font-size:12px;text-align:center;">
                        {item.get('subtotal_realistic', 0)}
                    </td>
                    <td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;font-size:12px;text-align:center;">
                        {item.get('subtotal_pessimistic', 0)}
                    </td>
                </tr>'''
            
            estimation_html = f'''
            <hr style="border:none;border-top:2px solid #6366f1;margin:24px 0;">
            
            <h2 style="font-size:13px;font-weight:700;color:#6366f1;text-transform:uppercase;letter-spacing:0.04em;margin:0 0 12px 0;">
                📊 PERT Estimation
            </h2>
            
            <div style="margin-bottom:16px;background:#f9fafb;padding:12px;border-radius:8px;">
                <div style="font-size:12px;font-weight:600;color:#111827;margin-bottom:8px;">
                    {est.get('formula', 'E = (O + 4×M + P) / 6')}
                </div>
                <div style="display:flex;gap:12px;margin-bottom:12px;">
                    <div style="flex:1;text-align:center;background:#fef2f2;padding:10px;border-radius:6px;">
                        <div style="font-size:11px;color:#6b7280;">OPTIMISTIC</div>
                        <div style="font-size:24px;font-weight:800;color:#dc2626;">{inputs.get('optimistic', '?')}</div>
                        <div style="font-size:10px;color:#6b7280;">working days</div>
                    </div>
                    <div style="flex:1;text-align:center;background:#f0fdf4;padding:10px;border-radius:6px;">
                        <div style="font-size:11px;color:#6b7280;">MOST LIKELY</div>
                        <div style="font-size:24px;font-weight:800;color:#059669;">{inputs.get('most_likely', '?')}</div>
                        <div style="font-size:10px;color:#6b7280;">working days</div>
                    </div>
                    <div style="flex:1;text-align:center;background:#fffbeb;padding:10px;border-radius:6px;">
                        <div style="font-size:11px;color:#6b7280;">PESSIMISTIC</div>
                        <div style="font-size:24px;font-weight:800;color:#d97706;">{inputs.get('pessimistic', '?')}</div>
                        <div style="font-size:10px;color:#6b7280;">working days</div>
                    </div>
                </div>
                <div style="text-align:center;background:linear-gradient(135deg,#6366f1,#4f46e5);padding:12px;border-radius:8px;">
                    <div style="font-size:11px;color:rgba(255,255,255,0.8);">PERT ESTIMATE</div>
                    <div style="font-size:32px;font-weight:800;color:#fff;">{est.get('calculation', '?').split('= ')[-1] if '= ' in est.get('calculation', '') else '?'}</div>
                    <div style="font-size:11px;color:rgba(255,255,255,0.8);">{est.get('confidence_interval', '')}</div>
                </div>
            </div>
            
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:12px;border-collapse:collapse;">
                <tr style="background:#f3f4f6;">
                    <td style="padding:8px;font-size:11px;font-weight:700;color:#6b7280;text-transform:uppercase;">Risk Level</td>
                    <td style="padding:8px;font-size:11px;font-weight:700;color:#6b7280;text-transform:uppercase;text-align:center;">Stories</td>
                    <td style="padding:8px;font-size:11px;font-weight:700;color:#6b7280;text-transform:uppercase;text-align:center;">Optimistic</td>
                    <td style="padding:8px;font-size:11px;font-weight:700;color:#6b7280;text-transform:uppercase;text-align:center;">Realistic</td>
                    <td style="padding:8px;font-size:11px;font-weight:700;color:#6b7280;text-transform:uppercase;text-align:center;">Pessimistic</td>
                </tr>
                {breakdown_rows}
            </table>
            '''
        
        # 3. SECTION RECOMMENDATIONS
        recommendations_html = ''
        if plan.risk_analysis and plan.risk_analysis.get('aggregated_recommendations'):
            aggr = plan.risk_analysis['aggregated_recommendations']
            
            techniques_list = '<br>'.join(
                f'✓ {tech} ({freq} risks)' 
                for tech, freq in aggr.get('technique_distribution', {}).items()
            ) if aggr.get('technique_distribution') else 'N/A'
            
            depth_items = aggr.get('test_depth_distribution', {})
            effort_items = aggr.get('effort_breakdown', {})
            
            recommendations_html = f'''
            <hr style="border:none;border-top:2px solid #059669;margin:24px 0;">
            
            <h2 style="font-size:13px;font-weight:700;color:#059669;text-transform:uppercase;letter-spacing:0.04em;margin:0 0 12px 0;">
                🧪 Test Recommendations
            </h2>
            
            <div style="display:flex;gap:12px;margin-bottom:12px;">
                <div style="flex:1;background:#f0fdf4;padding:12px;border-radius:8px;">
                    <div style="font-size:12px;font-weight:600;color:#059669;margin-bottom:8px;">Recommended Techniques</div>
                    <div style="font-size:12px;color:#374151;line-height:1.8;">{techniques_list}</div>
                </div>
                <div style="flex:1;background:#eef2ff;padding:12px;border-radius:8px;">
                    <div style="font-size:12px;font-weight:600;color:#6366f1;margin-bottom:8px;">Test Depth</div>
                    <div style="font-size:11px;color:#374151;">
                        Comprehensive: {depth_items.get('comprehensive', 0)} stories<br>
                        Thorough: {depth_items.get('thorough', 0)} stories<br>
                        Standard: {depth_items.get('standard', 0)} stories<br>
                        Smoke: {depth_items.get('smoke', 0)} stories
                    </div>
                </div>
            </div>
            
            <div style="background:#fffbeb;padding:12px;border-radius:8px;">
                <div style="font-size:12px;font-weight:600;color:#d97706;margin-bottom:8px;">Effort Allocation</div>
                <div style="font-size:11px;color:#374151;">
                    Critical: {effort_items.get('critical_effort', '0%')}<br>
                    High: {effort_items.get('high_effort', '0%')}<br>
                    Medium: {effort_items.get('medium_effort', '0%')}<br>
                    Low: {effort_items.get('low_effort', '0%')}
                </div>
            </div>
            '''
        
        # ============================================================
        # HTML FINAL
        # ============================================================
        
        html = f'''<!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"><title>Test Plan: {plan.title}</title></head>
    <body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f9fafb;padding:24px 0;">
        <tr><td align="center">
            <table width="640" cellpadding="0" cellspacing="0" border="0" style="max-width:640px;width:100%;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,0.08);">
                
                <!-- Header -->
                <tr>
                    <td style="background:linear-gradient(135deg,#6366f1 0%,#4f46e5 100%);padding:28px 32px;text-align:center;">
                        <div style="font-size:24px;font-weight:800;color:#fff;letter-spacing:-0.02em;margin-bottom:6px;">TEST<span style="color:#c7d2fe;">FORGE</span></div>
                        <div style="font-size:11px;color:rgba(255,255,255,0.7);letter-spacing:0.04em;text-transform:uppercase;">Intelligent Test Automation</div>
                    </td>
                </tr>
                
                <!-- Content -->
                <tr>
                    <td style="padding:32px 36px;">
                        
                        <div style="font-size:14px;color:#374151;line-height:1.6;margin-bottom:20px;">Hello <strong>Test Team</strong>,</div>
                        
                        <div style="margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid #e5e7eb;">
                            <h1 style="font-size:20px;font-weight:700;color:#111827;margin:0 0 8px 0;">📋 {plan.title}</h1>
                            <div style="display:inline-flex;align-items:center;gap:6px;background:{status_bg};color:{status_color};font-size:11px;font-weight:700;padding:4px 12px;border-radius:20px;text-transform:uppercase;letter-spacing:0.04em;">✓ Status: {status_display}</div>
                        </div>
                        
                        {body_paragraphs}
                        
                        <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;">
                        
                        <h2 style="font-size:13px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:0.04em;margin:0 0 16px 0;">📊 Test Plan Details</h2>
                        
                        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="font-size:13px;">
                            {info_rows}
                        </table>
                        
                        {in_scope_html}
                        {out_of_scope_html}
                        
                        {risks_html}
                        {estimation_html}
                        {recommendations_html}
                        
                        <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;">
                        
                        <!-- Call to Action -->
                        <div style="margin:24px 0;text-align:center;background:#f9fafb;padding:20px;border-radius:10px;border:1px solid #e5e7eb;">
                            <div style="font-size:13px;font-weight:600;color:#111827;margin-bottom:16px;">🎯 Action Required</div>
                            <div style="color:#6b7280;font-size:12px;line-height:1.6;margin-bottom:16px;">Please review the test plan and provide your feedback or approval.</div>
                            <div style="background:#eef2ff;padding:10px;border-radius:8px;font-size:12px;color:#4f46e5;margin-bottom:6px;">💡 Product Owner: Please review scope and objectives</div>
                            <div style="background:#f0fdf4;padding:10px;border-radius:8px;font-size:12px;color:#059669;">🔧 Dev Team: Review entry/exit criteria and environment setup</div>
                        </div>
                        
                        <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0 16px 0;">
                        <div style="font-size:11px;color:#9ca3af;text-align:center;line-height:1.5;">
                            <p style="margin:0 0 8px 0;">Generated by <strong>TestForge AI</strong> — Intelligent Test Automation</p>
                            <p style="margin:0;">© 2026 TestForge. All rights reserved.</p>
                        </div>
                        
                    </td>
                </tr>
                
            </table>
        </td></tr>
    </table>
    </body>
    </html>'''
        
        return html