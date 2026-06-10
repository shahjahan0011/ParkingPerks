"""
Genetec Security Center - plate reads client.

There is no Genetec API in our licence tier. Plate reads come from a manual
monthly export that staff generate in Security Desk:

    Security Desk > Reads Report > Select All Cameras > Deselect LPR Cars
    > No Images > Generate and Save Report

The exported .xlsx is uploaded through the web UI (POST /api/upload/reads)
and read from uploads/plate_reads.xlsx.

TWO EXPORT FORMATS EXIST -- both auto-detected by header-row scan:

  | Format            | Header row | Plate column   | Time column      | Timestamps      |
  |-------------------|-----------|----------------|------------------|-----------------|
  | Old (Cloudrunner) | row 2     | "Plate number" | "Local time ..." | string          |
  | New (Genetec)     | row 7     | "Plate read"   | "Read timestamp" | Excel serial    |

CRITICAL (do not reintroduce the UTC bug): Excel serials and the string
timestamps both represent WALL-CLOCK campus time. They are parsed as naive
datetimes -- never converted through a timezone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from app.config import settings
from app.core.normalise import normalise_reads_plate
from app.integrations.base import PlateRead, PlateReadsClient

logger = logging.getLogger(__name__)

_PLATE_HEADERS = ("plate read", "plate number")
_TIME_HEADERS = ("read timestamp", "local time")
_HEADER_SCAN_ROWS = 12

# Parsing a 60 MB / 450k-row export is expensive. Cache the parsed result
# keyed by (path, size, mtime) so upload -> analyze -> draw parses ONCE.
_parse_cache: dict[str, pd.DataFrame] = {}


def _file_key(path: Path) -> str:
    st = path.stat()
    return f"{path.resolve()}:{st.st_size}:{st.st_mtime_ns}"


def _read_excel(path: Path, **kwargs) -> pd.DataFrame:
    """python-calamine (Rust) is ~20x faster than openpyxl on big exports.
    Fall back to openpyxl if calamine isn't installed."""
    try:
        import python_calamine  # noqa: F401
        return pd.read_excel(path, engine="calamine", **kwargs)
    except ImportError:
        logger.warning("python-calamine not installed -- falling back to slow "
                       "openpyxl parser. Run: pip install python-calamine")
        return pd.read_excel(path, engine="openpyxl", **kwargs)


class ReadsFileError(RuntimeError):
    """Raised when the uploaded reads file is missing, unreadable, or does not
    cover the requested month. The message is shown to office staff -- keep it
    human-readable and actionable."""


@dataclass
class ReadsFileInfo:
    path: str
    total_rows: int
    date_min: str  # YYYY-MM-DD
    date_max: str
    months_covered: list[str]  # ["2026-04", ...]


class GenetecClient(PlateReadsClient):
    async def fetch_reads(self, year: int, month: int) -> list[PlateRead]:
        path = _find_reads_file()
        if path is None:
            raise ReadsFileError(
                "No plate reads file has been uploaded. Export it from "
                "Security Desk (Reads Report > all cameras, no LPR cars, "
                "no images) and upload it in step 1."
            )
        df = _parse_reads_file(path)
        return _reads_for_month(df, year, month, source=path.name)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _find_reads_file() -> Path | None:
    uploaded = Path(settings.uploads_dir) / "plate_reads.xlsx"
    if uploaded.exists():
        return uploaded
    # Development fallback only
    stub_dir = Path(settings.stub_data_dir)
    for pattern in ("*Plate*Reads*.xlsx", "*plate*reads*.xlsx", "Reads_*.xlsx"):
        candidates = sorted(stub_dir.glob(pattern))
        if candidates:
            return candidates[0]
    return None


# ---------------------------------------------------------------------------
# Parsing -- format auto-detection
# ---------------------------------------------------------------------------

def _parse_reads_file(path: Path) -> pd.DataFrame:
    """Return a DataFrame with columns [plate, ts] (ts = naive local datetime).
    Cached: upload, analyze and draw all share one parse of the same file."""
    key = _file_key(path)
    if key in _parse_cache:
        return _parse_cache[key]

    df = _parse_reads_file_uncached(path)
    _parse_cache.clear()          # only ever one current file
    _parse_cache[key] = df
    return df


def _parse_reads_file_uncached(path: Path) -> pd.DataFrame:
    try:
        preview = _read_excel(path, header=None, nrows=_HEADER_SCAN_ROWS)
    except Exception as exc:
        raise ReadsFileError(
            f"Could not open '{path.name}' as an Excel file: {exc}"
        ) from exc

    header_row = None
    for i, row in preview.iterrows():
        cells = [str(c).strip().lower() for c in row.tolist()]
        if any(h in cells for h in _PLATE_HEADERS):
            header_row = i
            break

    if header_row is None:
        raise ReadsFileError(
            f"'{path.name}' does not look like a plate reads export -- no "
            f"'Plate read' or 'Plate number' column found in the first "
            f"{_HEADER_SCAN_ROWS} rows. Make sure you exported the Reads "
            "Report from Security Desk."
        )

    df = _read_excel(path, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    plate_col = _find_column(df, _PLATE_HEADERS)
    time_col = _find_column(df, _TIME_HEADERS)
    if plate_col is None or time_col is None:
        raise ReadsFileError(
            f"'{path.name}': found the header row but could not locate the "
            f"plate/time columns. Columns present: {list(df.columns)[:10]}"
        )

    df = df[[plate_col, time_col]].rename(columns={plate_col: "plate_raw", time_col: "ts_raw"})
    df["plate"] = df["plate_raw"].apply(normalise_reads_plate)
    df = df[df["plate"].notna() & (df["plate"] != "") & (df["plate"] != "-")]

    df["ts"] = _parse_timestamps(df["ts_raw"])
    df = df.dropna(subset=["ts"])
    df = df.drop_duplicates(subset=["plate", "ts"], keep="first")

    if df.empty:
        raise ReadsFileError(
            f"'{path.name}' parsed but produced zero usable reads. "
            "The file may be empty or in an unexpected format."
        )

    return df[["plate", "ts"]].reset_index(drop=True)


def _find_column(df: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    for col in df.columns:
        low = str(col).strip().lower()
        if any(low == n or low.startswith(n) for n in names):
            return col
    return None


def _parse_timestamps(series: pd.Series) -> pd.Series:
    """
    Handle all three timestamp shapes WITHOUT timezone conversion:
      - Excel serial numbers (new Genetec export read as floats)
      - real datetimes (openpyxl converts date-formatted cells automatically)
      - strings "04/30/2026, 11:56:09 PM" (old Cloudrunner export)
    """
    if pd.api.types.is_numeric_dtype(series):
        # Excel serial day count, origin 1899-12-30. Wall-clock, no tz shift.
        return pd.to_datetime(series, unit="D", origin="1899-12-30", errors="coerce").dt.round("s")

    if pd.api.types.is_datetime64_any_dtype(series):
        return series

    # Object dtype: may be a mix. Try old-format string first, then general.
    parsed = pd.to_datetime(series, format="%m/%d/%Y, %I:%M:%S %p", errors="coerce")
    if parsed.isna().mean() > 0.5:
        parsed = pd.to_datetime(series, errors="coerce")
    return parsed


# ---------------------------------------------------------------------------
# Month filtering + coverage validation
# ---------------------------------------------------------------------------

def _reads_for_month(
    df: pd.DataFrame, year: int, month: int, source: str
) -> list[PlateRead]:
    in_month = df[(df["ts"].dt.year == year) & (df["ts"].dt.month == month)]

    if in_month.empty:
        d_min, d_max = df["ts"].min(), df["ts"].max()
        raise ReadsFileError(
            f"The uploaded reads file ('{source}') covers "
            f"{d_min:%Y-%m-%d} to {d_max:%Y-%m-%d}, but you selected "
            f"{year}-{month:02d}. Upload the export for the right month, "
            "or change the selected month."
        )

    dropped = len(df) - len(in_month)
    if dropped:
        logger.info(
            "Reads file: %d rows outside %d-%02d ignored (%d kept)",
            dropped, year, month, len(in_month),
        )

    return [
        PlateRead(plate=row.plate, timestamp=row.ts.to_pydatetime())
        for row in in_month.itertuples()
    ]


def inspect_reads_file(path: Path) -> ReadsFileInfo:
    """Parse a reads file and return coverage stats (used by the upload
    endpoint so staff immediately see whether they exported the right month)."""
    df = _parse_reads_file(path)
    months = sorted(df["ts"].dt.strftime("%Y-%m").unique().tolist())
    return ReadsFileInfo(
        path=str(path),
        total_rows=len(df),
        date_min=f"{df['ts'].min():%Y-%m-%d}",
        date_max=f"{df['ts'].max():%Y-%m-%d}",
        months_covered=months,
    )
