"""A university's own campus map (tenants.campus and campus_image, migration 011), edited in the
admin under an assistant's "Campus map" skill. GIU keeps its built-in map (app/campus.py).

GET  /admin/campus     {built_in, buildings, places, image_url}            (university admins)
PUT  /admin/campus     {buildings, places, image?}   image: a data URL, "" removes it, absent keeps it
GET  /campus/image     the campus picture (public: the chat shows it under answers)

A building: {code: "B", name, floors (0 = ground floor only), x?, y?, lat?, lng?}; a place:
{name, words?, x?, y?, lat?, lng?}. x and y are the spot on the picture (0 to 1 from the top
left), lat and lng the entrance for the "Walk me there" link. Room codes are the building's code,
the floor and a two-digit number: B204 = Building B, 2nd floor.
"""
import base64
import logging
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from app import tenants
from app.auth import tenant_admin
from app.db import get_connection

router = APIRouter()
log = logging.getLogger("uvicorn.error")

IMAGE = re.compile(r"^data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)$")
MAX_IMAGE_CHARS = 4_000_000  # a data URL of about 3 MB
BUILDING_CODE = re.compile(r"^[A-Z]{1,3}$")


class Spot(BaseModel):
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


class BuildingIn(Spot):
    code: str = Field(min_length=1, max_length=3)
    name: str = Field(min_length=1, max_length=80)
    floors: int = Field(default=0, ge=0, le=9)


class PlaceIn(Spot):
    name: str = Field(min_length=1, max_length=60)
    words: list[str] = Field(default_factory=list, max_length=10)


class CampusIn(BaseModel):
    buildings: list[BuildingIn] = Field(default_factory=list, max_length=40)
    places: list[PlaceIn] = Field(default_factory=list, max_length=40)
    image: str | None = Field(default=None, max_length=MAX_IMAGE_CHARS)


def image_url(campus: dict | None) -> str:
    """The picture's address for the browser (changes with every new picture), or ""."""
    version = (campus or {}).get("image_version")
    return f"/campus/image?v={version}" if version else ""


def campus_out(tenant: tenants.Tenant) -> dict:
    campus = tenant.campus or {}
    return {"built_in": tenant.campus_map, "buildings": campus.get("buildings", []),
            "places": campus.get("places", []), "image_url": image_url(campus)}


def place_key(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "place"
    key, n = base, 2
    while key in taken:
        key, n = f"{base}_{n}", n + 1
    taken.add(key)
    return key


@router.get("/admin/campus", dependencies=[Depends(tenant_admin)])
def get_campus():
    return campus_out(tenants.current())


@router.put("/admin/campus", dependencies=[Depends(tenant_admin)])
def save_campus(body: CampusIn):
    """Save the university's buildings, places and (optionally) its campus picture."""
    tenant = tenants.current()
    if tenant.campus_map:
        raise HTTPException(400, f"{tenant.short} has a built-in campus map.")
    buildings = []
    for b in body.buildings:
        code = b.code.strip().upper()
        if not BUILDING_CODE.match(code):
            raise HTTPException(400, f'Building codes are 1 to 3 letters, like "B" ("{b.code}" is not).')
        if code in {x["code"] for x in buildings}:
            raise HTTPException(400, f"Two buildings have the code {code}.")
        buildings.append({**b.model_dump(), "code": code, "name": b.name.strip()})
    keys: set[str] = set()
    places = [{**p.model_dump(), "name": p.name.strip(), "key": place_key(p.name, keys),
               "words": [w.strip() for w in p.words if w.strip()][:10]} for p in body.places]
    version = (tenant.campus or {}).get("image_version")
    values = {}
    if body.image is not None:
        if body.image and not IMAGE.match(body.image):
            raise HTTPException(400, "The campus picture must be a PNG, JPEG or WebP picture.")
        values["campus_image"] = body.image or None
        version = int(time.time() * 1000) if body.image else None
    values["campus"] = Jsonb({"buildings": buildings, "places": places, "image_version": version})
    with get_connection(tenant.id) as conn:
        conn.execute(f"UPDATE tenants SET {', '.join(f'{k} = %s' for k in values)} WHERE id = %s",
                     (*values.values(), tenant.id))
    tenants._by_host.clear()  # the next request reads the new campus
    log.info("Admin: campus saved (%d buildings, %d places)", len(buildings), len(places))
    return {"ok": True, "image_url": image_url({"image_version": version})}


@router.get("/campus/image")
def campus_image():
    tenant = tenants.current()
    with get_connection(tenant.id) as conn:
        row = conn.execute("SELECT campus_image FROM tenants WHERE id = %s", (tenant.id,)).fetchone()
    match = IMAGE.match(row[0] or "") if row else None
    if not match:
        raise HTTPException(404, "No campus picture.")
    # The address changes with every new picture (?v=), so it may be kept for a long time.
    return Response(base64.b64decode(match.group(2)), media_type=match.group(1),
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})
