"""Outbound email (invites, password resets). Disabled when SMTP_HOST is unset."""

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from blackmamba.core.config import Settings, get_settings

log = logging.getLogger(__name__)


def email_enabled(settings: Settings | None = None) -> bool:
    return bool((settings or get_settings()).smtp_host)


def _send_sync(settings: Settings, to: str, subject: str, body: str) -> None:
    if not settings.smtp_host:
        raise RuntimeError("SMTP is not configured")
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        smtp.send_message(msg)


async def send_email(to: str, subject: str, body: str) -> bool:
    """Best effort. Returns True if handed to the SMTP server."""
    settings = get_settings()
    if not email_enabled(settings):
        return False
    try:
        await asyncio.to_thread(_send_sync, settings, to, subject, body)
    except (OSError, smtplib.SMTPException):
        log.exception("failed to send email (subject=%r)", subject)
        return False
    return True
