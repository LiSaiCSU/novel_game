"""Small SMTP adapter. Dev mode logs delivery links instead of leaking tokens."""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from apps.jobs import enqueue_job
from engine.core.config import Settings
from engine.core.logging import get_logger

logger = get_logger("email")


async def send_email(settings: Settings, to: str, subject: str, text: str) -> None:
    queued = await enqueue_job(
        settings,
        "send_email",
        {"to": to, "subject": subject, "text": text},
    )
    if queued:
        return
    await deliver_email(settings, to, subject, text)


async def deliver_email(settings: Settings, to: str, subject: str, text: str) -> None:
    if not settings.smtp_host:
        # Tokens may be present in the body. Never write them to application logs.
        logger.info("email delivery disabled: to=%s subject=%s", to, subject)
        return
    await asyncio.to_thread(_send_sync, settings, to, subject, text)


def _send_sync(settings: Settings, to: str, subject: str, text: str) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    smtp_class = smtplib.SMTP_SSL if settings.smtp_ssl else smtplib.SMTP
    with smtp_class(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_starttls and not settings.smtp_ssl:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
