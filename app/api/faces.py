"""Face management API.

Endpoints for enrolling, renaming, listing, and deleting face references,
plus per-face notification message settings.
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import database as db
from app.services import face_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/faces")

# Registry injected by main.py
_registry = None


def init(registry) -> None:
    global _registry
    _registry = registry


class EnrollRequest(BaseModel):
    name: str


class RenameRequest(BaseModel):
    new_name: str


class FaceNotifSettingsUpdate(BaseModel):
    notify_enabled: bool = True
    telegram_message: str = ""
    email_message: str = ""


@router.get("")
async def list_faces():
    """Return all enrolled faces with metadata."""
    return {"faces": face_store.face_list()}


@router.post("/enroll")
async def enroll_face(body: EnrollRequest):
    """Enroll a face from the current video frame."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name must not be empty")

    # Find a stack with a ready face processor
    face_proc = None
    pipeline = None
    if _registry:
        for stack in _registry.all():
            fp = stack.get_processor("FaceProcessor")
            if fp and getattr(fp, "_model_ready", False):
                face_proc = fp
                pipeline = stack.pipeline
                break

    if not face_proc:
        raise HTTPException(
            status_code=503,
            detail="Face model not loaded yet — enable Face Recognition first and wait for the model to load",
        )

    frame = getattr(pipeline, "_last_frame", None)
    if frame is None:
        raise HTTPException(status_code=503, detail="No video frame available yet")

    embedding = face_proc.get_embedding_from_frame(frame)
    if embedding is None:
        raise HTTPException(
            status_code=422,
            detail="No face detected in the current frame — make sure your face is clearly visible",
        )

    created_at = face_store.add_face(name, embedding)
    logger.info("Enrolled face: '%s'", name)
    return {"enrolled": True, "name": name, "created_at": created_at}


@router.patch("/{name}")
async def rename_face(name: str, body: RenameRequest):
    """Rename an enrolled face."""
    new_name = body.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="New name must not be empty")
    if not face_store.rename_face(name, new_name):
        raise HTTPException(
            status_code=404 if name not in face_store.face_names() else 409,
            detail=f"'{name}' not found" if name not in face_store.face_names() else f"'{new_name}' is already enrolled",
        )
    # Carry notification settings over to the new name
    await db.rename_face_notification_settings(name, new_name)
    return {"renamed": True, "old_name": name, "new_name": new_name}


@router.delete("/{name}")
async def delete_face(name: str):
    """Remove an enrolled face by name."""
    if not face_store.remove_face(name):
        raise HTTPException(status_code=404, detail=f"No face enrolled under '{name}'")
    await db.delete_face_notification_settings(name)
    return {"deleted": True, "name": name}


@router.delete("")
async def clear_faces():
    """Remove all enrolled faces."""
    face_store.clear()
    return {"cleared": True}


# ── Per-face notification settings ───────────────────────────────────────────

@router.get("/settings")
async def get_all_face_notif_settings():
    """Return notification settings for every enrolled face, keyed by name."""
    return await db.get_all_face_notification_settings()


@router.get("/{name}/settings")
async def get_face_notif_settings(name: str):
    """Return notification settings for a specific enrolled face."""
    return await db.get_face_notification_settings(name)


@router.put("/{name}/settings")
async def update_face_notif_settings(name: str, body: FaceNotifSettingsUpdate):
    """Save notification toggle and message templates for a specific enrolled face."""
    await db.upsert_face_notification_settings(
        name, body.notify_enabled, body.telegram_message, body.email_message
    )
    return await db.get_face_notification_settings(name)
