"""
Pull the daily Genetec reads-report emails from Gmail and load their .xlsx
attachments into reads.db.

Why mail instead of the Data Exporter push: the exporter throttles at
20 reads/second and silently drops the excess unless the licence tier with
queueing is purchased. Genetec's scheduled report (daily, ~12am, "last day")
has no such limit, and the monthly report is too big for email -- hence daily.

Flow (runs at the start of every monthly_run invocation, i.e. daily):
    1. Gmail search: settings.gmail_report_query AND NOT label:pperks-processed
    2. For each message: download .xlsx attachments -> parse with the SAME
       auto-detecting parser used for manual uploads -> insert into reads.db
       (UNIQUE(plate, ts) dedupes the 24h-window overlaps between reports)
    3. Label the message pperks-processed (failures stay unlabelled and are
       retried on the next run)

Uses the same Gmail OAuth credentials as the sender (gmail.modify scope
covers reading, labelling AND sending).
"""

from __future__ import annotations

import base64
import logging
import tempfile
from pathlib import Path

import httpx

from app.config import settings
from app.email.sender import _gmail_access_token
from app.store import reads_db

logger = logging.getLogger(__name__)

_API = "https://gmail.googleapis.com/gmail/v1/users/me"
PROCESSED_LABEL = "pperks-processed"


def pull_reads_reports() -> dict:
    """Fetch and ingest all unprocessed report emails. Returns stats.
    Raises on auth/connectivity failure (callers decide how fatal that is)."""
    stats = {"messages": 0, "attachments": 0, "new_reads": 0, "failures": 0}

    token = _gmail_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    with httpx.Client(headers=headers, timeout=120) as client:
        label_id = _ensure_label(client)
        query = f"({settings.gmail_report_query}) -label:{PROCESSED_LABEL}"
        message_ids = _search(client, query)
        logger.info("Mail pull: %d unprocessed report email(s)", len(message_ids))

        for mid in message_ids:
            try:
                new_reads, n_atts = _process_message(client, mid)
                stats["messages"] += 1
                stats["attachments"] += n_atts
                stats["new_reads"] += new_reads
                # Mark processed only after successful ingestion.
                client.post(f"{_API}/messages/{mid}/modify",
                            json={"addLabelIds": [label_id]}).raise_for_status()
            except Exception as exc:
                stats["failures"] += 1
                logger.warning("Mail pull: message %s failed (will retry next "
                               "run): %s", mid, exc)

    logger.info("Mail pull: %(messages)d emails, %(attachments)d attachments, "
                "%(new_reads)d new reads, %(failures)d failures", stats)
    return stats


def _search(client: httpx.Client, query: str) -> list[str]:
    ids: list[str] = []
    page_token = None
    while True:
        params = {"q": query, "maxResults": 100}
        if page_token:
            params["pageToken"] = page_token
        resp = client.get(f"{_API}/messages", params=params)
        resp.raise_for_status()
        data = resp.json()
        ids.extend(m["id"] for m in data.get("messages", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            return ids


def _ensure_label(client: httpx.Client) -> str:
    resp = client.get(f"{_API}/labels")
    resp.raise_for_status()
    for label in resp.json().get("labels", []):
        if label["name"] == PROCESSED_LABEL:
            return label["id"]
    resp = client.post(f"{_API}/labels", json={
        "name": PROCESSED_LABEL,
        "labelListVisibility": "labelShow",
        "messageListVisibility": "show",
    })
    resp.raise_for_status()
    return resp.json()["id"]


def _process_message(client: httpx.Client, message_id: str) -> tuple[int, int]:
    """Download + ingest every .xlsx attachment. Returns (new_reads, n_attachments)."""
    resp = client.get(f"{_API}/messages/{message_id}", params={"format": "full"})
    resp.raise_for_status()
    msg = resp.json()

    attachments = _find_xlsx_attachments(msg.get("payload", {}))
    if not attachments:
        logger.info("Mail pull: message %s has no .xlsx attachment -- labelling "
                    "as processed anyway", message_id)
        return 0, 0

    total_new = 0
    for filename, attachment_id in attachments:
        resp = client.get(
            f"{_API}/messages/{message_id}/attachments/{attachment_id}")
        resp.raise_for_status()
        content = base64.urlsafe_b64decode(resp.json()["data"])
        new = ingest_report_bytes(content, filename)
        total_new += new
        logger.info("Mail pull: %s -> %d new reads", filename, new)

    return total_new, len(attachments)


def _find_xlsx_attachments(payload: dict) -> list[tuple[str, str]]:
    """Walk the MIME tree for .xlsx attachments -> [(filename, attachmentId)]."""
    found: list[tuple[str, str]] = []

    def walk(part: dict) -> None:
        filename = (part.get("filename") or "").strip()
        body = part.get("body", {})
        if filename.lower().endswith(".xlsx") and body.get("attachmentId"):
            found.append((filename, body["attachmentId"]))
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    return found


def ingest_report_bytes(content: bytes, filename: str) -> int:
    """Parse a reads-report .xlsx (bytes) and insert into reads.db.
    Returns the number of NEW reads stored (overlaps dedupe to zero)."""
    from app.integrations.genetec import _parse_reads_file

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        df = _parse_reads_file(tmp_path)
        rows = [
            (row.plate, row.ts.strftime("%Y-%m-%d %H:%M:%S"), "")
            for row in df.itertuples()
        ]
        return reads_db.insert_reads(rows)
    finally:
        tmp_path.unlink(missing_ok=True)
