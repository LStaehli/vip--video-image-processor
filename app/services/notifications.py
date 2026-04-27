"""Notification service — Telegram and email.

Sends an alert whenever a detection zone is triggered or a known face is
recognised, including a JPEG snapshot of the annotated frame.

Both channels are optional: if the required config values are empty the
channel is silently skipped, so the service degrades gracefully.

Per-zone / per-face cooldown (notify_cooldown seconds, default 60) prevents
repeated alerts during a long recording session for the same zone or face.
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

# face_name → monotonic timestamp of last notification sent
_last_notified_faces: dict[str, float] = {}


async def notify_zone_trigger(
    zone_id: str,
    zone_name: str,
    recording_path: str | None = None,
    snapshot: bytes | None = None,
    telegram_message: str = "",
    email_message: str = "",
) -> None:
    """Fire Telegram + email alerts for a zone entry event.

    Args:
        zone_id:           Zone UUID (used for cooldown tracking).
        zone_name:         Human-readable zone name shown in the message.
        recording_path:    Path of the recording file that was started, if any.
        snapshot:          JPEG-encoded bytes of the annotated frame at trigger
                           time. Sent as a photo/attachment when provided.
        telegram_message:  Custom message body for Telegram (already resolved).
                           Falls back to the default when empty.
        email_message:     Custom message body for email (already resolved).
                           Falls back to the default when empty.
    """
    now = time.monotonic()
    if now - _last_notified.get(zone_id, 0.0) < settings.notify_cooldown:
        logger.debug("Notification suppressed for zone '%s' (cooldown)", zone_name)
        return
    _last_notified[zone_id] = now

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tasks: list = []

    if settings.telegram_bot_token and settings.telegram_chat_id:
        tasks.append(_send_telegram(zone_name, ts, recording_path, snapshot, telegram_message))

    if settings.smtp_host and settings.notify_email:
        tasks.append(_send_email(zone_name, ts, recording_path, snapshot, email_message))

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
    custom_message: str = "",
) -> None:
    if custom_message:
        caption = custom_message
    else:
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
    custom_message: str = "",
) -> None:
    if custom_message:
        body_text = custom_message
    else:
        body_lines = [
            f"Zone triggered: {zone_name}",
            f"Time: {ts}",
        ]
        if recording_path:
            body_lines.append(f"Recording saved to: {recording_path}")
        body_text = "\n".join(body_lines)

    if snapshot:
        msg: MIMEMultipart | MIMEText = MIMEMultipart()
        msg.attach(MIMEText(body_text))
        img = MIMEImage(snapshot, _subtype="jpeg")
        img.add_header("Content-Disposition", "attachment", filename="snapshot.jpg")
        msg.attach(img)
    else:
        msg = MIMEText(body_text)

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


# ── Face recognition notifications ───────────────────────────────────────────

async def notify_face_recognized(
    face_name: str,
    similarity: float,
    recording_path: str | None = None,
    snapshot: bytes | None = None,
    telegram_message: str = "",
    email_message: str = "",
) -> None:
    """Fire Telegram + email alerts when a known face is recognised.

    Args:
        face_name:         Enrolled face name (used for cooldown tracking).
        similarity:        Cosine similarity score (0–1).
        recording_path:    Path of the active recording file, if any.
        snapshot:          JPEG-encoded bytes of the annotated frame.
        telegram_message:  Custom message body for Telegram (already resolved).
        email_message:     Custom message body for email (already resolved).
    """
    now = time.monotonic()
    if now - _last_notified_faces.get(face_name, 0.0) < settings.notify_cooldown:
        logger.debug("Face notification suppressed for '%s' (cooldown)", face_name)
        return
    _last_notified_faces[face_name] = now

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tasks: list = []

    if settings.telegram_bot_token and settings.telegram_chat_id:
        tasks.append(_send_telegram_face(face_name, similarity, ts, recording_path, snapshot, telegram_message))

    if settings.smtp_host and settings.notify_email:
        tasks.append(_send_email_face(face_name, similarity, ts, recording_path, snapshot, email_message))

    if not tasks:
        logger.debug("No notification channels configured — skipping face notification")
        return

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            logger.error("Face notification delivery error: %s", result)


async def _send_telegram_face(
    face_name: str,
    similarity: float,
    ts: str,
    recording_path: str | None,
    snapshot: bytes | None,
    custom_message: str = "",
) -> None:
    if custom_message:
        caption = custom_message
    else:
        caption_lines = [
            "👤 <b>Face recognised</b>",
            f"Name: <b>{face_name}</b>",
            f"Match: {similarity:.0%}",
            f"Time: {ts}",
        ]
        if recording_path:
            caption_lines.append(f"Recording: <code>{recording_path}</code>")
        caption = "\n".join(caption_lines)

    async with httpx.AsyncClient(timeout=15) as client:
        if snapshot:
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
            resp = await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": caption,
                    "parse_mode": "HTML",
                },
            )
        resp.raise_for_status()

    logger.info("Telegram face notification sent (face=%s, snapshot=%s)", face_name, snapshot is not None)


async def _send_email_face(
    face_name: str,
    similarity: float,
    ts: str,
    recording_path: str | None,
    snapshot: bytes | None,
    custom_message: str = "",
) -> None:
    if custom_message:
        body_text = custom_message
    else:
        body_lines = [
            f"Face recognised: {face_name} ({similarity:.0%} match)",
            f"Time: {ts}",
        ]
        if recording_path:
            body_lines.append(f"Recording saved to: {recording_path}")
        body_text = "\n".join(body_lines)

    if snapshot:
        msg: MIMEMultipart | MIMEText = MIMEMultipart()
        msg.attach(MIMEText(body_text))
        img = MIMEImage(snapshot, _subtype="jpeg")
        img.add_header("Content-Disposition", "attachment", filename="snapshot.jpg")
        msg.attach(img)
    else:
        msg = MIMEText(body_text)

    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = settings.notify_email
    msg["Subject"] = f"[VIP] Face recognised: {face_name}"

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
        "Email face notification sent to %s (face=%s, snapshot=%s)",
        settings.notify_email, face_name, snapshot is not None,
    )
