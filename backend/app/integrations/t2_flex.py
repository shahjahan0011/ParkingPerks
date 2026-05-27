"""
T2 Flex — SOAP web services client.

Uses the ExecuteQuery() method on T2_Flex_Misc.asmx to run registered
queries from T2 Flex Query Manager.

SOAP endpoint:
    POST {T2_FLEX_WS_URL}
    SOAPAction: http://www.t2systems.com/ExecuteQuery
    Content-Type: text/xml; charset=utf-8

Config (.env):
    T2_FLEX_WS_URL               — full URL to T2_Flex_Misc.asmx
    T2_FLEX_USERNAME / PASSWORD  — web services account
    T2_FLEX_QUERY_PERMITS_UID    — UID of permits query in T2 Flex Query Manager
    T2_FLEX_QUERY_CITATIONS_UID  — UID of citations query in T2 Flex Query Manager

Stub mode (USE_STUBS=true):
    Permits  — loaded from test-data/*.txt
    Citations — returns EMPTY LIST (see note below)

NOTE ON CITATIONS STUB:
    The test-data Citations file is a UBC Vancouver export. The live T2 Flex
    citations query filters CZL_UID_ZONE = 2001 (UBCO campus only). Using
    Vancouver data in stub mode would wrongly disqualify UBCO parkers who
    happened to have a citation at the Vancouver campus — exactly the
    geographic bias this system must avoid.

    Stub mode therefore returns zero citations (no disqualifications).
    To test citation-disqualification logic, create a file named
    test-data/Citations_UBCO.xls with real UBCO citation data.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
import pandas as pd

from app.config import settings
from app.core.normalise import normalise_citations_plate, normalise_permits_plate
from app.integrations.base import Citation, CitationsAndPermitsClient, PermitHolder

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SOAP templates
# ---------------------------------------------------------------------------

_SOAP_ENVELOPE = """\
<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:t2s="http://www.t2systems.com/">
  <soapenv:Header/>
  <soapenv:Body>
    <t2s:ExecuteQuery>
      <t2s:version>1.0</t2s:version>
      <t2s:username>{username}</t2s:username>
      <t2s:password>{password}</t2s:password>
      <t2s:queryUID>{query_uid}</t2s:queryUID>
      <t2s:queryParameters>{params_xml}</t2s:queryParameters>
    </t2s:ExecuteQuery>
  </soapenv:Body>
</soapenv:Envelope>"""

_PARAM_ELEMENT = (
    "<t2s:QueryParameter>"
    "<t2s:Field>{field}</t2s:Field>"
    "<t2s:Value>{value}</t2s:Value>"
    "</t2s:QueryParameter>"
)


def _build_envelope(query_uid: int, params: dict[str, str] | None = None) -> str:
    params_xml = "".join(
        _PARAM_ELEMENT.format(field=k, value=v)
        for k, v in (params or {}).items()
    )
    return _SOAP_ENVELOPE.format(
        username=settings.t2_flex_username,
        password=settings.t2_flex_password,
        query_uid=query_uid,
        params_xml=params_xml,
    )


def _parse_response(xml_text: str) -> list[dict]:
    """
    Extract rows from a T2 Flex ExecuteQuery SOAP response.

    The result element contains CDATA with:
        <QUERY_DATASET><RECORD><COL>val</COL>...</RECORD>...</QUERY_DATASET>
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(f"T2 Flex returned non-XML: {xml_text[:200]}") from exc

    result_el = root.find(".//{http://www.t2systems.com/}ExecuteQueryResult")
    if result_el is None:
        result_el = root.find(".//ExecuteQueryResult")

    if result_el is None:
        raise RuntimeError(f"ExecuteQueryResult not found in response: {xml_text[:400]}")

    cdata = (result_el.text or "").strip()
    if not cdata:
        logger.warning("T2 Flex ExecuteQueryResult is empty")
        return []

    if "<T2ErrorList>" in cdata or "<ErrorNumber>" in cdata:
        raise RuntimeError(f"T2 Flex returned error: {cdata[:400]}")

    try:
        dataset = ET.fromstring(cdata)
    except ET.ParseError as exc:
        raise RuntimeError(f"Could not parse QUERY_DATASET: {cdata[:200]}") from exc

    rows = []
    for record in dataset.findall("RECORD"):
        row = {child.tag: (child.text or "").strip() for child in record}
        rows.append(row)

    logger.info("T2 Flex query returned %d records", len(rows))
    return rows


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class T2FlexClient(CitationsAndPermitsClient):

    async def fetch_citations(self, year: int, month: int) -> list[Citation]:
        if settings.use_stubs:
            return _load_citations_stub(year, month)
        return await _fetch_citations_live(year, month)

    async def fetch_permits(self) -> list[PermitHolder]:
        if settings.use_stubs:
            return _load_permits_from_file()
        return await _fetch_permits_live()


# ---------------------------------------------------------------------------
# Live — SOAP calls
# ---------------------------------------------------------------------------

async def _call_query(query_uid: int, params: dict[str, str] | None = None) -> list[dict]:
    ws_url = settings.t2_flex_ws_url.strip()
    if not ws_url:
        raise RuntimeError(
            "T2_FLEX_WS_URL is not set in .env. "
            "It should point to T2_Flex_Misc.asmx, e.g. "
            "https://ubcparking.t2flex.ca/PowerParkWS/T2_Flex_Misc.asmx"
        )

    envelope = _build_envelope(query_uid, params)
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://www.t2systems.com/ExecuteQuery",
    }

    logger.info("T2 Flex SOAP → queryUID=%d params=%s", query_uid, params)

    async with httpx.AsyncClient(
        verify=settings.t2_flex_verify_ssl,
        timeout=settings.t2_flex_timeout,
    ) as client:
        resp = await client.post(ws_url, content=envelope.encode("utf-8"), headers=headers)
        resp.raise_for_status()

    return _parse_response(resp.text)


async def _fetch_permits_live() -> list[PermitHolder]:
    """
    Fetch active permit holders from T2 Flex.

    The SQL query uses LISTAGG so multiple plates per person are returned as
    a comma-separated string. _expand_plates() splits and normalises them.
    Plates are plain strings (e.g. SK041H) — use normalise_permits_plate.
    BIKE permits are excluded at the SQL level (PNA_SERIES_PREFIX != 'BIKE').
    """
    rows = await _call_query(settings.t2_flex_query_permits_uid)
    holders: list[PermitHolder] = []

    for row in rows:
        raw_plates = str(row.get("LICENSE_PLATES") or "").strip()
        plates = _expand_plates(raw_plates)
        if not plates:
            continue
        holders.append(PermitHolder(
            entity_uid=str(row.get("ENT_UID") or "").strip(),
            email=str(row.get("EMAIL_ADDRESS") or "").strip() or None,
            series_prefix=str(row.get("SERIES_PREFIX") or "").strip().upper(),
            permit_number=str(row.get("PERMIT_NUMBER") or "").strip(),
            plates=plates,
        ))

    logger.info("_fetch_permits_live: %d permit holders loaded", len(holders))
    return holders


async def _fetch_citations_live(year: int, month: int) -> list[Citation]:
    """
    Fetch UBCO-zone citations for the given month from T2 Flex.

    The SQL filters CZL_UID_ZONE = 2001 (UBCO campus only).
    CON_SNAP_VEH_PLATE_LICENSE is the plate as it appeared at citation time.
    Live plates are plain strings — use normalise_permits_plate (uppercase + trim).
    """
    rows = await _call_query(
        settings.t2_flex_query_citations_uid,
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
# Stub loaders
# ---------------------------------------------------------------------------

def _load_citations_stub(year: int, month: int) -> list[Citation]:
    """
    Stub citations loader.

    The available test-data citations file is a UBC VANCOUVER export and must
    NOT be used as UBCO stub data — it would wrongly disqualify UBCO parkers
    with Vancouver citations (291 plates affected in the April 2026 sample).

    We look for a UBCO-specific file first. If not found, we return empty
    (no disqualifications in stub mode), which matches the expected live
    behaviour where very few UBCO citations occur each month.

    To test citation disqualification: place a file named
    "Citations_UBCO.xls" or "Citations_UBCO.xlsx" in test-data/ containing
    only UBCO campus citations.
    """
    stub_dir = Path(settings.stub_data_dir)

    # Only load a file explicitly labelled as UBCO to avoid the campus-mix bug
    candidates = (
        sorted(stub_dir.glob("*Citations_UBCO*.xls"))
        + sorted(stub_dir.glob("*Citations_UBCO*.xlsx"))
        + sorted(stub_dir.glob("*Citations_UBCO*.csv"))
    )

    if not candidates:
        logger.warning(
            "Citations stub: no UBCO-specific citations file found in %s. "
            "Returning 0 citations. This is correct for UBCO-only scope. "
            "To test citation disqualification, add test-data/Citations_UBCO.xls.",
            stub_dir,
        )
        return []

    path = candidates[0]
    logger.info("Citations stub: loading UBCO citations from %s", path)

    engine = "xlrd" if path.suffix.lower() == ".xls" else "openpyxl"
    try:
        df = pd.read_excel(path, engine=engine, header=9)
    except Exception:
        df = pd.read_excel(path, engine=engine)

    df.columns = df.columns.str.strip()
    plate_col = next(
        (c for c in df.columns if "license" in c.lower() or "licence" in c.lower()),
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
        series = str(row.get(col_series, "") or "").strip().upper()
        if series in {"BIKE"}:
            continue
        raw_plates = str(row.get(col_plates, "") or "").strip()
        plates = _expand_plates(raw_plates)
        if not plates:
            continue
        holders.append(PermitHolder(
            entity_uid=str(row.get(col_uid, "") or "").strip(),
            email=str(row.get(col_email, "") or "").strip() or None,
            series_prefix=series,
            permit_number=str(row.get(col_permit, "") or "").strip(),
            plates=plates,
        ))
    return holders


def _expand_plates(raw: str) -> list[str]:
    """
    Handle both single-plate and multi-plate (LISTAGG comma-separated) formats:
      single: SK041H
      multi:  "674PRL,TC765L"
    """
    raw = raw.strip().strip('"')
    return [
        normalise_permits_plate(p)
        for p in re.split(r"[,;]+", raw)
        if normalise_permits_plate(p)
    ]
