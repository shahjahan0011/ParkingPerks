"""Tests for the Gmail daily-report ingestion path."""

from datetime import datetime
from io import BytesIO

import pytest
from openpyxl import Workbook

from app.integrations.mail_reports import _find_xlsx_attachments, ingest_report_bytes
from app.store import csv_store, reads_db


@pytest.fixture(autouse=True)
def isolated_dbs(tmp_path, monkeypatch):
    monkeypatch.setattr(reads_db, "_db_path", lambda: tmp_path / "reads.db")
    monkeypatch.setattr(csv_store, "_data_dir", lambda: tmp_path / "data")
    yield


def _daily_report_bytes(rows) -> bytes:
    """Mimic the REAL daily report shape: leading empty column, 7 metadata
    rows, header on row 8, datetime timestamps with milliseconds."""
    wb = Workbook()
    ws = wb.active
    ws.append([None, "Report: DailyReadsReport-ParkingPerks"])
    ws.append([None, "User: jshah04"])
    ws.append([None, "Date: 6/11/2026 3:13:02 PM"])
    ws.append([None, "Number of query results returned: %d" % len(rows)])
    ws.append([None, "Generated a hit: False"])
    ws.append([None, "Event timestamp: During the last 1 day"])
    ws.append([None])
    ws.append([None, "Plate read", "Address", "Patroller", "ALPR unit",
               "User", "Read timestamp", "Speed"])
    for plate, dt in rows:
        ws.append([None, plate, None, None, "Univ Way Exit", None, dt, "-"])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestFindAttachments:
    def test_nested_mime_tree(self):
        payload = {
            "filename": "", "body": {},
            "parts": [
                {"filename": "", "body": {}, "parts": [
                    {"filename": "report.XLSX", "body": {"attachmentId": "att1"}},
                    {"filename": "logo.png", "body": {"attachmentId": "att2"}},
                ]},
                {"filename": "another.xlsx", "body": {"attachmentId": "att3"}},
                {"filename": "noid.xlsx", "body": {}},
            ],
        }
        found = _find_xlsx_attachments(payload)
        assert found == [("report.XLSX", "att1"), ("another.xlsx", "att3")]

    def test_empty_payload(self):
        assert _find_xlsx_attachments({}) == []


class TestIngestReportBytes:
    def test_real_daily_report_shape(self):
        content = _daily_report_bytes([
            ("RM876S", datetime(2026, 6, 10, 15, 13, 7, 675000)),
            ("SM300F", datetime(2026, 6, 10, 23, 58, 8, 300000)),
        ])
        new = ingest_report_bytes(content, "DailyReadsReport.xlsx")
        assert new == 2
        rows = reads_db.month_reads(2026, 6)
        assert rows[0][0] == "RM876S"
        # milliseconds truncated to seconds; late-evening date NOT shifted
        assert rows[1][1] == datetime(2026, 6, 10, 23, 58, 8)

    def test_overlapping_reports_dedupe(self):
        day = [("AB123C", datetime(2026, 6, 10, 12, 0, 0))]
        assert ingest_report_bytes(_daily_report_bytes(day), "a.xlsx") == 1
        # The next day's report overlaps the same window -> zero new
        assert ingest_report_bytes(_daily_report_bytes(day), "b.xlsx") == 0

    def test_garbage_attachment_raises(self):
        with pytest.raises(Exception):
            ingest_report_bytes(b"this is not an xlsx file", "junk.xlsx")
