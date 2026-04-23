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
