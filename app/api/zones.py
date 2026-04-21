"""Zone management API.

GET    /api/zones        — list all zones
POST   /api/zones        — create a zone  (name + normalised polygon)
DELETE /api/zones/{id}   — remove one zone
DELETE /api/zones        — clear all zones
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.processors.zones import add_zone, clear_zones, remove_zone, zones

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/zones")


class ZoneCreate(BaseModel):
    name: str
    polygon: list[list[float]]   # [[nx, ny], …] normalised 0–1


@router.get("")
async def list_zones():
    return [{"id": z.id, "name": z.name, "polygon": z.polygon} for z in zones.values()]


@router.post("", status_code=201)
async def create_zone(body: ZoneCreate):
    if len(body.polygon) < 3:
        raise HTTPException(status_code=422, detail="Polygon must have at least 3 points")
    zone = add_zone(name=body.name, polygon=body.polygon)
    return {"id": zone.id, "name": zone.name, "polygon": zone.polygon}


@router.delete("/{zone_id}", status_code=204)
async def delete_zone(zone_id: str):
    if not remove_zone(zone_id):
        raise HTTPException(status_code=404, detail="Zone not found")


@router.delete("", status_code=204)
async def clear_all_zones():
    clear_zones()
