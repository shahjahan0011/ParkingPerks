"""
Genetec Security Center — plate reads client.

STUB: Returns data loaded from the local test-data XLSX file.
Replace the body of GenetecClient with real HTTP calls once the
Genetec REST API credentials and endpoint documentation are available.

Expected Genetec API shape (to be confirmed):
  GET /api/v1/lpr/reads?from=<ISO>&to=<ISO>
  Response: [{ "plate": "SK041H", "timestamp": "2026-04-15T09:14:32-07:00" }, ...]
"""

from __future__ import annotations

import pandas as pd

from app.config import settings
from app.core.normalise import normalise_reads_plate
from app.integrations.base import PlateRead, PlateReadsClient

import calendar
from datetime import datetime
from pathlib import Path


class GenetecClient(PlateReadsClient):
    """
    Real implementation stub — replace with httpx calls to Genetec REST API.

    When USE_STUBS=false, this class must be reimplemented to call:
      GET {GENETEC_BASE_URL}/api/v1/lpr/reads?from=...&to=...
    with Bearer token auth using GENETEC_USERNAME + GENETEC_PASSWORD.
    """

    async def fetch_reads(self, year: int, month: int) -> list[PlateRead]:
        if settings.use_stubs:
            return _load_reads_from_file(year, month)
        raise NotImplementedError(
            "Genetec live client not yet implemented. Set USE_STUBS=true "
            "or implement HTTP calls using GENETEC_BASE_URL / credentials."
        )


# ---------------------------------------------------------------------------
# Stub loader — reads the same XLSX the MVP uses
# ---------------------------------------------------------------------------

def _load_reads_from_file(year: int, month: int) -> list[PlateRead]:
    stub_dir = Path(settings.stub_data_dir)
    candidates = sorted(stub_dir.glob("*Plate*Reads*.xlsx")) + sorted(stub_dir.glob("*plate*reads*.xlsx"))

    if not candidates:
        return []

    path = candidates[0]
    df = pd.read_excel(path, header=1, engine="openpyxl")
    df.columns = df.columns.str.strip()

    time_col  = next((c for c in df.columns if "local time" in c.lower()), None)
    plate_col = next((c for c in df.columns if "plate number" in c.lower() or c.lower() == "plate"), None)

    if not time_col or not plate_col:
        return []

    df = df.rename(columns={time_col: "ts", plate_col: "plate_raw"})
    df["plate"] = df["plate_raw"].apply(normalise_reads_plate)
    df = df[df["plate"].notna() & (df["plate"] != "") & (df["plate"] != "-")]

    df["ts"] = pd.to_datetime(df["ts"], format="%m/%d/%Y, %I:%M:%S %p", errors="coerce")
    df = df.dropna(subset=["ts"])
    df = df.drop_duplicates(subset=["plate", "ts"], keep="first")

    return [
        PlateRead(plate=row["plate"], timestamp=row["ts"].to_pydatetime())
        for _, row in df.iterrows()
    ]
