"""
T2 Flex — citations and permit holders client.

Calls T2 Flex web service queries via HTTP Basic Auth.
Two queries must be registered in T2 Flex Query Manager
(see backend/t2flex_queries.sql for the SQL to paste in).

Web service URL pattern:
    GET {T2_FLEX_BASE_URL}/webservices/query
        ?queryName=<name>
        &format=json
        [&PARAM=value ...]

Response shape expected:
    { "rows": [ {"COL": "val", ...}, ... ] }

Config (.env):
    T2_FLEX_BASE_URL   — base URL of T2 Flex server, no trailing slash
    T2_FLEX_USERNAME   — web services account username
    T2_FLEX_PASSWORD   — web services account password

Stub mode:
    USE_STUBS=true (default) loads from local test-data files.
    Set USE_STUBS=false to hit the live T2 Flex web services.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx
import pandas as pd

from app.config import settings
from app.core.normalise import normalise_citations_plate, normalise_permits_plate
from app.integrations.base import Citation, CitationsAndPermitsClient, PermitHolder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class T2FlexClient(CitationsAndPermitsClient):

    async def fetch_citations(self, year: int, month: int) -> list[Citation]:
        if settings.use_stubs:
            return _load_citations_from_file(year, month)
        return await _fetch_citations_live(year, month)

    async def fetch_permits(self) -> list[PermitHolder]:
        if settings.use_stubs:
            return _load_permits_from_file()
        return await _fetch_permits_live()


# ---------------------------------------------------------------------------
# Live — web service calls
# ---------------------------------------------------------------------------

async def _call_query(query_name: str, params: dict[str, str] | None = None) -> list[dict]:
    """
    Call one named T2 Flex web service query and return the row list.
    Uses Basic Auth. Raises httpx.HTTPStatusError on non-2xx.
    """
    base = settings.t2_flex_base_url.rstrip("/")
    if not base:
        raise RuntimeError(
            "T2_FLEX_BASE_URL is not set in .env. "
            "Add it before running with USE_STUBS=false."
        )

    url = f"{base}/webservices/query"
    query_params: dict[str, str] = {"queryName": query_name, "format": "json"}
    if params:
        query_params.update(params)

    logger.info("T2 Flex → %s  params=%s", query_name, params)

    async with httpx.AsyncClient(
        auth=(settings.t2_flex_username, settings.t2_flex_password),
        verify=settings.t2_flex_verify_ssl,
        timeout=settings.t2_flex_timeout,
    ) as client:
        resp = await client.get(url, params=query_params)
        resp.raise_for_status()

    payload = resp.json()
    rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
    logger.info("T2 Flex '%s' → %d rows", query_name, len(rows))
    return rows


async def _fetch_permits_live() -> list[PermitHolder]:
    """
    Fetch active permit holders from T2 Flex web services.

    The SQL query uses LISTAGG so multiple plates per person are returned as
    a single comma-separated string (e.g. "674PRL,TC765L"). _expand_plates()
    splits and normalises them — same helper used by the stub loader.

    Plates come back as plain strings (e.g. "SK041H"), NOT in BC-PLATE-NA
    format. normalise_permits_plate (uppercase + trim) is correct here.

    BIKE permits: excluded in SQL via PNA.PNA_SERIES_PREFIX != 'BIKE'.
    SERIES_PREFIX is returned by the query and stored on the holder for
    reference, but the SQL-level filter is the authoritative exclusion.
    """
    rows = await _call_query(settings.t2_flex_query_permits)
    holders: list[PermitHolder] = []

    for row in rows:
        raw_plates = str(row.get("LICENSE_PLATES") or "").strip()
        plates = _expand_plates(raw_plates)
        if not plates:
            continue
        holders.append(PermitHolder(
            entity_uid=str(row.get("ENT_UID") or ""),
            email=str(row.get("EMAIL_ADDRESS") or "").strip() or None,
            series_prefix=str(row.get("SERIES_PREFIX") or "").strip().upper(),
            permit_number=str(row.get("PERMIT_NUMBER") or "").strip(),
            plates=plates,
        ))

    logger.info("_fetch_permits_live: %d permit holders loaded", len(holders))
    return holders


async def _fetch_citations_live(year: int, month: int) -> list[Citation]:
    """
    Fetch citations for the given month from T2 Flex web services (UBCO zone).

    CON_SNAP_VEH_PLATE_LICENSE is the plate as recorded at citation time —
    no VEHICLE join needed. Plates come back as plain strings.

    YEAR and MONTH are passed as plain integers to avoid T2 Flex Alpha-type
    validation errors that reject hyphens in date strings.
    """
    rows = await _call_query(
        settings.t2_flex_query_citations,
        params={"YEAR": str(year), "MONTH": str(month)},
    )

    plates: set[str] = set()
    for row in rows:
        plate = normalise_permits_plate(str(row.get("LICENSE_PLATE") or ""))
        if plate:
            plates.add(plate)

    logger.info(
        "_fetch_citations_live(%d-%02d): %d cited plates from %d rows",
        year, month, len(plates), len(rows),
    )
    return [Citation(plate=p) for p in plates]


# ---------------------------------------------------------------------------
# Stub loaders (unchanged — used when USE_STUBS=true)
# ---------------------------------------------------------------------------

def _load_citations_from_file(year: int, month: int) -> list[Citation]:
    stub_dir = Path(settings.stub_data_dir)
    candidates = (
        sorted(stub_dir.glob("*Citation*.xls"))
        + sorted(stub_dir.glob("*citation*.xls"))
        + sorted(stub_dir.glob("*Citation*.xlsx"))
    )
    if not candidates:
        return []

    path = candidates[0]
    engine = "xlrd" if path.suffix.lower() == ".xls" else "openpyxl"
    df = pd.read_excel(path, engine=engine, header=9)
    df.columns = df.columns.str.strip()

    plate_col = next(
        (c for c in df.columns if "license #" in c.lower() or "licence #" in c.lower() or "license" in c.lower()),
        None,
    )
    if not plate_col:
        return []

    plates = df[plate_col].apply(normalise_citations_plate)
    plates = plates[plates != ""].drop_duplicates()
    return [Citation(plate=p) for p in plates]


def _load_permits_from_file() -> list[PermitHolder]:
    stub_dir = Path(settings.stub_data_dir)
    candidates = sorted(stub_dir.glob("*Permit*.txt")) + sorted(stub_dir.glob("*permit*.txt"))
    if not candidates:
        return []

    path = candidates[0]
    df = pd.read_csv(path, dtype=str, sep=",", quotechar='"', on_bad_lines="skip")
    df.columns = df.columns.str.strip()

    col_email  = next((c for c in df.columns if "email" in c.lower()), None)
    col_series = next((c for c in df.columns if "series" in c.lower()), None)
    col_permit = next((c for c in df.columns if "permit" in c.lower() and "series" not in c.lower()), None)
    col_plates = next((c for c in df.columns if "plate" in c.lower()), None)
    col_uid    = next((c for c in df.columns if "uid" in c.lower() or "ent" in c.lower()), None)

    if not col_plates:
        return []

    holders: list[PermitHolder] = []
    for _, row in df.iterrows():
        raw_plates = str(row.get(col_plates, "") or "").strip()
        plates = _expand_plates(raw_plates)
        if not plates:
            continue
        holders.append(PermitHolder(
            entity_uid=str(row.get(col_uid, "") or "").strip(),
            email=str(row.get(col_email, "") or "").strip() or None,
            series_prefix=str(row.get(col_series, "") or "").strip().upper(),
            permit_number=str(row.get(col_permit, "") or "").strip(),
            plates=plates,
        ))
    return holders


def _expand_plates(raw: str) -> list[str]:
    """
    Handle both single-plate and multi-plate formats:
      single: SK041H
      multi:  "674PRL,TC765L"  (quoted comma-separated)
    """
    raw = raw.strip().strip('"')
    return [
        normalise_permits_plate(p)
        for p in re.split(r"[,;]+", raw)
        if normalise_permits_plate(p)
    ]
