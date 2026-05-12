"""
T2 Flex — citations and permit holders client.

STUB: Returns data loaded from local test-data files.
Replace with real T2 Flex REST API calls once endpoint docs are available.

Expected T2 Flex API shape (to be confirmed):
  GET /api/citations?month=2026-04
  Response: [{ "licensePlate": "BC-SK041H-NA", "date": "2026-04-10" }, ...]

  GET /api/permits/active
  Response: [{ "entityUid": "...", "email": "j.doe@ubc.ca", "seriesPrefix": "S",
               "permitNumber": "A1234", "licensePlates": ["SK041H", "674PRL"] }, ...]
"""

from __future__ import annotations

import re

import pandas as pd

from app.config import settings
from app.core.normalise import normalise_citations_plate, normalise_permits_plate
from app.integrations.base import Citation, CitationsAndPermitsClient, PermitHolder
from pathlib import Path


class T2FlexClient(CitationsAndPermitsClient):
    """
    Real implementation stub — replace with httpx calls to T2 Flex API.

    When USE_STUBS=false, implement calls using:
      T2_FLEX_BASE_URL, T2_FLEX_CLIENT_ID, T2_FLEX_CLIENT_SECRET (OAuth2).
    """

    async def fetch_citations(self, year: int, month: int) -> list[Citation]:
        if settings.use_stubs:
            return _load_citations_from_file(year, month)
        raise NotImplementedError(
            "T2 Flex live client not yet implemented. Set USE_STUBS=true "
            "or implement HTTP calls using T2_FLEX_BASE_URL / credentials."
        )

    async def fetch_permits(self) -> list[PermitHolder]:
        if settings.use_stubs:
            return _load_permits_from_file()
        raise NotImplementedError(
            "T2 Flex live client not yet implemented. Set USE_STUBS=true "
            "or implement HTTP calls using T2_FLEX_BASE_URL / credentials."
        )


# ---------------------------------------------------------------------------
# Stub loaders
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

    col_email   = next((c for c in df.columns if "email" in c.lower()), None)
    col_series  = next((c for c in df.columns if "series" in c.lower()), None)
    col_permit  = next((c for c in df.columns if "permit" in c.lower() and "series" not in c.lower()), None)
    col_plates  = next((c for c in df.columns if "plate" in c.lower()), None)
    col_uid     = next((c for c in df.columns if "uid" in c.lower() or "ent" in c.lower()), None)

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
