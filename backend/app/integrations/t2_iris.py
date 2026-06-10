"""
T2 Iris -- SOAP payments client (Digital Payment Technologies / Digital Iris).

Service: TransactionInfoService
    WSDL: {T2_IRIS_BASE_URL}/TransactionInfoService?wsdl
    Method: getTransactionByPurchasedDate(token, purchasedDateFrom,
            purchasedDateTo, version?)

Auth -- two layers, BOTH required (confirmed working 2026-05):
    1. WS-Security UsernameToken (T2_IRIS_USERNAME + T2_IRIS_PASSWORD)
       -- the Iris web portal login, attached as a SOAP security header.
    2. token parameter (T2_IRIS_TOKEN) -- a TransactionInfo token from
       Iris API - Read settings, passed as a method argument.

CONFIRMED API CONSTRAINTS (check_iris.py + compare_payments.py, 2026-06-10):
    - purchasedDateFrom/To MUST be within the same calendar day
      ("purchasedDateFrom and purchasedDateTo must be in same day").
      A month is therefore fetched as one call per day.
    - version='v1.2' is REQUIRED to get plateNumber in the response.
      Without it (or with v1.0) plateNumber is always None; v1.5 returns a
      schema zeep cannot parse (XMLParseError). Do not change from v1.2
      without re-running check_iris.py.
    - The API speaks UTC. Naive request datetimes are treated as UTC and
      purchasedDate comes back +00:00. The campus-local month (PDT/PST) is
      converted to its exact UTC interval and fetched as UTC day windows --
      otherwise reads after 5pm on the last local day are silently dropped
      (4 plates lost at the April boundary before this fix).
    - $0 transactions ARE valid payments (coupons / free periods). The
      payments report includes them; filtering on amount>0 wrongly removed
      446 of 5099 April plates. Keep every row that has a plateNumber.

Robustness:
    - Each day call retries once on a transient fault.
    - Connection errors produce a clear "check the internet connection"
      message instead of a stack trace.

Config (.env):
    T2_IRIS_BASE_URL, T2_IRIS_USERNAME, T2_IRIS_PASSWORD, T2_IRIS_TOKEN
    T2_IRIS_VERSION  -- 'version' method parameter, default v1.2.

Stub mode (USE_STUBS_PAYMENTS=true): loads plates from test-data/*Payment*.csv.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import pandas as pd

from app.config import settings
from app.core.normalise import normalise_iris_plate, normalise_payments_plate
from app.integrations.base import Payment, PaymentsClient

logger = logging.getLogger(__name__)

_iris_client = None


class PaymentsFetchError(RuntimeError):
    """Human-readable payments failure, shown to office staff."""


def _get_iris_client():
    """Return (and cache) a zeep SOAP client for TransactionInfoService."""
    global _iris_client
    if _iris_client is None:
        try:
            from zeep import Client
            from zeep.transports import Transport
            from zeep.wsse.username import UsernameToken
        except ImportError as exc:
            raise PaymentsFetchError(
                "The 'zeep' package is missing. Run: pip install zeep"
            ) from exc

        if not settings.t2_iris_username or not settings.t2_iris_password:
            raise PaymentsFetchError(
                "T2_IRIS_USERNAME / T2_IRIS_PASSWORD are not set in backend/.env "
                "(use the Iris portal login)."
            )
        if not settings.t2_iris_token:
            raise PaymentsFetchError(
                "T2_IRIS_TOKEN is not set in backend/.env "
                "(use a TransactionInfo token from Iris API - Read settings)."
            )

        wsdl = f"{settings.t2_iris_base_url.rstrip('/')}/TransactionInfoService?wsdl"
        logger.info("Initialising T2 Iris SOAP client from WSDL: %s", wsdl)
        try:
            _iris_client = Client(
                wsdl,
                wsse=UsernameToken(settings.t2_iris_username, settings.t2_iris_password),
                transport=Transport(operation_timeout=120, timeout=60),
            )
        except Exception as exc:
            raise PaymentsFetchError(
                f"Could not load the T2 Iris WSDL ({wsdl}). "
                f"Check the internet connection. Underlying error: {exc}"
            ) from exc

    return _iris_client


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class T2IrisClient(PaymentsClient):

    async def fetch_payments(self, year: int, month: int) -> list[Payment]:
        if settings.use_stubs_payments:
            return _load_payments_from_file(year, month)
        return await asyncio.to_thread(_fetch_payments_live, year, month)


# ---------------------------------------------------------------------------
# Live fetch -- the campus-local month, fetched as UTC day windows
# (API hard limits: same-UTC-day windows; datetimes interpreted as UTC)
# ---------------------------------------------------------------------------

def _month_utc_windows(year: int, month: int) -> list[tuple[datetime, datetime]]:
    """Convert the campus-local calendar month into a list of (from, to)
    naive-UTC windows, each within a single UTC calendar day."""
    tz = ZoneInfo(settings.campus_timezone)
    num_days = calendar.monthrange(year, month)[1]
    start_utc = (
        datetime(year, month, 1, 0, 0, 0, tzinfo=tz)
        .astimezone(timezone.utc).replace(tzinfo=None)
    )
    end_utc = (
        datetime(year, month, num_days, 23, 59, 59, tzinfo=tz)
        .astimezone(timezone.utc).replace(tzinfo=None)
    )

    windows: list[tuple[datetime, datetime]] = []
    day = start_utc.date()
    while day <= end_utc.date():
        win_start = max(datetime(day.year, day.month, day.day, 0, 0, 0), start_utc)
        win_end = min(datetime(day.year, day.month, day.day, 23, 59, 59), end_utc)
        windows.append((win_start, win_end))
        day += timedelta(days=1)
    return windows


def _fetch_payments_live(year: int, month: int) -> list[Payment]:
    rows: list = []
    for win_start, win_end in _month_utc_windows(year, month):
        rows.extend(_call_window(win_start, win_end))

    plates: set[str] = set()
    kept = 0
    for row in rows:
        plate = _extract_plate(row)
        if plate:
            kept += 1
            plates.add(plate)

    logger.info(
        "_fetch_payments_live(%d-%02d): %d rows -> %d valid payments -> %d unique plates",
        year, month, len(rows), kept, len(plates),
    )
    return [Payment(plate=p) for p in sorted(plates)]


def _call_window(from_dt: datetime, to_dt: datetime) -> list:
    """One getTransactionByPurchasedDate call (same-day window only --
    API constraint). Retries once on a transient fault, converts
    connection problems and faults to friendly messages."""
    client = _get_iris_client()

    kwargs: dict = {
        "token": settings.t2_iris_token,
        "purchasedDateFrom": from_dt,
        "purchasedDateTo": to_dt,
    }
    if settings.t2_iris_version:
        kwargs["version"] = settings.t2_iris_version

    for attempt in (1, 2):
        try:
            result = client.service.getTransactionByPurchasedDate(**kwargs)
            return _unwrap(result)
        except Exception as exc:
            if _is_connection_error(exc):
                raise PaymentsFetchError(
                    "Could not reach T2 Iris (iris.digitalpaytech.com). "
                    "Check the internet connection and try again."
                ) from exc
            if attempt == 1 and _is_retryable(exc):
                logger.warning("Transient Iris fault, retrying in 3s: %s", exc)
                time.sleep(3)
                continue
            raise PaymentsFetchError(
                f"T2 Iris rejected the query for {from_dt:%Y-%m-%d}: "
                f"{_fault_text(exc)}"
            ) from exc

    return []  # unreachable


def _unwrap(result) -> list:
    if result is None:
        return []
    if isinstance(result, list):
        return result
    for attr in ("transactionInfoTypes", "item", "return", "result"):
        inner = getattr(result, attr, None)
        if inner is not None:
            return list(inner) if hasattr(inner, "__iter__") else [inner]
    return list(result) if hasattr(result, "__iter__") else [result]


def _is_connection_error(exc: Exception) -> bool:
    import requests
    return isinstance(
        exc,
        (requests.exceptions.ConnectionError, requests.exceptions.Timeout, OSError),
    )


def _is_retryable(exc: Exception) -> bool:
    name = type(exc).__name__
    text = str(exc).lower()
    return "retry" in name.lower() or "retry" in text or "timeout" in text


def _fault_text(exc: Exception | None) -> str:
    """Pull shortErrorMessage/errCode out of an InfoServiceFault detail."""
    if exc is None:
        return "unknown"
    detail = getattr(exc, "detail", None)
    if detail is not None:
        try:
            parts = [
                el.text for el in detail.iter()
                if el.text and el.text.strip() and "}" in el.tag
            ]
            if parts:
                return " | ".join(p.strip() for p in parts)
        except Exception:
            pass
    return str(exc)


# ---------------------------------------------------------------------------
# Row -> plate
# ---------------------------------------------------------------------------

def _extract_plate(row) -> str:
    """
    Extract and normalise a plate from a TransactionInfoType.

    Every row with a plateNumber counts as a payment -- INCLUDING $0
    transactions (coupons / free periods). The payments report treats them
    as payments, and filtering on amount removed 446 of 5099 April plates
    (verified with compare_payments.py). Rows without a plate are useless
    for matching and are dropped.
    """
    plate_raw = _field(row, "plateNumber")
    if not plate_raw:
        return ""
    return normalise_iris_plate(str(plate_raw))


def _field(row, name):
    val = getattr(row, name, None)
    if val is None and hasattr(row, "get"):
        val = row.get(name)
    return val


def _to_float(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


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
