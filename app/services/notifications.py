"""Notification service — Telegram and email.

Sends an alert whenever a detection zone is triggered.
Both channels are optional: if the required config values are empty the
channel is silently skipped, so the service degrades gracefully.

Per-zone cooldown (notify_cooldown seconds, default 60) prevents repeated
alerts during a long recording session triggered by the same zone.
"""
import asyncio
import logging
import time
from datetime import datetime
from email.mime.text import MIMEText

import aiosmtplib
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# zone_id → monotonic timestamp of last notification sent
_last_notified: dict[str, float] = {}


async def notify_zone_trigger(
    zone_id: str,
    zone_name: str,
    recording_path: str | None = None,
) -> None:
    """Fire Telegram + email alerts for a zone entry event.

    Respects settings.notify_cooldown per zone to suppress repeated
    alerts while the same zone remains continuously triggered.
    """
    now = time.monotonic()
    if now - _last_notified.get(zone_id, 0.0) < settings.notify_cooldown:
        logger.debug("Notification suppressed for zone '%s' (cooldown)", zone_name)
        return
    _last_notified[zone_id] = now

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tasks: list = []

    if settings.telegram_bot_token and settings.telegram_chat_id:
        tasks.append(_send_telegram(zone_name, ts, recording_path))

    if settings.smtp_host and settings.notify_email:
        tasks.append(_send_email(zone_name, ts, recording_path))

    if not tasks:
        logger.debug("No notification channels configured — skipping")
        return

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            logger.error("Notification delivery error: %s", result)


# ── Telegram ──────────────────────────────────────────────────────────────────

async def _send_telegram(
    zone_name: str,
    ts: str,
    recording_path: str | None,
) -> None:
    lines = [
        "🚨 <b>Zone triggered</b>",
        f"Zone: <b>{zone_name}</b>",
        f"Time: {ts}",
    ]
    if recording_path:
        lines.append(f"Recording: <code>{recording_path}</code>")

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json={
            "chat_id": settings.telegram_chat_id,
            "text": "\n".join(lines),
            "parse_mode": "HTML",
        })
        resp.raise_for_status()
    logger.info("Telegram notification sent (zone=%s)", zone_name)


# ── Email ─────────────────────────────────────────────────────────────────────

async def _send_email(
    zone_name: str,
    ts: str,
    recording_path: str | None,
) -> None:
    lines = [
        f"Zone triggered: {zone_name}",
        f"Time: {ts}",
    ]
    if recording_path:
        lines.append(f"Recording saved to: {recording_path}")

    msg = MIMEText("\n".join(lines))
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = settings.notify_email
    msg["Subject"] = f"[VIP] Zone triggered: {zone_name}"

    # Port 465 → implicit TLS; port 587 / anything else → STARTTLS
    use_tls = settings.smtp_port == 465

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        use_tls=use_tls,
        start_tls=not use_tls,
    )
    logger.info("Email notification sent to %s (zone=%s)", settings.notify_email, zone_name)
