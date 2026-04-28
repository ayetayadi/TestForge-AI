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
    MAIL_PORT=587,
    MAIL_SERVER="smtp.gmail.com",
    MAIL_FROM_NAME=settings.MAIL_FROM_NAME,
    MAIL_STARTTLS=True,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True,
)

async def send_account_setup_email(email: str, username: str, setup_token: str):
    setup_url = f"{settings.FRONTEND_URL}/authentication/setup-password?token={setup_token}"

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #1a1a2e; padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
            <h1 style="color: #4a9eff; margin: 0; font-size: 28px;">TESTFORGE</h1>
            <p style="color: #aaa; margin: 8px 0 0 0; font-size: 13px;">
                Intelligent Test Automation
            </p>
        </div>

        <div style="background: #ffffff; padding: 40px; border-radius: 0 0 8px 8px;
                    border: 1px solid #e0e0e0;">
            <h2 style="color: #333; margin-top: 0;">Welcome, {username}! 👋</h2>
            <p style="color: #555; line-height: 1.6;">
                Your TestForge account has been created by an administrator.
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
                © 2026 TestForge — Intelligent Test Automation
            </p>
        </div>
    </div>
    """

    message = MessageSchema(
        subject="Set up your TestForge account",
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
            <h1 style="color: #4a9eff; margin: 0; font-size: 28px;">TESTFORGE</h1>
            <p style="color: #aaa; margin: 8px 0 0 0; font-size: 13px;">
                Intelligent Test Automation
            </p>
        </div>

        <div style="background: #ffffff; padding: 40px; border-radius: 0 0 8px 8px;
                    border: 1px solid #e0e0e0;">
            <h2 style="color: #333; margin-top: 0;">Password reset request</h2>
            <p style="color: #555; line-height: 1.6;">
                Hi <strong>{username}</strong>, we received a request to reset
                your TestForge password. Click the button below to choose a new one.
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
                © 2026 TestForge — Intelligent Test Automation
            </p>
        </div>
    </div>
    """

    message = MessageSchema(
        subject="Reset your TestForge password",
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
            <h1 style="color: #4a9eff; margin: 0; font-size: 28px;">TESTFORGE</h1>
            <p style="color: #aaa; margin: 8px 0 0 0; font-size: 13px;">
                Intelligent Test Automation
            </p>
        </div>

        <div style="background: #ffffff; padding: 40px; border-radius: 0 0 8px 8px;
                    border: 1px solid #e0e0e0;">
            <h2 style="color: #333; margin-top: 0;">Password changed successfully</h2>

            <p style="color: #555; line-height: 1.6;">
                Hi <strong>{username}</strong>, this is a confirmation that your
                TestForge password was changed successfully.
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
                    Security notice: for your protection, TestForge never sends your password by email.
                </p>
            </div>

            <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;" />
            <p style="color: #aaa; font-size: 12px; text-align: center; margin: 0;">
                © 2026 TestForge — Intelligent Test Automation
            </p>
        </div>
    </div>
    """

    message = MessageSchema(
        subject="Your TestForge password has been changed",
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
        # Connexion au serveur SMTP
        server = smtplib.SMTP("smtp.gmail.com", 587)
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