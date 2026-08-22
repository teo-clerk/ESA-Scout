"""Notification dispatch: email (Resend or SMTP), Telegram and Discord.

Only *notifiable* events reach this module — a status change, or a newly listed
open opportunity scoring at or above the configured threshold. Filtering lives
in `should_notify` so the rule is testable in isolation.

Every channel is independent: one failing transport is reported and the others
still deliver.
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Sequence

import httpx

from . import render
from .config import NotifierSettings
from .models import ChangeEvent

LOGGER = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
TELEGRAM_API_URL = "https://api.telegram.org"
_REQUEST_TIMEOUT = 30.0


@dataclass(frozen=True)
class NotificationResult:
    """Outcome of one channel's delivery attempt."""

    channel: str
    sent: bool
    detail: str = ""

    @classmethod
    def skipped(cls, channel: str, reason: str) -> "NotificationResult":
        return cls(channel=channel, sent=False, detail=f"skipped: {reason}")

    @classmethod
    def failed(cls, channel: str, reason: str) -> "NotificationResult":
        return cls(channel=channel, sent=False, detail=f"failed: {reason}")

    @classmethod
    def ok(cls, channel: str, detail: str = "sent") -> "NotificationResult":
        return cls(channel=channel, sent=True, detail=detail)


def should_notify(events: Sequence[ChangeEvent], first_run: bool) -> tuple[ChangeEvent, ...]:
    """Select the events that justify interrupting the user.

    Suppressed entirely on the first run: with no prior state every opportunity
    looks new, and a storm of alerts on setup would train the user to ignore
    them.
    """
    if first_run:
        return ()
    return tuple(event for event in events if event.is_notifiable)


# --- Channels --------------------------------------------------------------
def send_email(
    events: Sequence[ChangeEvent],
    settings: NotifierSettings,
    dashboard_url: str | None = None,
    client: httpx.Client | None = None,
) -> NotificationResult:
    """Send via Resend when an API key is present, otherwise SMTP."""
    if not settings.email_enabled:
        return NotificationResult.skipped(
            "email", "EMAIL_FROM/EMAIL_TO and a transport (Resend or SMTP) required"
        )

    subject = render.subject(events)
    html = render.html_body(events, dashboard_url)
    text = render.text_body(events, dashboard_url)

    if settings.resend_api_key:
        return _send_via_resend(settings, subject, html, text, client)
    return _send_via_smtp(settings, subject, html, text)


def _send_via_resend(
    settings: NotifierSettings,
    subject: str,
    html: str,
    text: str,
    client: httpx.Client | None,
) -> NotificationResult:
    payload = {
        "from": settings.email_from,
        "to": list(settings.email_to),
        "subject": subject,
        "html": html,
        "text": text,
    }
    owns_client = client is None
    client = client or httpx.Client(timeout=_REQUEST_TIMEOUT)
    try:
        response = client.post(
            RESEND_API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        )
        if response.status_code >= 400:
            return NotificationResult.failed(
                "email", f"Resend HTTP {response.status_code}: {response.text[:200]}"
            )
        return NotificationResult.ok("email", f"Resend -> {len(settings.email_to)} recipient(s)")
    except Exception as exc:
        return NotificationResult.failed("email", f"Resend request failed: {exc}")
    finally:
        if owns_client:
            client.close()


def _send_via_smtp(
    settings: NotifierSettings, subject: str, html: str, text: str
) -> NotificationResult:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.email_from or ""
    message["To"] = ", ".join(settings.email_to)
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(settings.smtp_host or "", settings.smtp_port, timeout=_REQUEST_TIMEOUT) as server:
            server.ehlo()
            if settings.smtp_starttls:
                server.starttls()
                server.ehlo()
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
        return NotificationResult.ok("email", f"SMTP -> {len(settings.email_to)} recipient(s)")
    except Exception as exc:
        return NotificationResult.failed("email", f"SMTP send failed: {exc}")


def send_telegram(
    events: Sequence[ChangeEvent],
    settings: NotifierSettings,
    dashboard_url: str | None = None,
    client: httpx.Client | None = None,
) -> NotificationResult:
    if not settings.telegram_enabled:
        return NotificationResult.skipped(
            "telegram", "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required"
        )

    url = f"{TELEGRAM_API_URL}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": render.telegram_body(events, dashboard_url),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    owns_client = client is None
    client = client or httpx.Client(timeout=_REQUEST_TIMEOUT)
    try:
        response = client.post(url, json=payload)
        if response.status_code >= 400:
            return NotificationResult.failed(
                "telegram", f"HTTP {response.status_code}: {response.text[:200]}"
            )
        return NotificationResult.ok("telegram")
    except Exception as exc:
        return NotificationResult.failed("telegram", f"request failed: {exc}")
    finally:
        if owns_client:
            client.close()


def send_discord(
    events: Sequence[ChangeEvent],
    settings: NotifierSettings,
    dashboard_url: str | None = None,
    client: httpx.Client | None = None,
) -> NotificationResult:
    if not settings.discord_enabled:
        return NotificationResult.skipped("discord", "DISCORD_WEBHOOK_URL required")

    payload = {"content": render.discord_body(events, dashboard_url)}
    owns_client = client is None
    client = client or httpx.Client(timeout=_REQUEST_TIMEOUT)
    try:
        response = client.post(settings.discord_webhook_url or "", json=payload)
        if response.status_code >= 400:
            return NotificationResult.failed(
                "discord", f"HTTP {response.status_code}: {response.text[:200]}"
            )
        return NotificationResult.ok("discord")
    except Exception as exc:
        return NotificationResult.failed("discord", f"request failed: {exc}")
    finally:
        if owns_client:
            client.close()


# --- Dispatch --------------------------------------------------------------
def dispatch(
    events: Sequence[ChangeEvent],
    settings: NotifierSettings,
    dashboard_url: str | None = None,
    client: httpx.Client | None = None,
) -> tuple[NotificationResult, ...]:
    """Deliver `events` on every configured channel.

    Returns one result per channel, including skipped ones, so the CLI can show
    exactly what happened.
    """
    if not events:
        LOGGER.info("no notifiable events — nothing to send")
        return ()

    if settings.dry_run:
        LOGGER.info("NOTIFY_DRY_RUN=1 — rendering %s event(s) without sending", len(events))
        print(render.text_body(events, dashboard_url))
        return (NotificationResult.ok("dry-run", f"{len(events)} event(s) rendered"),)

    if not settings.any_enabled:
        LOGGER.warning("no notification channel configured — see .env.example")
        return (NotificationResult.skipped("all", "no channel configured"),)

    results = (
        send_email(events, settings, dashboard_url, client),
        send_telegram(events, settings, dashboard_url, client),
        send_discord(events, settings, dashboard_url, client),
    )
    for result in results:
        if result.sent:
            LOGGER.info("notification %s: %s", result.channel, result.detail)
        elif result.detail.startswith("failed"):
            LOGGER.error("notification %s: %s", result.channel, result.detail)
        else:
            LOGGER.debug("notification %s: %s", result.channel, result.detail)
    return results
