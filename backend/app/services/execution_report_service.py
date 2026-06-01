"""
Execution Report Service
Builds full execution reports from TestCaseResult, sends emails, creates Jira issues.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, desc as sql_desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import Defect
from app.models.enums import DefectSeverity, DefectStatus
from app.repositories import playwright_repository as repo

logger = logging.getLogger(__name__)


# ============================================================
# REPORT BUILDER — depuis un TestCaseResult
# ============================================================

async def build_full_report(db: AsyncSession, tc_result_id: str) -> Dict[str, Any]:
    """
    Build a comprehensive execution report from a TestCaseResult ID.
    Includes: execution config, status, all steps, test case info, defect.
    """
    tc_result = await repo.get_tc_result(db, tc_result_id)
    if not tc_result:
        return {"error": f"TestCaseResult {tc_result_id} not found"}

    execution = await repo.get_test_execution(db, tc_result.execution_id)
    test_case = await repo.get_test_case(db, tc_result.test_case_id)

    script_version = None
    if tc_result.script_version_id:
        script_version = await repo.get_script_version(db, tc_result.script_version_id)

    # Steps are stored as JSON: [{order, type, tool_name, content, status, duration, error}]
    steps: List[Dict[str, Any]] = tc_result.steps or []

    think_steps  = [s for s in steps if (s.get("type") or "").lower() == "think"]
    act_steps    = [s for s in steps if (s.get("type") or "").lower() in ("act", "observe")]
    failed_steps = [s for s in steps if (s.get("status") or "").lower() == "failed"]

    # LLM reasoning from think steps
    llm_reasoning_parts: List[str] = []
    for s in think_steps:
        content = (s.get("content") or "").strip()
        if content and len(content) > 10:
            llm_reasoning_parts.append(content)
    llm_reasoning = "\n\n---\n\n".join(llm_reasoning_parts)

    # Test case data
    test_case_data = None
    if test_case:
        test_case_data = {
            "id":               test_case.id,
            "tc_code":          test_case.tc_code,
            "title":            test_case.title,
            "description":      getattr(test_case, "description", None),
            "risk_level":       test_case.risk_level,
            "test_type":        getattr(test_case, "test_type", None),
            "steps":            getattr(test_case, "steps", None) or [],
            "expected_results": getattr(test_case, "expected_results", None) or [],
            "user_story_id":    test_case.user_story_id,
        }

    # Defect
    defect_data = None
    if test_case_data:
        defect = await _get_defect_for_tc_result(db, tc_result_id, test_case_data["id"])
        if defect:
            defect_data = _serialize_defect(defect)

    # Error summary
    error_summary = None
    if tc_result.status.value != "passed":
        error_lines: List[str] = []
        if tc_result.error_message:
            error_lines.append(tc_result.error_message)
        for s in failed_steps[:3]:
            content = s.get("content") or s.get("action") or ""
            if content:
                error_lines.append(content[:500])
        error_summary = "\n".join(error_lines) if error_lines else "Unknown error"

    # Execution info
    execution_info = None
    if execution:
        execution_info = {
            "id":         execution.id,
            "suite_id":   execution.suite_id,
            "app_url":    execution.app_url,
            "browser":    execution.browser,
            "headless":   execution.headless,
            "started_at": execution.started_at.isoformat() if execution.started_at else None,
        }

    return {
        "tc_result": {
            "id":             tc_result.id,
            "execution_id":   tc_result.execution_id,
            "status":         tc_result.status.value,
            "duration":       tc_result.duration,
            "screenshot_b64": tc_result.screenshot_b64,
            "justification":  tc_result.justification,
            "error_message":  tc_result.error_message,
            "started_at":     tc_result.started_at.isoformat() if tc_result.started_at else None,
            "completed_at":   tc_result.completed_at.isoformat() if tc_result.completed_at else None,
            "steps_passed":   tc_result.steps_passed,
            "steps_failed":   tc_result.steps_failed,
        },
        "execution":      execution_info,
        "test_case":      test_case_data,
        "script_version": {
            "id":                script_version.id,
            "version_number":    script_version.version_number,
            "source":            script_version.source.value,
            "placeholder_count": script_version.placeholder_count,
        } if script_version else None,
        "steps":          steps,
        "llm_reasoning":  llm_reasoning,
        "error_summary":  error_summary,
        "defect":         defect_data,
        "stats": {
            "total_steps":  len(steps),
            "think_steps":  len(think_steps),
            "act_steps":    len(act_steps),
            "failed_steps": len(failed_steps),
            "success_rate": round(
                ((len(steps) - len(failed_steps)) / len(steps) * 100) if steps else 0, 1
            ),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def _get_defect_for_tc_result(
    db: AsyncSession, tc_result_id: str, test_case_id: str
) -> Optional[Defect]:
    """Find the most recent defect linked to this test case."""
    result = await db.execute(
        select(Defect)
        .where(Defect.test_case_id == test_case_id)
        .where(Defect.logs.contains(tc_result_id))
        .order_by(sql_desc(Defect.created_at))
        .limit(1)
    )
    defect = result.scalar_one_or_none()
    if not defect:
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
        "id":                  defect.id,
        "title":               defect.title,
        "description":         defect.description,
        "severity":            defect.severity.value,
        "status":              defect.status.value,
        "reproduction_steps":  defect.reproduction_steps or [],
        "jira_issue_key":      defect.jira_issue_key,
        "jira_project_key":    defect.jira_project_key,
        "created_at":          defect.created_at.isoformat() if defect.created_at else None,
    }


# ============================================================
# AUTO-DEFECT CREATION FROM TC RESULT
# ============================================================

async def create_defect_from_execution(
    db: AsyncSession,
    tc_result_id: str,
    test_case_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Create a Defect record from a failed TestCaseResult.
    Returns None if test case has no user_story_id (required FK).
    """
    test_case = await repo.get_test_case(db, test_case_id)
    if not test_case:
        logger.warning(f"[DEFECT] Test case {test_case_id} not found, skipping defect creation")
        return None

    if not test_case.user_story_id:
        logger.warning(
            f"[DEFECT] Test case {test_case_id} has no user_story_id — defect creation skipped."
        )
        return None

    tc_result = await repo.get_tc_result(db, tc_result_id)
    if not tc_result:
        return None

    execution = await repo.get_test_execution(db, tc_result.execution_id)

    steps: List[Dict[str, Any]] = tc_result.steps or []
    think_steps  = [s for s in steps if (s.get("type") or "").lower() == "think"]
    act_steps    = [s for s in steps if (s.get("type") or "").lower() == "act"]
    failed_steps = [s for s in steps if (s.get("status") or "").lower() == "failed"]

    # Reproduction steps from act steps
    reproduction_steps: List[str] = []
    for i, s in enumerate(act_steps[:15]):
        tool = f"[{s.get('tool_name')}] " if s.get("tool_name") else ""
        content = (s.get("content") or s.get("action") or "")[:200]
        reproduction_steps.append(f"{i + 1}. {tool}{content}")

    # LLM reasoning
    llm_reasoning = "\n".join([(s.get("content") or "")[:800] for s in think_steps[:5]])

    # Error message
    error_msg = tc_result.error_message
    if not error_msg and failed_steps:
        error_msg = (failed_steps[0].get("content") or failed_steps[0].get("action") or "")[:500]

    # Screenshot
    screenshot = tc_result.screenshot_b64
    if not screenshot:
        for fs in failed_steps:
            if fs.get("screenshot_b64"):
                screenshot = fs["screenshot_b64"]
                break

    # Severity from risk level
    status_val = tc_result.status.value
    if status_val == "error":
        severity = DefectSeverity.HIGH
    else:
        risk = (test_case.risk_level or "medium").lower()
        severity = {
            "critical": DefectSeverity.CRITICAL,
            "high":     DefectSeverity.HIGH,
            "medium":   DefectSeverity.MEDIUM,
            "low":      DefectSeverity.LOW,
        }.get(risk, DefectSeverity.HIGH)

    title = f"[PLAYWRIGHT] {test_case.tc_code} — {test_case.title[:120]}"
    description = (
        f"Playwright E2E test failed for {test_case.tc_code}.\n\n"
        f"Browser: {execution.browser if execution else 'unknown'}\n"
        f"URL: {execution.app_url if execution else 'unknown'}\n"
        f"Duration: {(tc_result.duration or 0):.1f}s\n\n"
        f"Error:\n{error_msg or 'No error message captured'}\n\n"
        f"LLM Reasoning:\n{llm_reasoning[:1500] if llm_reasoning else 'No reasoning captured'}"
    )

    logs_text = (
        f"TestCaseResult ID: {tc_result_id}\n"
        f"Execution ID: {tc_result.execution_id}\n"
        f"Steps: {len(steps)} total, {len(failed_steps)} failed\n\n"
        + "\n".join([
            f"[{(s.get('type') or '?').upper()}] {(s.get('status') or '?')} | "
            f"{s.get('tool_name') or '-'} | {(s.get('content') or s.get('action') or '')[:200]}"
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
        correction_priority=test_case.risk_level or "medium",
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

    tc        = report.get("test_case") or {}
    tc_result = report.get("tc_result") or {}
    execution = report.get("execution") or {}
    stats     = report.get("stats") or {}
    defect    = report.get("defect")
    steps     = report.get("steps") or []

    status = tc_result.get("status") or "unknown"
    status_color = {
        "passed":  "#16a34a",
        "failed":  "#dc2626",
        "error":   "#ea580c",
        "skipped": "#6b7280",
    }.get(status, "#6b7280")
    status_icon = {"passed": "✅", "failed": "❌", "error": "⚠️"}.get(status, "ℹ️")

    duration_s = round((tc_result.get("duration") or 0), 1)

    # Build steps HTML (failed first, then last 5 act/observe)
    relevant_steps = [s for s in steps if (s.get("status") or "").lower() == "failed"][:5]
    if not relevant_steps:
        relevant_steps = [
            s for s in steps
            if (s.get("type") or "").lower() in ("act", "observe")
        ][-5:]

    steps_html = ""
    for s in relevant_steps:
        s_status = (s.get("status") or "").lower()
        icon = "❌" if s_status == "failed" else "✅"
        tool = (
            f'<code style="background:#f3f4f6;padding:1px 4px;border-radius:3px;font-size:11px;">'
            f'{s.get("tool_name","")}</code> ' if s.get("tool_name") else ""
        )
        content = (s.get("content") or s.get("action") or "")[:200]
        steps_html += f"""
        <tr>
            <td style="padding:8px 12px;color:#6b7280;font-size:12px;">{s.get("order","")}</td>
            <td style="padding:8px 12px;font-size:12px;">{tool}{content}</td>
            <td style="padding:8px 12px;text-align:center;font-size:13px;">{icon}</td>
        </tr>"""

    # LLM reasoning
    reasoning = report.get("llm_reasoning") or ""
    reasoning_html = ""
    if reasoning:
        paragraphs = [p.strip() for p in reasoning.split("\n---\n") if p.strip()]
        for p in paragraphs[:3]:
            reasoning_html += (
                f'<p style="color:#374151;font-size:13px;line-height:1.6;margin:0 0 10px 0;">'
                f'{p[:600]}</p>'
            )

    # Defect section
    defect_html = ""
    if defect:
        sev_color = {
            "critical": "#dc2626", "high": "#ea580c",
            "medium":   "#d97706", "low":  "#16a34a",
        }.get(defect.get("severity", "high"), "#6b7280")
        jira_html = (
            f'&nbsp;|&nbsp; Jira: <strong>{defect.get("jira_issue_key")}</strong>'
            if defect.get("jira_issue_key") else ""
        )
        defect_html = f"""
        <div style="margin:24px 0;padding:16px;background:#fef2f2;border-left:4px solid #dc2626;border-radius:6px;">
            <h3 style="margin:0 0 8px 0;color:#dc2626;font-size:14px;">🐛 Defect Created</h3>
            <p style="margin:0 0 6px 0;font-size:13px;"><strong>{defect.get("title","")}</strong></p>
            <p style="margin:0;font-size:12px;color:#6b7280;">
                Severity: <span style="color:{sev_color};font-weight:600;">{(defect.get("severity") or "").upper()}</span>
                &nbsp;|&nbsp; Status: {defect.get("status","open").upper()}{jira_html}
            </p>
        </div>"""

    # Error summary
    error_html = ""
    err = report.get("error_summary") or tc_result.get("error_message") or ""
    if err and status != "passed":
        error_html = f"""
        <div style="margin:16px 0;padding:14px;background:#fef2f2;border-radius:6px;border:1px solid #fecaca;">
            <h4 style="margin:0 0 8px 0;color:#dc2626;font-size:13px;">Error Details</h4>
            <pre style="margin:0;font-size:12px;color:#374151;white-space:pre-wrap;font-family:monospace;">{err[:800]}</pre>
        </div>"""

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:750px;margin:0 auto;background:#f9fafb;">

        <div style="background:{status_color};padding:24px 32px;border-radius:8px 8px 0 0;text-align:center;">
            <h1 style="color:white;margin:0;font-size:24px;">
                {status_icon} Execution Report — {status.upper()}
            </h1>
            <p style="color:rgba(255,255,255,0.85);margin:6px 0 0 0;font-size:13px;">
                TestForge AI · Playwright E2E Testing
            </p>
        </div>

        <div style="background:white;padding:32px;border-radius:0 0 8px 8px;border:1px solid #e5e7eb;">

            <div style="margin-bottom:24px;padding:16px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;">
                <h2 style="margin:0 0 10px 0;color:#1e293b;font-size:16px;">
                    {tc.get("tc_code","N/A")} — {tc.get("title","Unknown Test Case")}
                </h2>
                <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:#64748b;">
                    <span>Type: <strong>{(tc.get("test_type") or "N/A").upper()}</strong></span>
                    <span>Risk: <strong>{(tc.get("risk_level") or "N/A").upper()}</strong></span>
                    <span>Browser: <strong>{execution.get("browser","N/A")}</strong></span>
                    <span>URL: <strong>{execution.get("app_url","N/A")}</strong></span>
                    <span>Duration: <strong>{duration_s}s</strong></span>
                </div>
            </div>

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

            {f'''
            <div style="margin-bottom:24px;">
                <h3 style="color:#1e293b;font-size:14px;margin:0 0 12px 0;">🧠 AI Reasoning</h3>
                <div style="background:#fafafa;padding:16px;border-radius:6px;border:1px solid #e5e7eb;">
                    {reasoning_html}
                </div>
            </div>
            ''' if reasoning_html else ''}

            {f'''
            <div style="margin-bottom:24px;">
                <h3 style="color:#1e293b;font-size:14px;margin:0 0 12px 0;">🔍 Execution Steps</h3>
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

            {f'''
            <div style="margin-bottom:24px;padding:14px;background:#f0f9ff;border-left:4px solid #0284c7;border-radius:6px;">
                <h4 style="margin:0 0 6px 0;color:#0284c7;font-size:13px;">Result Justification</h4>
                <p style="margin:0;color:#374151;font-size:13px;">{tc_result.get("justification","")}</p>
            </div>
            ''' if tc_result.get("justification") else ''}

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
    logger.info(
        f"Execution report email sent to {recipients} for tc_result "
        f"{tc_result.get('id')}"
    )


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
        "[TestForge AI — Playwright E2E Defect]",
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
