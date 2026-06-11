"""
Genetec AutoVu Data Exporter receiver.

POST /api/ingest/token  -- OAuth2 client-credentials token endpoint.
POST /api/ingest/reads  -- receives read events (Bearer auth required).

The Data Exporter is configured with:
    Server URL : https://<host>/parkingperks/api/ingest/reads
    Token URL  : https://<host>/parkingperks/api/ingest/token
    Client ID / Client secret : INGEST_CLIENT_ID / INGEST_CLIENT_SECRET (.env)

It POSTs each read as JSON the moment a camera sees a plate. Payload shapes
handled (Security Center 5.12 admin guide):
    {"Read": {...}}                      -- plain read export
    {"Vehicle": {"Read": {...}}, ...}    -- hit-wrapped read (if Hits enabled)
    [ ...either of the above... ]        -- batched
    {...bare read fields...}             -- defensive

Only Plate + DateLocal/TimeLocal (+ camera name) are stored -- wall-clock
campus time, never timezone-converted. Images are ignored even if sent.

Tokens are random, in-memory, 1-hour expiry. An app restart invalidates
them; the exporter just requests a new one on the next 401.
"""

from __future__ import annotations

import base64
import logging
import secrets
import time
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import settings
from app.core.normalise import normalise_reads_plate
from app.store import reads_db

logger = logging.getLogger(__name__)

router = APIRouter()

_TOKEN_TTL_SECONDS = 3600
_tokens: dict[str, float] = {}  # token -> expiry epoch

# .NET date-format strings (Data Exporter dropdown) -> strptime
_DATE_FORMATS = {
    "MM/dd/yyyy": "%m/%d/%Y",
    "dd/MM/yyyy": "%d/%m/%Y",
    "yyyy-MM-dd": "%Y-%m-%d",
    "yyyy/MM/dd": "%Y/%m/%d",
}


# ---------------------------------------------------------------------------
# OAuth2 client-credentials token endpoint
# ---------------------------------------------------------------------------

@router.post("/ingest/token")
async def issue_token(request: Request) -> dict:
    if not settings.ingest_client_id or not settings.ingest_client_secret:
        raise HTTPException(503, "Ingest credentials are not configured on the server.")

    client_id, client_secret = await _extract_client_credentials(request)

    if not (
        secrets.compare_digest(client_id or "", settings.ingest_client_id)
        and secrets.compare_digest(client_secret or "", settings.ingest_client_secret)
    ):
        logger.warning("Ingest token request with bad credentials (client_id=%r)", client_id)
        raise HTTPException(401, "invalid_client")

    token = secrets.token_urlsafe(32)
    now = time.time()
    # purge expired tokens so the dict can't grow unbounded
    for t in [t for t, exp in _tokens.items() if exp < now]:
        del _tokens[t]
    _tokens[token] = now + _TOKEN_TTL_SECONDS

    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": _TOKEN_TTL_SECONDS,
    }


async def _extract_client_credentials(request: Request) -> tuple[str | None, str | None]:
    """Spec-compliant clients send HTTP Basic; others put creds in the
    form body or JSON. Accept all three."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode()
            cid, _, csec = decoded.partition(":")
            return cid, csec
        except Exception:
            return None, None

    content_type = request.headers.get("content-type", "")
    try:
        if "json" in content_type:
            body = await request.json()
        else:
            form = await request.form()
            body = dict(form)
    except Exception:
        return None, None
    return body.get("client_id"), body.get("client_secret")


def _require_bearer(authorization: str | None) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token",
                            headers={"WWW-Authenticate": "Bearer"})
    token = authorization[7:].strip()
    exp = _tokens.get(token)
    if exp is None or exp < time.time():
        _tokens.pop(token, None)
        raise HTTPException(401, "Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})


# ---------------------------------------------------------------------------
# Read ingestion
# ---------------------------------------------------------------------------

@router.post("/ingest/reads")
async def ingest_reads(request: Request, authorization: str | None = Header(None)) -> dict:
    _require_bearer(authorization)

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Body must be JSON")

    read_objs = _extract_read_objs(payload)
    rows = []
    skipped = 0
    for obj in read_objs:
        parsed = _parse_read(obj)
        if parsed:
            rows.append(parsed)
        else:
            skipped += 1

    stored = reads_db.insert_reads(rows)
    if skipped:
        logger.info("Ingest: %d events skipped (no plate / bad timestamp)", skipped)

    return {"received": len(read_objs), "parsed": len(rows),
            "stored_new": stored, "skipped": skipped}


def _extract_read_objs(payload) -> list[dict]:
    if isinstance(payload, list):
        out: list[dict] = []
        for item in payload:
            out.extend(_extract_read_objs(item))
        return out
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("Read"), dict):
        return [payload["Read"]]
    vehicle = payload.get("Vehicle")
    if isinstance(vehicle, dict) and isinstance(vehicle.get("Read"), dict):
        return [vehicle["Read"]]
    if isinstance(payload.get("Reads"), list):
        return [r for r in payload["Reads"] if isinstance(r, dict)]
    if "Plate" in payload:  # bare read object
        return [payload]
    return []


def _parse_read(obj: dict) -> tuple[str, str, str] | None:
    """Returns (plate, 'YYYY-MM-DD HH:MM:SS' local wall-clock, camera) or None."""
    plate = normalise_reads_plate(str(obj.get("Plate") or ""))
    if not plate or plate == "-" or set(plate) == {"*"}:
        return None

    date_raw = str(obj.get("DateLocal") or "").strip()
    time_raw = str(obj.get("TimeLocal") or "").strip()
    if not date_raw or not time_raw:
        return None

    dt = _parse_local(date_raw, time_raw)
    if dt is None:
        logger.warning("Ingest: unparseable timestamp %r %r (check GENETEC_DATE_FORMAT)",
                       date_raw, time_raw)
        return None

    camera = str(obj.get("CameraName") or obj.get("SharpName") or "").strip()
    return plate, dt.strftime("%Y-%m-%d %H:%M:%S"), camera


def _parse_local(date_raw: str, time_raw: str) -> datetime | None:
    configured = _DATE_FORMATS.get(settings.genetec_date_format, "%m/%d/%Y")
    candidates = [configured] + [f for f in ("%Y-%m-%d", "%m/%d/%Y") if f != configured]
    for fmt in candidates:
        try:
            return datetime.strptime(f"{date_raw} {time_raw}", f"{fmt} %H:%M:%S")
        except ValueError:
            continue
    return None
