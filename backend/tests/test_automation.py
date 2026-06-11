"""
Tests for the automation layer:
- reads_db: insert/dedupe, month queries, coverage, retention, customer cache
- ingest endpoints: token issuance, bad creds, bearer enforcement, payload shapes
- GenetecClient source selection: feed vs uploaded file (best coverage wins)
- enrichment: cache behaviour, lookup failure tolerance
- monthly_run: idempotency, coverage gate, draw-once / email-retry separation
"""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from app.config import settings
from app.store import csv_store, reads_db


@pytest.fixture(autouse=True)
def isolated_dbs(tmp_path, monkeypatch):
    """Point reads.db and the csv store at a temp dir for every test."""
    monkeypatch.setattr(reads_db, "_db_path", lambda: tmp_path / "reads.db")
    monkeypatch.setattr(csv_store, "_data_dir", lambda: tmp_path / "data")
    (tmp_path / "data").mkdir()
    yield


# ---------------------------------------------------------------------------
# reads_db
# ---------------------------------------------------------------------------

class TestReadsDb:
    def test_insert_and_dedupe(self):
        rows = [("SK041H", "2026-05-10 09:00:00", "cam1"),
                ("SK041H", "2026-05-10 09:00:00", "cam2"),  # dual-camera dupe
                ("AB123C", "2026-05-10 09:00:00", "cam1")]
        assert reads_db.insert_reads(rows) == 2
        assert reads_db.insert_reads(rows) == 0  # idempotent re-delivery

    def test_month_reads_and_coverage(self):
        reads_db.insert_reads([
            ("SK041H", "2026-05-10 09:00:00", ""),
            ("SK041H", "2026-05-11 09:00:00", ""),
            ("ZZ999Z", "2026-06-01 00:05:00", ""),  # next month
        ])
        may = reads_db.month_reads(2026, 5)
        assert len(may) == 2
        assert all(isinstance(ts, datetime) for _, ts in may)
        assert reads_db.month_days_covered(2026, 5) == 2
        assert reads_db.month_days_covered(2026, 6) == 1

    def test_feed_stats_and_retention(self):
        reads_db.insert_reads([
            ("A", "2026-04-15 10:00:00", ""),
            ("B", "2026-05-02 10:00:00", ""),
        ])
        stats = reads_db.feed_stats()
        assert stats["rows"] == 2
        assert stats["months_covered"] == ["2026-04", "2026-05"]

        deleted = reads_db.delete_through_month(2026, 4)
        assert deleted == 1
        assert reads_db.feed_stats()["months_covered"] == ["2026-05"]

    def test_customer_cache_roundtrip(self):
        assert reads_db.cache_get_customer("SK041H") is None
        reads_db.cache_put_customer("SK041H", {
            "name": "Jane Doe", "email": "jane@ubc.ca",
            "primary_id": "123", "subclassification": "Student",
            "active_permit": "N",
        })
        rec = reads_db.cache_get_customer("SK041H")
        assert rec["found"] and rec["email"] == "jane@ubc.ca"

        reads_db.cache_put_customer("NOBODY1", None)
        rec = reads_db.cache_get_customer("NOBODY1")
        assert rec is not None and rec["found"] is False  # fresh negative cached


# ---------------------------------------------------------------------------
# Ingest endpoints
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setattr(settings, "ingest_client_id", "test-id")
    monkeypatch.setattr(settings, "ingest_client_secret", "test-secret")
    monkeypatch.setattr(settings, "genetec_date_format", "MM/dd/yyyy")
    return TestClient(app)


def _get_token(client):
    r = client.post("/api/ingest/token",
                    data={"grant_type": "client_credentials",
                          "client_id": "test-id", "client_secret": "test-secret"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


class TestIngest:
    def test_token_bad_credentials(self, client):
        r = client.post("/api/ingest/token",
                        data={"client_id": "test-id", "client_secret": "WRONG"})
        assert r.status_code == 401

    def test_token_basic_auth(self, client):
        import base64
        basic = base64.b64encode(b"test-id:test-secret").decode()
        r = client.post("/api/ingest/token",
                        headers={"Authorization": f"Basic {basic}"})
        assert r.status_code == 200

    def test_reads_require_bearer(self, client):
        r = client.post("/api/ingest/reads", json={"Read": {"Plate": "X"}})
        assert r.status_code == 401
        r = client.post("/api/ingest/reads", json={"Read": {"Plate": "X"}},
                        headers={"Authorization": "Bearer garbage"})
        assert r.status_code == 401

    def test_ingest_plain_read(self, client):
        token = _get_token(client)
        payload = {"Read": {
            "Plate": "sk041h", "DateLocal": "05/10/2026", "TimeLocal": "09:15:30",
            "DateUtc": "05/10/2026", "TimeUtc": "16:15:30",
            "CameraName": "H Lot Cam",
        }}
        r = client.post("/api/ingest/reads", json=payload,
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        assert r.json()["stored_new"] == 1
        rows = reads_db.month_reads(2026, 5)
        assert rows[0][0] == "SK041H"
        assert rows[0][1] == datetime(2026, 5, 10, 9, 15, 30)  # local, not UTC

    def test_ingest_hit_wrapped_and_batch(self, client):
        token = _get_token(client)
        payload = [
            {"Vehicle": {"Read": {"Plate": "AB123C", "DateLocal": "05/10/2026",
                                  "TimeLocal": "10:00:00"}}},
            {"Read": {"Plate": "CD456E", "DateLocal": "05/10/2026",
                      "TimeLocal": "11:00:00"}},
        ]
        r = client.post("/api/ingest/reads", json=payload,
                        headers={"Authorization": f"Bearer {token}"})
        assert r.json()["stored_new"] == 2

    def test_ingest_garbage_skipped(self, client):
        token = _get_token(client)
        payload = [
            {"Read": {"Plate": "******", "DateLocal": "05/10/2026", "TimeLocal": "10:00:00"}},
            {"Read": {"Plate": "", "DateLocal": "05/10/2026", "TimeLocal": "10:00:00"}},
            {"Read": {"Plate": "OK111A", "DateLocal": "garbage", "TimeLocal": "10:00:00"}},
            {"something": "else"},
        ]
        r = client.post("/api/ingest/reads", json=payload,
                        headers={"Authorization": f"Bearer {token}"})
        body = r.json()
        assert body["stored_new"] == 0

    def test_iso_date_format(self, client, monkeypatch):
        monkeypatch.setattr(settings, "genetec_date_format", "yyyy-MM-dd")
        token = _get_token(client)
        payload = {"Read": {"Plate": "EF789G", "DateLocal": "2026-05-12",
                            "TimeLocal": "23:55:00"}}
        r = client.post("/api/ingest/reads", json=payload,
                        headers={"Authorization": f"Bearer {token}"})
        assert r.json()["stored_new"] == 1
        rows = reads_db.month_reads(2026, 5)
        # late-evening read stays on its local date (UTC bug regression)
        assert rows[0][1].day == 12 and rows[0][1].hour == 23


# ---------------------------------------------------------------------------
# Reads source selection (feed vs file)
# ---------------------------------------------------------------------------

class TestReadsSourceSelection:
    def _client(self, tmp_path, monkeypatch):
        from app.integrations.genetec import GenetecClient
        monkeypatch.setattr(settings, "uploads_dir", str(tmp_path / "uploads"))
        monkeypatch.setattr(settings, "stub_data_dir", str(tmp_path / "nostub"))
        return GenetecClient()

    def test_feed_used_when_file_absent(self, tmp_path, monkeypatch):
        reads_db.insert_reads([("SK041H", "2026-05-10 09:00:00", "")])
        c = self._client(tmp_path, monkeypatch)
        reads = asyncio.run(c.fetch_reads(2026, 5))
        assert [r.plate for r in reads] == ["SK041H"]

    def test_error_when_nothing_available(self, tmp_path, monkeypatch):
        from app.integrations.genetec import ReadsFileError
        c = self._client(tmp_path, monkeypatch)
        with pytest.raises(ReadsFileError, match="No plate reads available"):
            asyncio.run(c.fetch_reads(2026, 5))

    def test_file_wins_when_more_coverage(self, tmp_path, monkeypatch):
        from openpyxl import Workbook
        # feed: 1 day; file: 2 days -> file wins
        reads_db.insert_reads([("FEED01", "2026-05-10 09:00:00", "")])
        uploads = tmp_path / "uploads"; uploads.mkdir()
        wb = Workbook(); ws = wb.active
        ws.append(["junk", None])
        ws.append(["Plate number", "Local time (PDT)"])
        for day in (10, 11):
            ws.append(["FILE01", f"05/{day}/2026, 09:00:00 AM"])
        wb.save(uploads / "plate_reads.xlsx")
        c = self._client(tmp_path, monkeypatch)
        reads = asyncio.run(c.fetch_reads(2026, 5))
        assert {r.plate for r in reads} == {"FILE01"}


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

class TestEnrichment:
    def test_enrich_with_cache_and_failures(self, monkeypatch):
        from app.core import enrich as enrich_mod
        monkeypatch.setattr(settings, "use_stubs", False)

        calls = []

        async def fake_lookup(plate):
            calls.append(plate)
            if plate == "BOOM99":
                raise RuntimeError("flex hiccup")
            if plate == "KNOWN1":
                return {"name": "Jane", "email": "jane@ubc.ca",
                        "primary_id": "1", "subclassification": "Staff",
                        "active_permit": "N"}
            return None

        import app.integrations.t2_flex as t2f
        monkeypatch.setattr(t2f, "fetch_customer_by_plate", fake_lookup)

        qualifiers = [
            {"plate": "KNOWN1", "name": "", "email": None, "track": "payment"},
            {"plate": "GHOST1", "name": "", "email": None, "track": "payment"},
            {"plate": "BOOM99", "name": "", "email": None, "track": "payment"},
            {"plate": "HASMAIL", "name": "x", "email": "x@ubc.ca", "track": "permit"},
        ]
        stats = asyncio.run(enrich_mod.enrich_qualifiers(qualifiers))
        assert stats["needed"] == 3
        assert stats["found"] == 1
        assert stats["errors"] == 1
        assert qualifiers[0]["email"] == "jane@ubc.ca"
        assert qualifiers[1]["email"] is None  # ghost stays blank

        # Second pass: cache hits, no live calls for KNOWN1/GHOST1
        calls.clear()
        qualifiers2 = [
            {"plate": "KNOWN1", "name": "", "email": None, "track": "payment"},
            {"plate": "GHOST1", "name": "", "email": None, "track": "payment"},
        ]
        stats2 = asyncio.run(enrich_mod.enrich_qualifiers(qualifiers2))
        assert stats2["cache_hits"] == 2
        assert calls == []
        assert qualifiers2[0]["email"] == "jane@ubc.ca"

    def test_enrich_skipped_in_stub_mode(self, monkeypatch):
        from app.core import enrich as enrich_mod
        monkeypatch.setattr(settings, "use_stubs", True)
        stats = asyncio.run(enrich_mod.enrich_qualifiers(
            [{"plate": "X", "email": None}]))
        assert stats["needed"] == 0


# ---------------------------------------------------------------------------
# monthly_run orchestration
# ---------------------------------------------------------------------------

class TestMonthlyRun:
    @pytest.fixture
    def env(self, tmp_path, monkeypatch):
        import monthly_run as mr
        monkeypatch.setattr(mr, "QUALIFIERS_DIR", tmp_path / "data")
        monkeypatch.setattr(settings, "min_coverage_days", 2)
        monkeypatch.setattr(settings, "use_stubs", True)
        monkeypatch.setattr(settings, "use_stubs_payments", True)
        monkeypatch.setattr(settings, "stub_data_dir", str(tmp_path / "stub"))
        monkeypatch.setattr(settings, "uploads_dir", str(tmp_path / "uploads"))
        stub = tmp_path / "stub"; stub.mkdir()
        (stub / "Payments.csv").write_text(
            'License Plate\r\n"=""SK041H"""\r\n')
        (stub / "Permits.txt").write_text(
            "Distinct of ENT_UID,EMAIL_ADDRESS,SERIES_PREFIX,PERMIT_NUMBER,LICENSE_PLATES\n"
            "1,holder@ubc.ca,STAFF,P-1,XY987Z\n")

        sent = []
        def fake_send(to, subject, body, attachments=None):
            sent.append({"to": to, "subject": subject, "body": body,
                         "attachments": attachments or []})
        monkeypatch.setattr(mr, "send_email", fake_send)
        return mr, sent

    def _seed_feed(self):
        rows = []
        for day in (10, 11):  # 2 days >= min_coverage_days=2
            rows.append(("SK041H", f"2026-05-{day:02d} 09:00:00", ""))
            rows.append(("SK041H", f"2026-05-{day:02d} 11:00:00", ""))
        reads_db.insert_reads(rows)

    def test_coverage_gate_blocks(self, env):
        mr, sent = env
        rc = asyncio.run(mr.run(2026, 5, 1, False))
        assert rc == 1
        assert "coverage too low" in sent[0]["subject"]
        assert csv_store.get_draw_by_month("2026-05") is None

    def test_full_run_then_idempotent(self, env, monkeypatch):
        mr, sent = env
        monkeypatch.setattr(settings, "min_visits", 2)
        self._seed_feed()

        rc = asyncio.run(mr.run(2026, 5, 1, False))
        assert rc == 0
        draw = csv_store.get_draw_by_month("2026-05")
        assert draw is not None and len(draw["winners"]) == 1
        assert csv_store.has_audit("report_sent", "2026-05")
        assert len(sent) == 1
        assert sent[0]["attachments"][0][0] == "qualifiers_2026-05.csv"
        # retention: feed cleaned after success
        assert reads_db.month_days_covered(2026, 5) == 0

        # Second run: nothing happens
        rc = asyncio.run(mr.run(2026, 5, 1, False))
        assert rc == 0
        assert len(sent) == 1  # no second email
        assert csv_store.get_draw_by_month("2026-05")["winners"] == draw["winners"]

    def test_email_failure_keeps_draw_and_retries(self, env, monkeypatch):
        mr, sent = env
        monkeypatch.setattr(settings, "min_visits", 2)
        self._seed_feed()

        boom = {"on": True}
        real_alert = []
        def flaky_send(to, subject, body, attachments=None):
            if boom["on"] and not subject.startswith("[Parking Perks ALERT]"):
                raise RuntimeError("gmail down")
            real_alert.append(subject)
        monkeypatch.setattr(mr, "send_email", flaky_send)

        rc = asyncio.run(mr.run(2026, 5, 1, False))
        assert rc == 1
        draw = csv_store.get_draw_by_month("2026-05")
        assert draw is not None                      # draw survived
        assert not csv_store.has_audit("report_sent", "2026-05")
        winners_before = [w["plate"] for w in draw["winners"]]

        # Next day: email works again -> report only, same winners
        boom["on"] = False
        rc = asyncio.run(mr.run(2026, 5, 1, False))
        assert rc == 0
        assert csv_store.has_audit("report_sent", "2026-05")
        draw2 = csv_store.get_draw_by_month("2026-05")
        assert [w["plate"] for w in draw2["winners"]] == winners_before  # NOT redrawn
