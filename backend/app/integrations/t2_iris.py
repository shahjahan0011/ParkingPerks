"""
T2 Iris - payments client.

STUB: Returns data loaded from the local test-data CSV file.
Replace with real T2 Iris REST API calls once endpoint docs are available.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.config import settings
from app.core.normalise import normalise_payments_plate
from app.integrations.base import Payment, PaymentsClient


class T2IrisClient(PaymentsClient):
    """
    Real implementation stub - replace with httpx calls to T2 Iris API.

    When USE_STUBS_PAYMENTS=false, implement:
      GET {T2_IRIS_BASE_URL}/transactions with T2_IRIS_API_KEY header.
    """

    async def fetch_payments(self, year: int, month: int) -> list[Payment]:
        if settings.use_stubs_payments:
            return _load_payments_from_file(year, month)
        raise NotImplementedError(
            "T2 Iris live client not yet implemented. Set USE_STUBS_PAYMENTS=true "
            "or implement HTTP calls using T2_IRIS_BASE_URL / T2_IRIS_API_KEY."
        )


# ---------------------------------------------------------------------------
# Stub loader
# ---------------------------------------------------------------------------

def _load_payments_from_file(year: int, month: int) -> list[Payment]:
    stub_dir = Path(settings.stub_data_dir)
    candidates = (
        sorted(stub_dir.glob("*Payment*.csv"))
        + sorted(stub_dir.glob("*payment*.csv"))
    )

    if not candidates:
        return []

    path = candidates[0]
    df = pd.read_csv(path, dtype=str)
    df.columns = df.columns.str.strip()

    plate_col = next(
        (c for c in df.columns if "license plate" in c.lower() or "licence plate" in c.lower()),
        None,
    )
    if not plate_col:
        return []

    plates = df[plate_col].apply(normalise_payments_plate)
    plates = plates[plates != ""].drop_duplicates()
    return [Payment(plate=p) for p in plates]
