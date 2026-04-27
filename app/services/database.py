"""SQLite database service.

Single persistent aiosqlite connection opened at startup and closed at
shutdown. All table operations are centralised here.

Tables
------
zones                   — persisted zone definitions (survives restarts)
recordings              — metadata for every recording session
zone_events             — each time motion entered a zone
face_recognition_events — rate-limited face recognition hits
faces                   — enrolled face embeddings (replaces faces.json)
"""
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import aiosqlite
import numpy as np

logger = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None


# ── Lifecycle ─────────────────────────────────────────────────────────────────

async def init(path: str) -> None:
    global _db
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(path)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    await _create_schema()
    logger.info("Database initialised: %s", path)


async def close() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database not initialised — call database.init() first")
    return _db


# ── Schema ────────────────────────────────────────────────────────────────────

async def _create_schema() -> None:
    await get_db().executescript("""
        CREATE TABLE IF NOT EXISTS zones (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            polygon    TEXT NOT NULL,
            created_at TEXT NOT NULL,
            stream_id  INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS recordings (
            id                TEXT PRIMARY KEY,
            path              TEXT NOT NULL,
            start_time        TEXT NOT NULL,
            end_time          TEXT,
            duration_seconds  REAL,
            trigger           TEXT NOT NULL,
            trigger_zone_id   TEXT,
            trigger_face_name TEXT
        );

        CREATE TABLE IF NOT EXISTS zone_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id      TEXT NOT NULL,
            zone_name    TEXT NOT NULL,
            entered_at   TEXT NOT NULL,
            recording_id TEXT
        );

        CREATE TABLE IF NOT EXISTS face_recognition_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            face_name    TEXT NOT NULL,
            similarity   REAL NOT NULL,
            detected_at  TEXT NOT NULL,
            recording_id TEXT
        );

        CREATE TABLE IF NOT EXISTS faces (
            name       TEXT PRIMARY KEY,
            embedding  BLOB NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS streams (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_number INTEGER NOT NULL DEFAULT 1,
            name           TEXT    NOT NULL DEFAULT 'Channel 1',
            url            TEXT    NOT NULL DEFAULT '0',
            enabled        INTEGER NOT NULL DEFAULT 1,
            created_at     TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS zone_settings (
            zone_id          TEXT PRIMARY KEY,
            telegram_message TEXT NOT NULL DEFAULT '',
            email_message    TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS face_notification_settings (
            face_name        TEXT PRIMARY KEY,
            notify_enabled   INTEGER NOT NULL DEFAULT 1,
            telegram_message TEXT NOT NULL DEFAULT '',
            email_message    TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS stream_config (
            stream_id INTEGER NOT NULL,
            key       TEXT    NOT NULL,
            value     TEXT    NOT NULL,
            PRIMARY KEY (stream_id, key)
        );

        CREATE TABLE IF NOT EXISTS plate_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            stream_id       INTEGER NOT NULL,
            plate_text      TEXT    NOT NULL,
            plate_text_norm TEXT    NOT NULL,
            confidence      REAL    NOT NULL,
            detected_at     TEXT    NOT NULL,
            recording_id    TEXT,
            screenshot_path TEXT
        );

        CREATE TABLE IF NOT EXISTS plate_list (
            plate_text_norm TEXT PRIMARY KEY,
            plate_text_raw  TEXT NOT NULL,
            list_type       TEXT NOT NULL,
            notes           TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL
        );
    """)
    await get_db().commit()
    await _migrate()


async def _migrate() -> None:
    """Apply additive schema migrations for columns added after initial release."""
    db = get_db()
    # zones.stream_id — added in Phase C (per-stream zones)
    async with db.execute("PRAGMA table_info(zones)") as cur:
        cols = {row[1] for row in await cur.fetchall()}
    if "stream_id" not in cols:
        await db.execute(
            "ALTER TABLE zones ADD COLUMN stream_id INTEGER NOT NULL DEFAULT 1"
        )
        await db.commit()
        logger.info("Migration applied: zones.stream_id")

    # streams.channel_number uniqueness — enforced via index (safe to add on existing tables)
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_streams_channel_number ON streams(channel_number)"
    )
    await db.commit()

    # face_notification_settings.notify_enabled — added to allow per-face alert toggle
    async with db.execute("PRAGMA table_info(face_notification_settings)") as cur:
        face_notif_cols = {row[1] for row in await cur.fetchall()}
    if "notify_enabled" not in face_notif_cols and face_notif_cols:
        await db.execute(
            "ALTER TABLE face_notification_settings ADD COLUMN notify_enabled INTEGER NOT NULL DEFAULT 1"
        )
        await db.commit()
        logger.info("Migration applied: face_notification_settings.notify_enabled")


# ── Helpers ───────────────────────────────────────────────────────────────────

def new_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── Zones ─────────────────────────────────────────────────────────────────────

async def load_zones(stream_id: int) -> list[dict]:
    async with get_db().execute(
        "SELECT id, name, polygon FROM zones WHERE stream_id = ? ORDER BY created_at",
        (stream_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [
        {"id": r["id"], "name": r["name"], "polygon": json.loads(r["polygon"])}
        for r in rows
    ]


async def insert_zone(stream_id: int, zone_id: str, name: str, polygon: list) -> None:
    db = get_db()
    await db.execute(
        "INSERT INTO zones (id, name, polygon, created_at, stream_id) VALUES (?, ?, ?, ?, ?)",
        (zone_id, name, json.dumps(polygon), _now(), stream_id),
    )
    await db.commit()


async def delete_zone(zone_id: str) -> None:
    db = get_db()
    await db.execute("DELETE FROM zones WHERE id = ?", (zone_id,))
    await db.commit()


async def delete_all_zones(stream_id: int) -> None:
    db = get_db()
    await db.execute("DELETE FROM zones WHERE stream_id = ?", (stream_id,))
    await db.commit()


# ── Recordings ────────────────────────────────────────────────────────────────

async def insert_recording(
    recording_id: str,
    path: str,
    trigger: str,
    trigger_zone_id: str | None = None,
    trigger_face_name: str | None = None,
) -> None:
    db = get_db()
    await db.execute(
        """INSERT INTO recordings
           (id, path, start_time, trigger, trigger_zone_id, trigger_face_name)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (recording_id, path, _now(), trigger, trigger_zone_id, trigger_face_name),
    )
    await db.commit()


async def finalize_recording(recording_id: str, duration: float) -> None:
    db = get_db()
    await db.execute(
        "UPDATE recordings SET end_time = ?, duration_seconds = ? WHERE id = ?",
        (_now(), round(duration, 2), recording_id),
    )
    await db.commit()


# ── Zone events ───────────────────────────────────────────────────────────────

async def log_zone_event(
    zone_id: str,
    zone_name: str,
    recording_id: str | None = None,
) -> None:
    db = get_db()
    await db.execute(
        """INSERT INTO zone_events (zone_id, zone_name, entered_at, recording_id)
           VALUES (?, ?, ?, ?)""",
        (zone_id, zone_name, _now(), recording_id),
    )
    await db.commit()


# ── Face recognition events ───────────────────────────────────────────────────

async def log_face_event(
    face_name: str,
    similarity: float,
    recording_id: str | None = None,
) -> None:
    db = get_db()
    await db.execute(
        """INSERT INTO face_recognition_events
           (face_name, similarity, detected_at, recording_id) VALUES (?, ?, ?, ?)""",
        (face_name, round(similarity, 4), _now(), recording_id),
    )
    await db.commit()


# ── Faces ─────────────────────────────────────────────────────────────────────

async def load_faces() -> dict[str, dict]:
    """Return {name: {embedding: np.ndarray, created_at: str}}."""
    async with get_db().execute(
        "SELECT name, embedding, created_at FROM faces"
    ) as cur:
        rows = await cur.fetchall()
    return {
        r["name"]: {
            "embedding": np.frombuffer(r["embedding"], dtype=np.float32).copy(),
            "created_at": r["created_at"],
        }
        for r in rows
    }


async def upsert_face(name: str, embedding: np.ndarray, created_at: str) -> None:
    db = get_db()
    await db.execute(
        """INSERT INTO faces (name, embedding, created_at, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(name) DO UPDATE
               SET embedding = excluded.embedding, updated_at = excluded.updated_at""",
        (name, embedding.astype(np.float32).tobytes(), created_at, _now()),
    )
    await db.commit()


async def rename_face_db(old_name: str, new_name: str) -> None:
    db = get_db()
    await db.execute(
        "UPDATE faces SET name = ?, updated_at = ? WHERE name = ?",
        (new_name, _now(), old_name),
    )
    await db.commit()


async def delete_face(name: str) -> None:
    db = get_db()
    await db.execute("DELETE FROM faces WHERE name = ?", (name,))
    await db.commit()


async def delete_all_faces() -> None:
    db = get_db()
    await db.execute("DELETE FROM faces")
    await db.commit()


# ── Streams ───────────────────────────────────────────────────────────────────

async def load_streams() -> list[dict]:
    async with get_db().execute(
        "SELECT id, channel_number, name, url, enabled FROM streams ORDER BY channel_number, id"
    ) as cur:
        rows = await cur.fetchall()
    return [
        {
            "id": r["id"],
            "channel_number": r["channel_number"],
            "name": r["name"],
            "url": r["url"],
            "enabled": bool(r["enabled"]),
        }
        for r in rows
    ]


async def stream_count() -> int:
    async with get_db().execute("SELECT COUNT(*) FROM streams") as cur:
        row = await cur.fetchone()
    return row[0] if row else 0


async def insert_stream(channel_number: int, name: str, url: str) -> dict:
    db = get_db()
    cur = await db.execute(
        "INSERT INTO streams (channel_number, name, url, enabled, created_at) VALUES (?, ?, ?, 1, ?)",
        (channel_number, name, url, _now()),
    )
    await db.commit()
    return {"id": cur.lastrowid, "channel_number": channel_number, "name": name, "url": url, "enabled": True}


async def update_stream(stream_id: int, **fields) -> bool:
    """Update any combination of channel_number, name, url, enabled."""
    allowed = {"channel_number", "name", "url", "enabled"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return True
    clauses = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [stream_id]
    db = get_db()
    cur = await db.execute(f"UPDATE streams SET {clauses} WHERE id = ?", values)
    await db.commit()
    return cur.rowcount > 0


async def delete_stream(stream_id: int) -> bool:
    db = get_db()
    cur = await db.execute("DELETE FROM streams WHERE id = ?", (stream_id,))
    await db.commit()
    return cur.rowcount > 0


# ── App settings (persisted key-value) ───────────────────────────────────────

async def load_app_settings() -> dict[str, str]:
    """Return all persisted application settings as {key: value}."""
    async with get_db().execute("SELECT key, value FROM app_settings") as cur:
        rows = await cur.fetchall()
    return {r["key"]: r["value"] for r in rows}


async def save_app_setting(key: str, value: str) -> None:
    """Upsert a single application setting."""
    db = get_db()
    await db.execute(
        """INSERT INTO app_settings (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        (key, value),
    )
    await db.commit()


# ── Zone settings ─────────────────────────────────────────────────────────────

async def get_zone_settings(zone_id: str) -> dict:
    """Return notification message settings for a zone (always returns a dict)."""
    async with get_db().execute(
        "SELECT telegram_message, email_message FROM zone_settings WHERE zone_id = ?",
        (zone_id,),
    ) as cur:
        row = await cur.fetchone()
    if row:
        return {"telegram_message": row["telegram_message"], "email_message": row["email_message"]}
    return {"telegram_message": "", "email_message": ""}


async def upsert_zone_settings(zone_id: str, telegram_message: str, email_message: str) -> None:
    db = get_db()
    await db.execute(
        """INSERT INTO zone_settings (zone_id, telegram_message, email_message)
           VALUES (?, ?, ?)
           ON CONFLICT(zone_id) DO UPDATE
               SET telegram_message = excluded.telegram_message,
                   email_message    = excluded.email_message""",
        (zone_id, telegram_message, email_message),
    )
    await db.commit()


async def delete_zone_settings(zone_id: str) -> None:
    db = get_db()
    await db.execute("DELETE FROM zone_settings WHERE zone_id = ?", (zone_id,))
    await db.commit()


# ── Stream config (per-stream key-value) ──────────────────────────────────────

async def load_stream_config(stream_id: int) -> dict[str, str]:
    """Return all stored config keys for a stream as {key: value} strings."""
    async with get_db().execute(
        "SELECT key, value FROM stream_config WHERE stream_id = ?", (stream_id,)
    ) as cur:
        rows = await cur.fetchall()
    return {r["key"]: r["value"] for r in rows}


async def save_stream_config(stream_id: int, data: dict[str, str]) -> None:
    """Bulk-upsert stream config key-value pairs in a single transaction."""
    db = get_db()
    await db.executemany(
        "INSERT INTO stream_config (stream_id, key, value) VALUES (?, ?, ?)"
        " ON CONFLICT(stream_id, key) DO UPDATE SET value = excluded.value",
        [(stream_id, k, v) for k, v in data.items()],
    )
    await db.commit()


# ── Face notification settings ────────────────────────────────────────────────

async def get_face_notification_settings(face_name: str) -> dict:
    """Return notification settings for a face (always returns a dict with defaults)."""
    async with get_db().execute(
        "SELECT notify_enabled, telegram_message, email_message FROM face_notification_settings WHERE face_name = ?",
        (face_name,),
    ) as cur:
        row = await cur.fetchone()
    if row:
        return {
            "notify_enabled":   bool(row["notify_enabled"]),
            "telegram_message": row["telegram_message"],
            "email_message":    row["email_message"],
        }
    return {"notify_enabled": True, "telegram_message": "", "email_message": ""}


async def get_all_face_notification_settings() -> dict[str, dict]:
    """Return all face notification settings keyed by face_name."""
    async with get_db().execute(
        "SELECT face_name, notify_enabled, telegram_message, email_message FROM face_notification_settings"
    ) as cur:
        rows = await cur.fetchall()
    return {
        r["face_name"]: {
            "notify_enabled":   bool(r["notify_enabled"]),
            "telegram_message": r["telegram_message"],
            "email_message":    r["email_message"],
        }
        for r in rows
    }


async def upsert_face_notification_settings(
    face_name: str,
    notify_enabled: bool,
    telegram_message: str,
    email_message: str,
) -> None:
    db = get_db()
    await db.execute(
        """INSERT INTO face_notification_settings (face_name, notify_enabled, telegram_message, email_message)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(face_name) DO UPDATE
               SET notify_enabled   = excluded.notify_enabled,
                   telegram_message = excluded.telegram_message,
                   email_message    = excluded.email_message""",
        (face_name, int(notify_enabled), telegram_message, email_message),
    )
    await db.commit()


async def rename_face_notification_settings(old_name: str, new_name: str) -> None:
    """Carry notification settings over when a face is renamed."""
    db = get_db()
    await db.execute(
        "UPDATE face_notification_settings SET face_name = ? WHERE face_name = ?",
        (new_name, old_name),
    )
    await db.commit()


async def delete_face_notification_settings(face_name: str) -> None:
    db = get_db()
    await db.execute("DELETE FROM face_notification_settings WHERE face_name = ?", (face_name,))
    await db.commit()


# ── Plate events ──────────────────────────────────────────────────────────────

async def log_plate_event(
    stream_id: int,
    plate_text: str,
    plate_text_norm: str,
    confidence: float,
    recording_id: str | None = None,
    screenshot_path: str | None = None,
) -> int:
    """Insert a plate detection event and return its row id."""
    db = get_db()
    cur = await db.execute(
        """INSERT INTO plate_events
           (stream_id, plate_text, plate_text_norm, confidence, detected_at, recording_id, screenshot_path)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (stream_id, plate_text, plate_text_norm, round(confidence, 4), _now(), recording_id, screenshot_path),
    )
    await db.commit()
    return cur.lastrowid


async def load_plate_events(stream_id: int | None = None, limit: int = 50) -> list[dict]:
    """Return recent plate events, optionally filtered to one stream."""
    if stream_id is not None:
        sql = (
            "SELECT id, stream_id, plate_text, plate_text_norm, confidence, "
            "detected_at, recording_id, screenshot_path "
            "FROM plate_events WHERE stream_id = ? ORDER BY id DESC LIMIT ?"
        )
        params = (stream_id, limit)
    else:
        sql = (
            "SELECT id, stream_id, plate_text, plate_text_norm, confidence, "
            "detected_at, recording_id, screenshot_path "
            "FROM plate_events ORDER BY id DESC LIMIT ?"
        )
        params = (limit,)
    async with get_db().execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── Plate allow/block list ────────────────────────────────────────────────────

async def load_plate_list() -> list[dict]:
    """Return all entries in the plate allow/block list."""
    async with get_db().execute(
        "SELECT plate_text_norm, plate_text_raw, list_type, notes, created_at "
        "FROM plate_list ORDER BY list_type, plate_text_norm"
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def upsert_plate_list_entry(
    plate_text_norm: str,
    plate_text_raw: str,
    list_type: str,
    notes: str = "",
) -> None:
    """Add or update a plate in the allow/block list."""
    db = get_db()
    await db.execute(
        """INSERT INTO plate_list (plate_text_norm, plate_text_raw, list_type, notes, created_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(plate_text_norm) DO UPDATE
               SET plate_text_raw = excluded.plate_text_raw,
                   list_type      = excluded.list_type,
                   notes          = excluded.notes""",
        (plate_text_norm, plate_text_raw, list_type, notes, _now()),
    )
    await db.commit()


async def delete_plate_list_entry(plate_text_norm: str) -> bool:
    """Remove a plate from the list. Returns True if a row was deleted."""
    db = get_db()
    cur = await db.execute(
        "DELETE FROM plate_list WHERE plate_text_norm = ?", (plate_text_norm,)
    )
    await db.commit()
    return cur.rowcount > 0
