"""Notification service — Telegram and email.

Sends an alert whenever a detection zone is triggered, including a JPEG
snapshot of the annotated frame captured at the moment of the trigger.

Both channels are optional: if the required config values are empty the
channel is silently skipped, so the service degrades gracefully.

Per-zone cooldown (notify_cooldown seconds, default 60) prevents repeated
alerts during a long recording session triggered by the same zone.
"""
import asyncio
import logging
import time
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
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
    snapshot: bytes | None = None,
) -> None:
    """Fire Telegram + email alerts for a zone entry event.

    Args:
        zone_id:        Zone UUID (used for cooldown tracking).
        zone_name:      Human-readable zone name shown in the message.
        recording_path: Path of the recording file that was started, if any.
        snapshot:       JPEG-encoded bytes of the annotated frame at trigger
                        time. Sent as a photo/attachment when provided.
    """
    if not settings.notify_on_zone_trigger:
        return

    now = time.monotonic()
    if now - _last_notified.get(zone_id, 0.0) < settings.notify_cooldown:
        logger.debug("Notification suppressed for zone '%s' (cooldown)", zone_name)
        return
    _last_notified[zone_id] = now

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tasks: list = []

    if settings.telegram_bot_token and settings.telegram_chat_id:
        tasks.append(_send_telegram(zone_name, ts, recording_path, snapshot))

    if settings.smtp_host and settings.notify_email:
        tasks.append(_send_email(zone_name, ts, recording_path, snapshot))

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
    snapshot: bytes | None,
) -> None:
    caption_lines = [
        "🚨 <b>Zone triggered</b>",
        f"Zone: <b>{zone_name}</b>",
        f"Time: {ts}",
    ]
    if recording_path:
        caption_lines.append(f"Recording: <code>{recording_path}</code>")
    caption = "\n".join(caption_lines)

    async with httpx.AsyncClient(timeout=15) as client:
        if snapshot:
            # Send annotated snapshot via sendPhoto
            resp = await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendPhoto",
                data={
                    "chat_id": settings.telegram_chat_id,
                    "caption": caption,
                    "parse_mode": "HTML",
                },
                files={"photo": ("snapshot.jpg", snapshot, "image/jpeg")},
            )
        else:
            # Fallback to text-only message
            resp = await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": caption,
                    "parse_mode": "HTML",
                },
            )
        resp.raise_for_status()

    logger.info("Telegram notification sent (zone=%s, snapshot=%s)", zone_name, snapshot is not None)


# ── Email ─────────────────────────────────────────────────────────────────────

async def _send_email(
    zone_name: str,
    ts: str,
    recording_path: str | None,
    snapshot: bytes | None,
) -> None:
    body_lines = [
        f"Zone triggered: {zone_name}",
        f"Time: {ts}",
    ]
    if recording_path:
        body_lines.append(f"Recording saved to: {recording_path}")

    if snapshot:
        msg: MIMEMultipart | MIMEText = MIMEMultipart()
        msg.attach(MIMEText("\n".join(body_lines)))
        img = MIMEImage(snapshot, _subtype="jpeg")
        img.add_header("Content-Disposition", "attachment", filename="snapshot.jpg")
        msg.attach(img)
    else:
        msg = MIMEText("\n".join(body_lines))

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
    logger.info(
        "Email notification sent to %s (zone=%s, snapshot=%s)",
        settings.notify_email, zone_name, snapshot is not None,
    )
