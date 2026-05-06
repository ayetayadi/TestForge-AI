"""
Execution Report Service
Builds full execution reports from test runs, sends emails, creates Jira issues.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import Defect
from app.models.enums import (
    DefectSeverity, DefectStatus, StepType, TestResultStatus
)
from app.repositories import playwright_repository as repo

logger = logging.getLogger(__name__)


# ============================================================
# REPORT BUILDER
# ============================================================

async def build_full_report(db: AsyncSession, test_run_id: str) -> Dict[str, Any]:
    """
    Build a comprehensive execution report from a test run ID.
    Includes: run config, result, all steps (with LLM reasoning), test case info, defect.
    """
    test_run = await repo.get_test_run(db, test_run_id)
    if not test_run:
        return {"error": f"TestRun {test_run_id} not found"}

    result = await repo.get_test_result(db, test_run_id)
    steps = await repo.get_steps(db, test_run_id)

    # Get test case via script version
    test_case_data = None
    script_version = None
    if test_run.script_version_id:
        script_version = await repo.get_script_version(db, test_run.script_version_id)
        if script_version:
            test_case = await repo.get_test_case(db, script_version.test_case_id)
            if test_case:
                test_case_data = {
                    "id": test_case.id,
                    "tc_code": test_case.tc_code,
                    "title": test_case.title,
                    "description": test_case.description,
                    "priority": test_case.priority,
                    "test_type": test_case.test_type,
                    "steps": test_case.steps or [],
                    "expected_results": test_case.expected_results or [],
                    "user_story_id": test_case.user_story_id,
                }

    # Separate steps by type
    think_steps = [s for s in steps if s.step_type == StepType.THINK]
    act_steps = [s for s in steps if s.step_type != StepType.THINK]
    failed_steps = [s for s in steps if s.status.value == "failed"]

    # Build LLM reasoning text from think steps
    llm_reasoning_parts = []
    for s in think_steps:
        content = s.content.strip()
        if content and len(content) > 10:
            llm_reasoning_parts.append(content)
    llm_reasoning = "\n\n---\n\n".join(llm_reasoning_parts)

    # Get defect if exists
    defect_data = None
    if test_case_data:
        defect = await _get_defect_by_test_run(db, test_run_id, test_case_data["id"])
        if defect:
            defect_data = _serialize_defect(defect)

    # Build error summary
    error_summary = None
    if result and result.status != TestResultStatus.PASSED:
        error_lines = []
        if result.error_message:
            error_lines.append(result.error_message)
        for s in failed_steps[:3]:
            if s.content:
                error_lines.append(s.content[:500])
        error_summary = "\n".join(error_lines) if error_lines else "Unknown error"

    # Serialise steps
    serialized_steps = []
    for s in steps:
        serialized_steps.append({
            "order": s.step_order,
            "type": s.step_type.value,
            "tool_name": s.tool_name,
            "content": s.content,
            "status": s.status.value,
            "duration": s.duration,
            "screenshot_b64": s.screenshot_b64,
        })

    return {
        "test_run": {
            "id": test_run.id,
            "status": test_run.status.value,
            "browser": test_run.browser,
            "base_url": test_run.base_url,
            "headless": test_run.headless,
            "duration": test_run.duration,
            "started_at": test_run.started_at.isoformat() if test_run.started_at else None,
            "completed_at": test_run.completed_at.isoformat() if test_run.completed_at else None,
        },
        "result": {
            "status": result.status.value if result else None,
            "justification": result.justification if result else None,
            "error_message": result.error_message if result else None,
            "screenshot_b64": result.screenshot_b64 if result else None,
            "duration": result.duration if result else None,
            "step_count": result.step_count if result else 0,
            "completed_at": result.completed_at.isoformat() if result and result.completed_at else None,
        } if result else None,
        "test_case": test_case_data,
        "script_version": {
            "id": script_version.id,
            "version_number": script_version.version_number,
            "source": script_version.source.value,
            "placeholder_count": script_version.placeholder_count,
        } if script_version else None,
        "steps": serialized_steps,
        "llm_reasoning": llm_reasoning,
        "error_summary": error_summary,
        "defect": defect_data,
        "stats": {
            "total_steps": len(steps),
            "think_steps": len(think_steps),
            "act_steps": len(act_steps),
            "failed_steps": len(failed_steps),
            "success_rate": round(
                ((len(steps) - len(failed_steps)) / len(steps) * 100) if steps else 0, 1
            ),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def _get_defect_by_test_run(
    db: AsyncSession, test_run_id: str, test_case_id: str
) -> Optional[Defect]:
    """Find the most recent defect linked to this test case from execution."""
    from sqlalchemy import desc as sql_desc
    result = await db.execute(
        select(Defect)
        .where(Defect.test_case_id == test_case_id)
        .where(Defect.logs.contains(test_run_id))
        .order_by(sql_desc(Defect.created_at))
        .limit(1)
    )
    defect = result.scalar_one_or_none()
    if not defect:
        # fallback: most recent defect for this test case
        result2 = await db.execute(
            select(Defect)
            .where(Defect.test_case_id == test_case_id)
            .order_by(sql_desc(Defect.created_at))
            .limit(1)
        )
        defect = result2.scalar_one_or_none()
    return defect


def _serialize_defect(defect: Defect) -> Dict[str, Any]:
    return {
        "id": defect.id,
        "title": defect.title,
        "description": defect.description,
        "severity": defect.severity.value,
        "status": defect.status.value,
        "reproduction_steps": defect.reproduction_steps or [],
        "jira_issue_key": defect.jira_issue_key,
        "jira_project_key": defect.jira_project_key,
        "created_at": defect.created_at.isoformat() if defect.created_at else None,
    }


# ============================================================
# AUTO-DEFECT CREATION FROM EXECUTION
# ============================================================

async def create_defect_from_execution(
    db: AsyncSession,
    test_run_id: str,
    test_case_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Create a Defect record from a failed Playwright execution.
    Returns None if test case has no user_story_id (required FK).
    """
    test_case = await repo.get_test_case(db, test_case_id)
    if not test_case:
        logger.warning(f"[DEFECT] Test case {test_case_id} not found, skipping defect creation")
        return None

    if not test_case.user_story_id:
        logger.warning(
            f"[DEFECT] Test case {test_case_id} has no user_story_id — defect creation skipped. "
            "Link this test case to a user story to enable defect tracking."
        )
        return None

    result = await repo.get_test_result(db, test_run_id)
    steps = await repo.get_steps(db, test_run_id)
    test_run = await repo.get_test_run(db, test_run_id)

    think_steps = [s for s in steps if s.step_type == StepType.THINK]
    act_steps = [s for s in steps if s.step_type.value == "act"]
    failed_steps = [s for s in steps if s.status.value == "failed"]

    # Build reproduction steps from act steps
    reproduction_steps = []
    for i, s in enumerate(act_steps[:15]):
        tool = f"[{s.tool_name}] " if s.tool_name else ""
        reproduction_steps.append(f"{i + 1}. {tool}{s.content[:200]}")

    # LLM reasoning from think steps
    llm_reasoning = "\n".join([s.content[:800] for s in think_steps[:5]])

    # Error message
    error_msg = result.error_message if result else None
    if not error_msg and failed_steps:
        error_msg = failed_steps[0].content[:500]

    # Screenshot (from result or first failed step)
    screenshot = None
    if result and result.screenshot_b64:
        screenshot = result.screenshot_b64
    elif failed_steps:
        for fs in failed_steps:
            if fs.screenshot_b64:
                screenshot = fs.screenshot_b64
                break

    # Determine severity from result status
    status_val = result.status.value if result else "error"
    if status_val == "error":
        severity = DefectSeverity.HIGH
    else:
        priority = (test_case.priority or "medium").lower()
        severity = {
            "critical": DefectSeverity.CRITICAL,
            "high": DefectSeverity.HIGH,
            "medium": DefectSeverity.MEDIUM,
            "low": DefectSeverity.LOW,
        }.get(priority, DefectSeverity.HIGH)

    title = f"[PLAYWRIGHT] {test_case.tc_code} — {test_case.title[:120]}"
    description = (
        f"Playwright E2E test failed for {test_case.tc_code}.\n\n"
        f"Browser: {test_run.browser if test_run else 'unknown'}\n"
        f"URL: {test_run.base_url if test_run else 'unknown'}\n"
        f"Duration: {test_run.duration if test_run else 0:.1f}s\n\n"
        f"Error:\n{error_msg or 'No error message captured'}\n\n"
        f"LLM Reasoning:\n{llm_reasoning[:1500] if llm_reasoning else 'No reasoning captured'}"
    )

    # Log all info for developer
    logs_text = (
        f"TestRun ID: {test_run_id}\n"
        f"Steps: {len(steps)} total, {len(failed_steps)} failed\n\n"
        + "\n".join([
            f"[{s.step_type.value.upper()}] {s.status.value} | "
            f"{s.tool_name or '-'} | {s.content[:200]}"
            for s in steps
        ])
    )

    defect = Defect(
        id=str(uuid.uuid4()),
        user_story_id=test_case.user_story_id,
        test_case_id=test_case_id,
        title=title,
        description=description,
        severity=severity,
        correction_priority=test_case.priority or "medium",
        status=DefectStatus.OPEN,
        reproduction_steps=reproduction_steps,
        screenshot_b64=screenshot,
        logs=logs_text[:10000],
        detected_issues=[error_msg[:300]] if error_msg else [],
        jira_project_key=None,
    )

    db.add(defect)
    await db.flush()

    logger.info(
        f"[DEFECT] Auto-created defect {defect.id} for test case {test_case.tc_code} "
        f"(severity={severity.value})"
    )

    return _serialize_defect(defect)


# ============================================================
# EMAIL — EXECUTION REPORT
# ============================================================

async def send_execution_report_email(
    report: Dict[str, Any],
    recipients: List[str],
) -> None:
    """Build and send a rich HTML execution report email."""
    from app.services.mail_service import send_test_plan_email

    tc = report.get("test_case") or {}
    run = report.get("test_run") or {}
    result = report.get("result") or {}
    stats = report.get("stats") or {}
    defect = report.get("defect")
    steps = report.get("steps") or []

    status = result.get("status") or "unknown"
    status_color = {
        "passed": "#16a34a",
        "failed": "#dc2626",
        "error": "#ea580c",
        "skipped": "#6b7280",
    }.get(status, "#6b7280")
    status_icon = {"passed": "✅", "failed": "❌", "error": "⚠️"}.get(status, "ℹ️")

    duration_s = round((run.get("duration") or 0), 1)

    # Build steps HTML (only failed + last 5 act steps)
    relevant_steps = [s for s in steps if s.get("status") == "failed"][:5]
    if not relevant_steps:
        relevant_steps = [s for s in steps if s.get("type") in ("act", "observe")][-5:]

    steps_html = ""
    for s in relevant_steps:
        color = "#dc2626" if s.get("status") == "failed" else "#374151"
        icon = "❌" if s.get("status") == "failed" else "✅"
        tool = f'<code style="background:#f3f4f6;padding:1px 4px;border-radius:3px;font-size:11px;">{s.get("tool_name","")}</code> ' if s.get("tool_name") else ""
        steps_html += f"""
        <tr>
            <td style="padding:8px 12px;color:#6b7280;font-size:12px;">{s.get("order","")}</td>
            <td style="padding:8px 12px;font-size:12px;">{tool}{(s.get("content") or "")[:200]}</td>
            <td style="padding:8px 12px;text-align:center;font-size:13px;">{icon}</td>
        </tr>"""

    # LLM reasoning
    reasoning = report.get("llm_reasoning") or ""
    reasoning_html = ""
    if reasoning:
        paragraphs = [p.strip() for p in reasoning.split("\n---\n") if p.strip()]
        for p in paragraphs[:3]:
            reasoning_html += f'<p style="color:#374151;font-size:13px;line-height:1.6;margin:0 0 10px 0;">{p[:600]}</p>'

    # Defect section
    defect_html = ""
    if defect:
        sev_color = {
            "critical": "#dc2626", "high": "#ea580c",
            "medium": "#d97706", "low": "#16a34a",
        }.get(defect.get("severity", "high"), "#6b7280")
        defect_html = f"""
        <div style="margin:24px 0;padding:16px;background:#fef2f2;border-left:4px solid #dc2626;border-radius:6px;">
            <h3 style="margin:0 0 8px 0;color:#dc2626;font-size:14px;">🐛 Defect Created</h3>
            <p style="margin:0 0 6px 0;font-size:13px;"><strong>{defect.get("title","")}</strong></p>
            <p style="margin:0;font-size:12px;color:#6b7280;">
                Severity: <span style="color:{sev_color};font-weight:600;">{(defect.get("severity") or "").upper()}</span>
                &nbsp;|&nbsp; Status: {defect.get("status","open").upper()}
                {f'&nbsp;|&nbsp; Jira: <strong>{defect.get("jira_issue_key")}</strong>' if defect.get("jira_issue_key") else ""}
            </p>
        </div>"""

    # Error summary
    error_html = ""
    err = report.get("error_summary") or result.get("error_message") or ""
    if err and status != "passed":
        error_html = f"""
        <div style="margin:16px 0;padding:14px;background:#fef2f2;border-radius:6px;border:1px solid #fecaca;">
            <h4 style="margin:0 0 8px 0;color:#dc2626;font-size:13px;">Error Details</h4>
            <pre style="margin:0;font-size:12px;color:#374151;white-space:pre-wrap;font-family:monospace;">{err[:800]}</pre>
        </div>"""

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:750px;margin:0 auto;background:#f9fafb;">

        <!-- Header -->
        <div style="background:{status_color};padding:24px 32px;border-radius:8px 8px 0 0;text-align:center;">
            <h1 style="color:white;margin:0;font-size:24px;">
                {status_icon} Execution Report — {status.upper()}
            </h1>
            <p style="color:rgba(255,255,255,0.85);margin:6px 0 0 0;font-size:13px;">
                TestForge AI · Playwright E2E Testing
            </p>
        </div>

        <div style="background:white;padding:32px;border-radius:0 0 8px 8px;border:1px solid #e5e7eb;">

            <!-- Test Case Info -->
            <div style="margin-bottom:24px;padding:16px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;">
                <h2 style="margin:0 0 10px 0;color:#1e293b;font-size:16px;">
                    {tc.get("tc_code","N/A")} — {tc.get("title","Unknown Test Case")}
                </h2>
                <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:#64748b;">
                    <span>Type: <strong>{(tc.get("test_type") or "N/A").upper()}</strong></span>
                    <span>Priority: <strong>{(tc.get("priority") or "N/A").upper()}</strong></span>
                    <span>Browser: <strong>{run.get("browser","N/A")}</strong></span>
                    <span>URL: <strong>{run.get("base_url","N/A")}</strong></span>
                    <span>Duration: <strong>{duration_s}s</strong></span>
                </div>
            </div>

            <!-- Stats -->
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px;">
                <div style="background:#f0fdf4;padding:14px;border-radius:8px;text-align:center;border:1px solid #bbf7d0;">
                    <div style="font-size:22px;font-weight:700;color:#16a34a;">{stats.get("success_rate",0)}%</div>
                    <div style="font-size:11px;color:#6b7280;margin-top:2px;">Success Rate</div>
                </div>
                <div style="background:#f0f9ff;padding:14px;border-radius:8px;text-align:center;border:1px solid #bae6fd;">
                    <div style="font-size:22px;font-weight:700;color:#0284c7;">{stats.get("total_steps",0)}</div>
                    <div style="font-size:11px;color:#6b7280;margin-top:2px;">Total Steps</div>
                </div>
                <div style="background:#fef9c3;padding:14px;border-radius:8px;text-align:center;border:1px solid #fef08a;">
                    <div style="font-size:22px;font-weight:700;color:#ca8a04;">{stats.get("act_steps",0)}</div>
                    <div style="font-size:11px;color:#6b7280;margin-top:2px;">Actions</div>
                </div>
                <div style="background:#fef2f2;padding:14px;border-radius:8px;text-align:center;border:1px solid #fecaca;">
                    <div style="font-size:22px;font-weight:700;color:#dc2626;">{stats.get("failed_steps",0)}</div>
                    <div style="font-size:11px;color:#6b7280;margin-top:2px;">Errors</div>
                </div>
            </div>

            {error_html}

            <!-- LLM Reasoning -->
            {f'''
            <div style="margin-bottom:24px;">
                <h3 style="color:#1e293b;font-size:14px;margin:0 0 12px 0;display:flex;align-items:center;gap:6px;">
                    🧠 AI Reasoning
                </h3>
                <div style="background:#fafafa;padding:16px;border-radius:6px;border:1px solid #e5e7eb;">
                    {reasoning_html}
                </div>
            </div>
            ''' if reasoning_html else ''}

            <!-- Step Details -->
            {f'''
            <div style="margin-bottom:24px;">
                <h3 style="color:#1e293b;font-size:14px;margin:0 0 12px 0;">
                    🔍 Execution Steps ({"errors + " if [s for s in steps if s.get("status")=="failed"] else ""}last actions)
                </h3>
                <table style="width:100%;border-collapse:collapse;font-size:12px;">
                    <thead>
                        <tr style="background:#f8fafc;border-bottom:1px solid #e2e8f0;">
                            <th style="padding:8px 12px;text-align:left;color:#64748b;">#</th>
                            <th style="padding:8px 12px;text-align:left;color:#64748b;">Action / Observation</th>
                            <th style="padding:8px 12px;text-align:center;color:#64748b;">Status</th>
                        </tr>
                    </thead>
                    <tbody>{steps_html}</tbody>
                </table>
            </div>
            ''' if steps_html else ''}

            {defect_html}

            <!-- Justification -->
            {f'''
            <div style="margin-bottom:24px;padding:14px;background:#f0f9ff;border-left:4px solid #0284c7;border-radius:6px;">
                <h4 style="margin:0 0 6px 0;color:#0284c7;font-size:13px;">Result Justification</h4>
                <p style="margin:0;color:#374151;font-size:13px;">{result.get("justification","")}</p>
            </div>
            ''' if result.get("justification") else ''}

            <!-- Footer -->
            <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0 16px 0;"/>
            <p style="color:#9ca3af;font-size:11px;text-align:center;margin:0;">
                Generated by TestForge AI · {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
            </p>
        </div>
    </div>
    """

    tc_code = tc.get("tc_code", "N/A")
    subject = f"[TestForge] {status_icon} {tc_code} — Playwright Report: {status.upper()}"
    await send_test_plan_email(recipients=recipients, subject=subject, html_body=html)
    logger.info(f"Execution report email sent to {recipients} for test run {report.get('test_run', {}).get('id')}")


# ============================================================
# JIRA — CREATE BUG FROM DEFECT
# ============================================================

async def create_jira_issue_from_defect(
    db: AsyncSession,
    defect_id: str,
    user_id: str,
    project_key: str,
    priority: str = "High",
) -> Dict[str, Any]:
    """Create a Jira bug ticket from a defect record."""
    from app.services.jira_session_manager import JiraSessionManager

    result = await db.execute(select(Defect).where(Defect.id == defect_id))
    defect = result.scalar_one_or_none()
    if not defect:
        raise ValueError(f"Defect {defect_id} not found")

    if defect.jira_issue_key:
        return {"key": defect.jira_issue_key, "already_exists": True}

    mgr = JiraSessionManager(db)
    conn = await mgr.get_connection(user_id)
    client = await mgr.get_client(conn)

    repro = "\n".join(defect.reproduction_steps or [])
    description_paragraphs = [
        f"[TestForge AI — Playwright E2E Defect]",
        f"Test Case: {defect.title}",
        f"Severity: {defect.severity.value.upper()} | Status: {defect.status.value.upper()}",
        "",
        "Description:",
        defect.description or "No description",
        "",
        "Reproduction Steps:",
        repro or "See execution logs",
        "",
        "Detected Issues:",
        "; ".join(defect.detected_issues or []) or "N/A",
        "",
        f"Defect ID: {defect.id}",
    ]

    jira_result = await client.create_issue(
        project_key=project_key,
        summary=defect.title,
        description_paragraphs=description_paragraphs,
        issue_type="Bug",
        priority=priority,
        labels=["testforge-ai", "playwright-e2e", "auto-detected"],
    )

    defect.jira_issue_key = jira_result.get("key")
    defect.jira_project_key = project_key
    await db.commit()

    logger.info(f"[JIRA] Created bug {defect.jira_issue_key} for defect {defect_id}")
    return jira_result
