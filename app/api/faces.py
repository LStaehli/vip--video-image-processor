"""Face management API.

Endpoints for enrolling, renaming, listing, and deleting face references.
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import face_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/faces")

# References injected by main.py
_pipeline = None
_face_proc = None


def init(pipeline, face_proc) -> None:
    global _pipeline, _face_proc
    _pipeline = pipeline
    _face_proc = face_proc


class EnrollRequest(BaseModel):
    name: str


class RenameRequest(BaseModel):
    new_name: str


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

    if not _face_proc or not _face_proc._model_ready:
        raise HTTPException(
            status_code=503,
            detail="Face model not loaded yet — enable Face Recognition first and wait for the model to load",
        )

    frame = getattr(_pipeline, "_last_frame", None)
    if frame is None:
        raise HTTPException(status_code=503, detail="No video frame available yet")

    embedding = _face_proc.get_embedding_from_frame(frame)
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
    return {"renamed": True, "old_name": name, "new_name": new_name}


@router.delete("/{name}")
async def delete_face(name: str):
    """Remove an enrolled face by name."""
    if not face_store.remove_face(name):
        raise HTTPException(status_code=404, detail=f"No face enrolled under '{name}'")
    return {"deleted": True, "name": name}


@router.delete("")
async def clear_faces():
    """Remove all enrolled faces."""
    face_store.clear()
    return {"cleared": True}
