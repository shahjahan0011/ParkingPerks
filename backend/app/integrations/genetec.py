"""
Genetec Security Center - plate reads client.

STUB: Returns data loaded from a local .xlsx file.
Priority order:
  1. uploads/plate_reads.xlsx  (staff-uploaded via /api/upload/reads)
  2. test-data/*Plate*Reads*.xlsx (fallback for development)

Replace with real Genetec REST API calls once credentials are available.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.config import settings
from app.core.normalise import normalise_reads_plate
from app.integrations.base import PlateRead, PlateReadsClient


class GenetecClient(PlateReadsClient):
    async def fetch_reads(self, year: int, month: int) -> list[PlateRead]:
        if settings.use_stubs_reads:
            return _load_reads_from_file(year, month)
        raise NotImplementedError(
            "Genetec live client not yet implemented. "
            "Set USE_STUBS_READS=true or implement real HTTP calls."
        )


def _load_reads_from_file(year: int, month: int) -> list[PlateRead]:
    # 1. Staff-uploaded file takes priority
    uploads_dir = Path(settings.uploads_dir)
    candidates = sorted(uploads_dir.glob("plate_reads.xlsx"))

    # 2. Fall back to test-data
    if not candidates:
        stub_dir = Path(settings.stub_data_dir)
        candidates = (
            sorted(stub_dir.glob("*Plate*Reads*.xlsx"))
            + sorted(stub_dir.glob("*plate*reads*.xlsx"))
        )

    if not candidates:
        return []

    path = candidates[0]
    df = pd.read_excel(path, header=1, engine="openpyxl")
    df.columns = df.columns.str.strip()

    time_col  = next((c for c in df.columns if "local time" in c.lower()), None)
    plate_col = next(
        (c for c in df.columns if "plate number" in c.lower() or c.lower() == "plate"),
        None,
    )

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
