"""Integration tests for the qualification pipeline."""

from datetime import datetime

import pytest

from app.core.qualify import run_qualification
from app.integrations.base import Citation, Payment, PermitHolder, PlateRead


def _ts(date_str: str, hour: int = 9, minute: int = 0) -> datetime:
    return datetime(2026, 4, int(date_str), hour, minute)


def _reads_for(plate: str, days: list[int], span_hours: float = 2.0) -> list[PlateRead]:
    reads = []
    for day in days:
        reads.append(PlateRead(plate=plate, timestamp=_ts(str(day), 9, 0)))
        h = int(9 + span_hours)
        reads.append(PlateRead(plate=plate, timestamp=_ts(str(day), h, 0)))
    return reads


class TestPaymentTrack:
    def test_qualifies_with_enough_days(self):
        reads = _reads_for("SK041H", days=list(range(1, 11)))
        payments = [Payment(plate="SK041H")]
        qualifiers, summary = run_qualification(reads, payments, [], [], min_visits=10, min_hours=1.0)
        plates = [q["plate"] for q in qualifiers]
        assert "SK041H" in plates

    def test_disqualified_by_citation(self):
        reads = _reads_for("SK041H", days=list(range(1, 11)))
        payments = [Payment(plate="SK041H")]
        citations = [Citation(plate="SK041H")]
        qualifiers, _ = run_qualification(reads, payments, citations, [], min_visits=10)
        assert not any(q["plate"] == "SK041H" for q in qualifiers)

    def test_insufficient_days_excluded(self):
        reads = _reads_for("SK041H", days=[1, 2, 3])  # only 3 days
        payments = [Payment(plate="SK041H")]
        qualifiers, _ = run_qualification(reads, payments, [], [], min_visits=10)
        assert not any(q["plate"] == "SK041H" for q in qualifiers)

    def test_short_span_excluded(self):
        # Span of 0 hours (same first/last read) should not qualify
        reads = [PlateRead(plate="ABC123", timestamp=_ts("5", 9, 0))] * 10
        payments = [Payment(plate="ABC123")]
        qualifiers, _ = run_qualification(reads, payments, [], [], min_visits=1, min_hours=1.0)
        assert not any(q["plate"] == "ABC123" for q in qualifiers)

    def test_no_payment_excluded(self):
        reads = _reads_for("SK041H", days=list(range(1, 11)))
        qualifiers, _ = run_qualification(reads, [], [], [], min_visits=10)
        assert not any(q["plate"] == "SK041H" for q in qualifiers)


class TestPermitTrack:
    def test_permit_holder_qualifies_without_visits(self):
        permit = PermitHolder(
            entity_uid="001",
            email="j.doe@ubc.ca",
            series_prefix="S",
            permit_number="A1234",
            plates=["SK041H"],
        )
        qualifiers, _ = run_qualification([], [], [], [permit])
        assert any(q["plate"] == "SK041H" and q["track"] == "permit" for q in qualifiers)

    def test_bike_permit_excluded(self):
        permit = PermitHolder(
            entity_uid="002",
            email="biker@ubc.ca",
            series_prefix="BIKE",
            permit_number="B001",
            plates=["BIKE01"],
        )
        qualifiers, _ = run_qualification([], [], [], [permit])
        assert not any(q["plate"] == "BIKE01" for q in qualifiers)

    def test_permit_takes_precedence_over_payment(self):
        reads = _reads_for("SK041H", days=list(range(1, 11)))
        payments = [Payment(plate="SK041H")]
        permit = PermitHolder(
            entity_uid="001",
            email="j.doe@ubc.ca",
            series_prefix="S",
            permit_number="A1234",
            plates=["SK041H"],
        )
        qualifiers, _ = run_qualification(reads, payments, [], [permit])
        matching = [q for q in qualifiers if q["plate"] == "SK041H"]
        assert len(matching) == 1
        assert matching[0]["track"] == "permit"

    def test_permit_disqualified_by_citation(self):
        permit = PermitHolder(
            entity_uid="001",
            email="j.doe@ubc.ca",
            series_prefix="S",
            permit_number="A1234",
            plates=["SK041H"],
        )
        citations = [Citation(plate="SK041H")]
        qualifiers, _ = run_qualification([], [], citations, [permit])
        assert not any(q["plate"] == "SK041H" for q in qualifiers)

    def test_multi_plate_permit_expands(self):
        permit = PermitHolder(
            entity_uid="003",
            email="multi@ubc.ca",
            series_prefix="S",
            permit_number="A9999",
            plates=["AAA111", "BBB222"],
        )
        qualifiers, _ = run_qualification([], [], [], [permit])
        plates = [q["plate"] for q in qualifiers]
        assert "AAA111" in plates
        assert "BBB222" in plates


class TestSummary:
    def test_summary_counts(self):
        reads = _reads_for("SK041H", days=list(range(1, 11)))
        payments = [Payment(plate="SK041H")]
        _, summary = run_qualification(reads, payments, [], [], min_visits=10)
        assert summary["final"] == 1
        assert summary["stage2_payment"] == 1
        assert summary["removed_citations"] == 0
