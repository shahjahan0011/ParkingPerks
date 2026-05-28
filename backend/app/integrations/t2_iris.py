"""
T2 Iris -- SOAP payments client.

Uses getTransactionByPurchasedDate on TransactionInfoService.

SOAP endpoint:
    WSDL: {T2_IRIS_BASE_URL}/TransactionInfoService?wsdl
    Endpoint: https://iris.digitalpaytech.com/services/TransactionInfoService

Auth -- two layers required:
    1. WS-Security UsernameToken (T2_IRIS_USERNAME + T2_IRIS_PASSWORD)
       Attached as a SOAP security header by zeep at the transport level.
    2. token parameter (T2_IRIS_TOKEN) passed as a method argument.
       Use a TransactionInfo token from Iris API - Read settings.

Config (.env):
    T2_IRIS_BASE_URL  -- base URL (default: https://iris.digitalpaytech.com/services)
    T2_IRIS_USERNAME  -- Iris portal login email
    T2_IRIS_PASSWORD  -- Iris portal password
    T2_IRIS_TOKEN     -- TransactionInfo token from Iris API - Read section

Stub mode (USE_STUBS_PAYMENTS=true):
    Loads plates from test-data/*Payment*.csv.
    The CSV format uses Excel formula quoting (="SK041H") -- normalise_payments_plate
    is used for the file path only. Live API returns plain strings.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.config import settings
from app.core.normalise import normalise_payments_plate, normalise_reads_plate
from app.integrations.base import Payment, PaymentsClient

logger = logging.getLogger(__name__)

_iris_client = None


def _get_iris_client():
    """
    Return (and cache) a zeep SOAP client for TransactionInfoService.

    Authentication requires both:
    - WS-Security UsernameToken header (username + password)
    - token parameter per method call
    """
    global _iris_client
    if _iris_client is None:
        try:
            from zeep import Client
            from zeep.wsse.username import UsernameToken
        except ImportError as exc:
            raise RuntimeError(
                "zeep is required for the T2 Iris live client. Run: pip install zeep"
            ) from exc

        if not settings.t2_iris_username or not settings.t2_iris_password:
            raise RuntimeError(
                "T2_IRIS_USERNAME and T2_IRIS_PASSWORD must be set in .env. "
                "Use your Iris portal login credentials."
            )

        wsdl = f"{settings.t2_iris_base_url.rstrip('/')}/TransactionInfoService?wsdl"
        logger.info("Initialising T2 Iris SOAP client from WSDL: %s", wsdl)
        wsse = UsernameToken(settings.t2_iris_username, settings.t2_iris_password)
        _iris_client = Client(wsdl, wsse=wsse)

    return _iris_client


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class T2IrisClient(PaymentsClient):

    async def fetch_payments(self, year: int, month: int) -> list[Payment]:
        if settings.use_stubs_payments:
            return _load_payments_from_file(year, month)
        return await _fetch_payments_live(year, month)


# ---------------------------------------------------------------------------
# Live -- single SOAP call for the full month
# ---------------------------------------------------------------------------

async def _fetch_payments_live(year: int, month: int) -> list[Payment]:
    """
    Fetch all payment plates for the given month.

    getTransactionByPurchasedDate has no 24-hour window limit so the full
    month is fetched in a single call.
    """
    if not settings.t2_iris_token:
        raise RuntimeError(
            "T2_IRIS_TOKEN is not set in .env. "
            "Add a TransactionInfo token from Iris API - Read settings."
        )

    num_days = calendar.monthrange(year, month)[1]
    from_dt = datetime(year, month, 1, 0, 0, 0)
    to_dt   = datetime(year, month, num_days, 23, 59, 59)

    rows = await asyncio.to_thread(_call_get_transactions, from_dt, to_dt)

    plates: set[str] = set()
    for row in rows:
        plate = _extract_plate(row)
        if plate:
            plates.add(plate)

    logger.info(
        "_fetch_payments_live(%d-%02d): %d unique plates from %d total rows",
        year, month, len(plates), len(rows),
    )
    return [Payment(plate=p) for p in plates]


def _call_get_transactions(from_dt: datetime, to_dt: datetime) -> list:
    """Synchronous zeep call -- run via asyncio.to_thread()."""
    client = _get_iris_client()
    result = client.service.getTransactionByPurchasedDate(
        token=settings.t2_iris_token,
        purchasedDateFrom=from_dt,
        purchasedDateTo=to_dt,
    )

    if result is None:
        return []
    if isinstance(result, list):
        return result

    for attr in ("TransactionInfo", "item", "return", "result"):
        inner = getattr(result, attr, None)
        if inner is not None:
            return list(inner) if hasattr(inner, "__iter__") else [inner]

    return list(result) if hasattr(result, "__iter__") else [result]


def _extract_plate(row) -> str:
    """
    Extract and normalise a plate from a zeep TransactionInfo object.
    Live API returns plain strings -- use normalise_reads_plate (uppercase + trim).
    Rows with no plate or zero charge are discarded.
    """
    plate_raw = getattr(row, "plateNumber", None)
    if plate_raw is None and hasattr(row, "get"):
        plate_raw = row.get("plateNumber")

    charged = getattr(row, "chargedAmount", None)
    if charged is None and hasattr(row, "get"):
        charged = row.get("chargedAmount")

    if not plate_raw:
        return ""

    try:
        if float(charged or 0) <= 0:
            return ""
    except (TypeError, ValueError):
        pass

    return normalise_reads_plate(str(plate_raw))


# ---------------------------------------------------------------------------
# Stub loader -- CSV file path (Excel formula-quoted plates)
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
