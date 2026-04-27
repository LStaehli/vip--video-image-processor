"""License plate API.

GET    /api/plates/events              — recent plate detection events
GET    /api/plates/list                — allowlist + blocklist entries
POST   /api/plates/list                — add or update an entry
DELETE /api/plates/list/{plate_norm}   — remove an entry
"""
import logging
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import database as db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/plates")

# Registry injected by main.py (used to push list changes to live processors)
_registry = None


def init(registry) -> None:
    global _registry
    _registry = registry


def _normalize(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


class PlateListEntry(BaseModel):
    plate_text: str       # raw text as typed; normalised server-side
    list_type: str        # "allow" or "block"
    notes: str = ""


# ── Events ───────────────────────────────────────────────────────────────────

@router.get("/events")
async def get_plate_events(stream_id: int | None = None, limit: int = 100):
    """Return recent plate detection events."""
    events = await db.load_plate_events(stream_id=stream_id, limit=min(limit, 500))
    return {"events": events}


# ── Allow / block list ───────────────────────────────────────────────────────

@router.get("/list")
async def get_plate_list():
    """Return all entries in the plate allow/block list."""
    entries = await db.load_plate_list()
    return {"entries": entries}


@router.post("/list", status_code=201)
async def add_plate_list_entry(body: PlateListEntry):
    """Add or update a plate in the allow/block list."""
    if body.list_type not in ("allow", "block"):
        raise HTTPException(status_code=422, detail="list_type must be 'allow' or 'block'")
    plate_norm = _normalize(body.plate_text)
    if not plate_norm:
        raise HTTPException(status_code=422, detail="plate_text contains no alphanumeric characters")

    await db.upsert_plate_list_entry(
        plate_text_norm=plate_norm,
        plate_text_raw=body.plate_text.strip().upper(),
        list_type=body.list_type,
        notes=body.notes,
    )
    logger.info("Plate list entry upserted: %s → %s", plate_norm, body.list_type)
    await _push_list_to_processors()
    return {"plate_text_norm": plate_norm, "list_type": body.list_type}


@router.delete("/list/{plate_norm}", status_code=204)
async def delete_plate_list_entry(plate_norm: str):
    """Remove a plate from the allow/block list."""
    norm = _normalize(plate_norm)
    if not await db.delete_plate_list_entry(norm):
        raise HTTPException(status_code=404, detail="Plate not found in list")
    logger.info("Plate list entry removed: %s", norm)
    await _push_list_to_processors()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _push_list_to_processors() -> None:
    """Push the updated plate list to all live PlateProcessor instances."""
    if not _registry:
        return
    entries = await db.load_plate_list()
    for stack in _registry.all():
        proc = stack.get_processor("PlateProcessor")
        if proc:
            proc.reload_plate_list(entries)
