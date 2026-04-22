"""In-memory face embedding store backed by SQLite.

The in-memory dict is the hot path for recognition (sync cosine search).
All mutations are written through to the DB immediately via
asyncio.ensure_future() so the sync processor API is preserved.
"""
import asyncio
import logging
from datetime import datetime

import numpy as np

from app.services import database as db

logger = logging.getLogger(__name__)

# name -> {embedding: np.ndarray, created_at: str}
_store: dict[str, dict] = {}


async def init() -> None:
    """Load all faces from DB into memory. Called at startup."""
    global _store
    _store = await db.load_faces()
    logger.info("Face store: loaded %d reference(s) from DB", len(_store))


# ── Read ──────────────────────────────────────────────────────────────────────

def all_faces() -> dict[str, np.ndarray]:
    """Return {name: embedding} — hot path for the face processor."""
    return {name: entry["embedding"] for name, entry in _store.items()}


def face_list() -> list[dict]:
    """Return [{name, created_at}, ...] — used by the API."""
    return [
        {"name": name, "created_at": entry["created_at"]}
        for name, entry in _store.items()
    ]


def face_names() -> list[str]:
    return list(_store.keys())


# ── Write ─────────────────────────────────────────────────────────────────────

def add_face(name: str, embedding: np.ndarray) -> str:
    """Enroll a face. Returns the ISO timestamp of creation."""
    created_at = datetime.now().isoformat(timespec="seconds")
    _store[name] = {"embedding": embedding.astype(np.float32), "created_at": created_at}
    asyncio.ensure_future(db.upsert_face(name, embedding, created_at))
    logger.info("Face store: enrolled '%s'", name)
    return created_at


def rename_face(old_name: str, new_name: str) -> bool:
    """Rename an enrolled face. Returns False if not found or name taken."""
    if old_name not in _store:
        return False
    if new_name in _store and new_name != old_name:
        return False
    entry = _store.pop(old_name)
    _store[new_name] = entry
    asyncio.ensure_future(db.rename_face_db(old_name, new_name))
    logger.info("Face store: renamed '%s' → '%s'", old_name, new_name)
    return True


def remove_face(name: str) -> bool:
    if name not in _store:
        return False
    del _store[name]
    asyncio.ensure_future(db.delete_face(name))
    logger.info("Face store: removed '%s'", name)
    return True


def clear() -> None:
    _store.clear()
    asyncio.ensure_future(db.delete_all_faces())
