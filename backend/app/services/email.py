import asyncio
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("uvicorn.error")


def _app_url() -> str:
    return os.getenv("APP_URL", "http://localhost:5173").strip().rstrip("/")


def smtp_configured() -> bool:
    return bool(os.getenv("SMTP_HOST", "").strip())


def _build_verification_link(token: str) -> str:
    return f"{_app_url()}/auth/verify?token={token}"


def _send_sync(to_email: str, subject: str, html: str, text: str) -> None:
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    from_addr = os.getenv("SMTP_FROM", user).strip() or user

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(host, port, timeout=30) as server:
        if os.getenv("SMTP_USE_TLS", "1").strip() not in ("0", "false", "False"):
            server.starttls()
        if user and password:
            server.login(user, password)
        server.sendmail(from_addr, [to_email], msg.as_string())


async def send_verification_email(to_email: str, token: str, *, name: str = "") -> None:
    link = _build_verification_link(token)
    greeting = f"Hi {name}," if name else "Hi,"
    subject = "Activate your Resume Tailor account"
    text = (
        f"{greeting}\n\n"
        f"Click the link below to verify your email and activate your account:\n\n"
        f"{link}\n\n"
        f"This link expires in 24 hours.\n\n"
        f"If you did not create an account, you can ignore this email."
    )
    html = f"""
    <p>{greeting}</p>
    <p>Click the button below to verify your email and activate your account:</p>
    <p><a href="{link}" style="display:inline-block;padding:12px 24px;background:#12b886;color:#fff;text-decoration:none;border-radius:8px;font-weight:600;">Activate account</a></p>
    <p>Or copy this link into your browser:<br><a href="{link}">{link}</a></p>
    <p style="color:#666;font-size:13px;">This link expires in 24 hours. If you did not create an account, ignore this email.</p>
    """

    if not smtp_configured():
        logger.warning(
            "SMTP not configured in backend/.env — no email sent to %s. "
            "Activation link (dev fallback): %s",
            to_email,
            link,
        )
        return

    try:
        await asyncio.to_thread(_send_sync, to_email, subject, html, text)
        logger.info("Verification email sent to %s", to_email)
    except Exception as exc:
        logger.error(
            "Failed to send verification email to %s (%s). Dev fallback link: %s",
            to_email,
            exc,
            link,
        )
        raise RuntimeError(
            "Could not send activation email. Check SMTP settings in backend/.env."
        ) from exc
