"""Persistent storage for face reference embeddings.

Storage format (faces.json):
    {
        "John": {
            "embedding": [...512 floats],
            "created_at": "2026-04-22T14:31:42"
        },
        ...
    }

Backward-compatible with the old flat format (name -> embedding list).
All mutations are written to disk immediately.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Internal store: name -> {"embedding": np.ndarray, "created_at": str}
_store: dict[str, dict] = {}
_store_path: Path | None = None


def init(path: str) -> None:
    global _store_path
    _store_path = Path(path)
    _load()


def _load() -> None:
    if not (_store_path and _store_path.exists()):
        return
    try:
        data: dict = json.loads(_store_path.read_text())
        for name, value in data.items():
            if isinstance(value, list):
                # Backward compat: old format stored the embedding directly
                _store[name] = {
                    "embedding": np.array(value, dtype=np.float32),
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                }
            else:
                _store[name] = {
                    "embedding": np.array(value["embedding"], dtype=np.float32),
                    "created_at": value.get("created_at", datetime.now().isoformat(timespec="seconds")),
                }
        logger.info("Face store: loaded %d reference(s) from %s", len(_store), _store_path)
        # Re-save to normalise any backward-compat entries
        _save()
    except Exception as exc:
        logger.error("Face store: failed to load from %s: %s", _store_path, exc)


def _save() -> None:
    if not _store_path:
        return
    try:
        data = {
            name: {
                "embedding": entry["embedding"].tolist(),
                "created_at": entry["created_at"],
            }
            for name, entry in _store.items()
        }
        _store_path.write_text(json.dumps(data, indent=2))
    except Exception as exc:
        logger.error("Face store: failed to save to %s: %s", _store_path, exc)


# ── Read ──────────────────────────────────────────────────────────────────────

def all_faces() -> dict[str, np.ndarray]:
    """Return {name: embedding} — used by the processor for recognition."""
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
    _store[name] = {
        "embedding": embedding.astype(np.float32),
        "created_at": created_at,
    }
    logger.info("Face store: enrolled '%s'", name)
    _save()
    return created_at


def rename_face(old_name: str, new_name: str) -> bool:
    """Rename an enrolled face. Returns False if old_name not found or new_name taken."""
    if old_name not in _store:
        return False
    if new_name in _store and new_name != old_name:
        return False
    entry = _store.pop(old_name)
    _store[new_name] = entry
    logger.info("Face store: renamed '%s' → '%s'", old_name, new_name)
    _save()
    return True


def remove_face(name: str) -> bool:
    if name not in _store:
        return False
    del _store[name]
    logger.info("Face store: removed '%s'", name)
    _save()
    return True


def clear() -> None:
    _store.clear()
    _save()
