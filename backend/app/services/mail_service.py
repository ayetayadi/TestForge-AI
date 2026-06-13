from email import encoders
from email.mime.base import MIMEBase
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional
import asyncio
from concurrent.futures import ThreadPoolExecutor
import aiosmtplib
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from app.core.config import settings

conf = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME,
    MAIL_PASSWORD=settings.MAIL_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_FROM_NAME=settings.MAIL_FROM_NAME,
    MAIL_STARTTLS=settings.MAIL_STARTTLS,
    MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
    USE_CREDENTIALS=True,
)

async def send_account_setup_email(email: str, username: str, setup_token: str):
    setup_url = f"{settings.FRONTEND_URL}/authentication/setup-password?token={setup_token}"

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #1a1a2e; padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
            <h1 style="color: #4a9eff; margin: 0; font-size: 28px;">TestForge AI AI AI</h1>
            <p style="color: #aaa; margin: 8px 0 0 0; font-size: 13px;">
                Intelligent Test Automation
            </p>
        </div>

        <div style="background: #ffffff; padding: 40px; border-radius: 0 0 8px 8px;
                    border: 1px solid #e0e0e0;">
            <h2 style="color: #333; margin-top: 0;">Welcome, {username}! 👋</h2>
            <p style="color: #555; line-height: 1.6;">
                Your TestForge AI AI AI account has been created by an administrator.
                Click the button below to set up your password and activate your account.
            </p>

            <div style="text-align: center; margin: 32px 0;">
                <a href="{setup_url}"
                   style="background: #4a9eff; color: white; padding: 14px 32px;
                          border-radius: 6px; text-decoration: none; font-weight: bold;
                          font-size: 16px; display: inline-block;">
                    Set Up My Password
                </a>
            </div>

            <p style="color: #888; font-size: 13px; text-align: center;">
                This link expires in <strong>24 hours</strong>.<br/>
                If you did not expect this email, please ignore it.
            </p>

            <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;" />
            <p style="color: #aaa; font-size: 12px; text-align: center; margin: 0;">
                © 2026 TestForge AI AI AI — Intelligent Test Automation
            </p>
        </div>
    </div>
    """

    message = MessageSchema(
        subject="Set up your TestForge AI AI AI account",
        recipients=[email],
        body=html,
        subtype=MessageType.html,
    )

    fm = FastMail(conf)
    await fm.send_message(message)

async def send_reset_email(email: str, username: str, reset_token: str):
    reset_url = f"{settings.FRONTEND_URL}/authentication/reset-password?token={reset_token}"

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #1a1a2e; padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
            <h1 style="color: #4a9eff; margin: 0; font-size: 28px;">TestForge AI AI AI</h1>
            <p style="color: #aaa; margin: 8px 0 0 0; font-size: 13px;">
                Intelligent Test Automation
            </p>
        </div>

        <div style="background: #ffffff; padding: 40px; border-radius: 0 0 8px 8px;
                    border: 1px solid #e0e0e0;">
            <h2 style="color: #333; margin-top: 0;">Password reset request</h2>
            <p style="color: #555; line-height: 1.6;">
                Hi <strong>{username}</strong>, we received a request to reset
                your TestForge AI AI AI password. Click the button below to choose a new one.
            </p>

            <div style="text-align: center; margin: 32px 0;">
                <a href="{reset_url}"
                   style="background: #4a9eff; color: white; padding: 14px 32px;
                          border-radius: 6px; text-decoration: none; font-weight: bold;
                          font-size: 16px; display: inline-block;">
                    Reset My Password
                </a>
            </div>

            <p style="color: #888; font-size: 13px; text-align: center;">
                This link expires in <strong>30 minutes</strong>.<br/>
                If you did not request a password reset, you can safely ignore this email.
            </p>

            <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;" />
            <p style="color: #aaa; font-size: 12px; text-align: center; margin: 0;">
                © 2026 TestForge AI AI AI — Intelligent Test Automation
            </p>
        </div>
    </div>
    """

    message = MessageSchema(
        subject="Reset your TestForge AI AI AI password",
        recipients=[email],
        body=html,
        subtype=MessageType.html,
    )

    fm = FastMail(conf)
    await fm.send_message(message)

async def send_password_changed_email(email: str, username: str):
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #1a1a2e; padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
            <h1 style="color: #4a9eff; margin: 0; font-size: 28px;">TestForge AI AI AI</h1>
            <p style="color: #aaa; margin: 8px 0 0 0; font-size: 13px;">
                Intelligent Test Automation
            </p>
        </div>

        <div style="background: #ffffff; padding: 40px; border-radius: 0 0 8px 8px;
                    border: 1px solid #e0e0e0;">
            <h2 style="color: #333; margin-top: 0;">Password changed successfully</h2>

            <p style="color: #555; line-height: 1.6;">
                Hi <strong>{username}</strong>, this is a confirmation that your
                TestForge AI AI AI password was changed successfully.
            </p>

            <p style="color: #555; line-height: 1.6;">
                If you made this change, no further action is needed.
            </p>

            <p style="color: #555; line-height: 1.6;">
                If you did <strong>not</strong> make this change, please reset your password
                immediately or contact support as soon as possible.
            </p>

            <div style="margin-top: 28px; padding: 16px; background: #f8f9fb; border-left: 4px solid #4a9eff; border-radius: 6px;">
                <p style="margin: 0; color: #555; font-size: 14px;">
                    Security notice: for your protection, TestForge AI AI AI never sends your password by email.
                </p>
            </div>

            <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;" />
            <p style="color: #aaa; font-size: 12px; text-align: center; margin: 0;">
                © 2026 TestForge AI AI AI — Intelligent Test Automation
            </p>
        </div>
    </div>
    """

    message = MessageSchema(
        subject="Your TestForge AI AI AI password has been changed",
        recipients=[email],
        body=html,
        subtype=MessageType.html,
    )

    fm = FastMail(conf)
    await fm.send_message(message)


async def send_test_plan_email(
    recipients: List[str],
    subject: str,
    html_body: str,
) -> None:
    """Send a test plan report email to a list of recipients."""
    message = MessageSchema(
        subject=subject,
        recipients=recipients,
        body=html_body,
        subtype=MessageType.html,
    )
    fm = FastMail(conf)
    await fm.send_message(message)

def _send_email_with_pdf_sync(msg: MIMEMultipart) -> None:
    """
    Fonction synchrone pour envoyer l'email avec pièce jointe.
    Utilise smtplib standard qui gère correctement STARTTLS.
    """
    try:
        server = smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT)
        server.ehlo()  # Saluer le serveur
        server.starttls()  # Démarrer TLS
        server.ehlo()  # Saluer à nouveau après TLS
        server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
        
        # Envoyer le message
        server.send_message(msg)
        server.quit()
        
        print("✅ Email sent successfully")
        
    except Exception as e:
        print(f"❌ Sync send error: {str(e)}")
        raise


async def send_test_plan_email_with_attachment(
    recipients: List[str],
    subject: str,
    html_body: str,
    attachments: Optional[List[Dict[str, any]]] = None,
) -> None:
    """
    Send a test plan email with PDF attachment.
    Uses smtplib in a thread pool for reliable async sending.
    """
    try:
        # Créer le message multipart
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = f"{settings.MAIL_FROM_NAME} <{settings.MAIL_FROM}>"
        msg["To"] = ", ".join(recipients)
        
        # Corps HTML
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        
        # Pièces jointes PDF
        if attachments:
            for attachment in attachments:
                part = MIMEBase("application", "pdf")
                part.set_payload(attachment["content"])
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f'attachment; filename="{attachment["filename"]}"'
                )
                msg.attach(part)
        
        # Envoyer de manière asynchrone avec ThreadPoolExecutor
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            await loop.run_in_executor(pool, _send_email_with_pdf_sync, msg)
        
        print(f"✅ Email with PDF attachment sent to {len(recipients)} recipients")
        
    except Exception as e:
        error_msg = f"Email sending failed: {str(e)}"
        print(f"❌ {error_msg}")
        raise ValueError(error_msg)
    

# ═══════════════════════════════════════════════════════
# RISK ANALYSIS EMAILS
# ═══════════════════════════════════════════════════════

async def send_risk_analysis_email(
    recipients: List[str],
    project_name: str,
    sprint: str,
    risks_summary: dict,
    risk_details: List[dict],
    risk_url: str,
) -> None:
    """
    Send risk analysis results to the team (Shift-Left).
    Called after LLM analysis is complete.
    """
    
    # Construire les sections par niveau
    critical_risks = [r for r in risk_details if r["level"] == "critical"]
    high_risks = [r for r in risk_details if r["level"] == "high"]
    medium_risks = [r for r in risk_details if r["level"] == "medium"]
    low_risks = [r for r in risk_details if r["level"] == "low"]
    
    # Générer les lignes HTML pour chaque risque
    def render_risk(r):
        return f"""
        <tr style="border-bottom: 1px solid #eee;">
            <td style="padding: 10px 12px; font-weight: 600;">{r.get('issue_key', '?')}</td>
            <td style="padding: 10px 12px;">{r.get('title', r.get('description', ''))}</td>
            <td style="padding: 10px 12px; text-align: center;">
                <strong>P{r.get('probability', '?')} × I{r.get('impact', '?')} = {r.get('risk_score', '?')}</strong>
            </td>
            <td style="padding: 10px 12px; font-size: 12px;">{r.get('mitigation', '')}</td>
        </tr>"""
    
    def render_section(icon, level, risks, effort, color):
        if not risks:
            return ""
        rows = "".join([render_risk(r) for r in risks])
        return f"""
        <div style="margin-bottom: 24px;">
            <h3 style="color: {color}; margin: 0 0 8px 0;">
                {icon} {level} ({len(risks)}) — {effort} of testing time
            </h3>
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <thead>
                    <tr style="background: #f8f9fb; text-align: left;">
                        <th style="padding: 8px 12px;">Story</th>
                        <th style="padding: 8px 12px;">Risk</th>
                        <th style="padding: 8px 12px; text-align: center;">Score</th>
                        <th style="padding: 8px 12px;">Mitigation</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </div>"""
    
    total = len(risk_details)
    
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto;">
        <div style="background: #1a1a2e; padding: 24px; text-align: center; border-radius: 8px 8px 0 0;">
            <h1 style="color: #4a9eff; margin: 0; font-size: 24px;">TestForge AI AI AI</h1>
            <p style="color: #aaa; margin: 4px 0 0 0; font-size: 13px;">Risk Analysis Report</p>
        </div>

        <div style="background: #ffffff; padding: 32px; border-radius: 0 0 8px 8px; border: 1px solid #e0e0e0;">
            
            <h2 style="color: #333; margin-top: 0;">🛡️ Risk Analysis — {sprint}</h2>
            <p style="color: #555; line-height: 1.6;">
                Project: <strong>{project_name}</strong><br>
                Total risks analyzed: <strong>{total}</strong><br>
                Average score: <strong>{risks_summary.get('avg_score', 'N/A')}</strong>
            </p>

            <div style="background: #f8f9fb; padding: 16px; border-radius: 6px; margin: 16px 0;">
                <table style="width: 100%; font-size: 13px;">
                    <tr>
                        <td>⛔ Critical: <strong>{risks_summary.get('by_level', {}).get('critical', 0)}</strong></td>
                        <td>⚠️ High: <strong>{risks_summary.get('by_level', {}).get('high', 0)}</strong></td>
                        <td>🔶 Medium: <strong>{risks_summary.get('by_level', {}).get('medium', 0)}</strong></td>
                        <td>✅ Low: <strong>{risks_summary.get('by_level', {}).get('low', 0)}</strong></td>
                    </tr>
                </table>
            </div>

            {render_section('⛔', 'CRITICAL', critical_risks, '60%', '#dc2626')}
            {render_section('⚠️', 'HIGH', high_risks, '25%', '#ea580c')}
            {render_section('🔶', 'MEDIUM', medium_risks, '10%', '#d97706')}
            {render_section('✅', 'LOW', low_risks, '5%', '#16a34a')}

            <div style="text-align: center; margin-top: 32px;">
                <a href="{risk_url}"
                   style="background: #4a9eff; color: white; padding: 12px 28px;
                          border-radius: 6px; text-decoration: none; font-weight: bold;
                          font-size: 14px; display: inline-block;">
                    View All Risks →
                </a>
            </div>

            <div style="margin-top: 24px; padding: 16px; background: #f0fdf4; border-left: 4px solid #16a34a; border-radius: 6px;">
                <p style="margin: 0; color: #555; font-size: 13px;">
                    <strong>💡 Tip:</strong> Read the mitigation column before coding. 
                    Risk Score = Probability × Impact (1-25 scale).
                    Critical = 20-25 | High = 12-19 | Medium = 6-11 | Low = 1-5
                </p>
            </div>

            <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0 16px 0;" />
            <p style="color: #aaa; font-size: 11px; text-align: center; margin: 0;">
                © 2026 TestForge AI AI AI — Risk Based Testing (ISTQB)
            </p>
        </div>
    </div>
    """

    message = MessageSchema(
        subject=f"🛡️ Risk Analysis - {sprint} - {project_name}",
        recipients=recipients,
        body=html,
        subtype=MessageType.html,
    )

    fm = FastMail(conf)
    await fm.send_message(message)


async def send_risk_alert_email(
    recipients: List[str],
    risk: dict,
    incident_description: str,
    risk_url: str,
) -> None:
    """
    Send alert when a risk is updated after a production incident (Shift-Right).
    """
    
    previous_score = risk.get('previous_risk_score', '?')
    previous_level = risk.get('previous_level', '?')
    new_score = risk.get('risk_score', '?')
    new_level = risk.get('level', '?')
    
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #dc2626; padding: 24px; text-align: center; border-radius: 8px 8px 0 0;">
            <h1 style="color: #fff; margin: 0; font-size: 22px;">🚨 RISK ALERT</h1>
            <p style="color: #fecaca; margin: 4px 0 0 0; font-size: 13px;">
                Production incident feedback
            </p>
        </div>

        <div style="background: #ffffff; padding: 32px; border-radius: 0 0 8px 8px; border: 1px solid #e0e0e0;">
            
            <h2 style="color: #dc2626; margin-top: 0;">Risk Updated: {risk.get('issue_key', '?')}</h2>
            <p style="color: #555; line-height: 1.6; font-size: 14px;">
                <strong>{risk.get('description', '')}</strong>
            </p>

            <div style="background: #fef2f2; padding: 20px; border-radius: 8px; margin: 20px 0; border: 1px solid #fecaca;">
                <h3 style="margin: 0 0 12px 0; color: #dc2626;">📈 Risk Change</h3>
                <table style="width: 100%; font-size: 14px;">
                    <tr>
                        <td style="padding: 6px;">Previous:</td>
                        <td style="padding: 6px; font-weight: 600;">P{risk.get('previous_probability', '?')} × I{risk.get('previous_impact', '?')} = {previous_score} ({previous_level.upper()})</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px;">New:</td>
                        <td style="padding: 6px; font-weight: 700; color: #dc2626;">P{risk.get('probability', '?')} × I{risk.get('impact', '?')} = {new_score} ({new_level.upper()})</td>
                    </tr>
                </table>
            </div>

            <div style="background: #f8f9fb; padding: 16px; border-radius: 6px; margin: 16px 0;">
                <h4 style="margin: 0 0 8px 0; color: #333;">📋 Incident Description</h4>
                <p style="color: #555; margin: 0; font-size: 13px;">{incident_description}</p>
            </div>

            <div style="background: #fff7ed; padding: 16px; border-radius: 6px; border-left: 4px solid #ea580c;">
                <h4 style="margin: 0 0 4px 0; color: #333;">🛡️ Updated Mitigation</h4>
                <p style="color: #555; margin: 0; font-size: 13px;"><strong>{risk.get('mitigation', 'No mitigation specified')}</strong></p>
            </div>

            <div style="text-align: center; margin-top: 28px;">
                <a href="{risk_url}"
                   style="background: #dc2626; color: white; padding: 12px 28px;
                          border-radius: 6px; text-decoration: none; font-weight: bold;
                          font-size: 14px; display: inline-block;">
                    View Risk Details →
                </a>
            </div>

            <p style="color: #888; font-size: 12px; text-align: center; margin-top: 20px;">
                ⚠️ Action required before next deployment
            </p>

            <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0 12px 0;" />
            <p style="color: #aaa; font-size: 11px; text-align: center; margin: 0;">
                © 2026 TestForge AI AI AI — Risk Based Testing (ISTQB)
            </p>
        </div>
    </div>
    """

    message = MessageSchema(
        subject=f"🚨 Risk Updated - {risk.get('issue_key', '?')} ({new_level.upper()} {new_score})",
        recipients=recipients,
        body=html,
        subtype=MessageType.html,
    )

    fm = FastMail(conf)
    await fm.send_message(message)