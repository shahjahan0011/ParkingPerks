"""Unit tests for all three plate normalisation functions."""

import pytest

from app.core.normalise import (
    normalise_citations_plate,
    normalise_payments_plate,
    normalise_reads_plate,
)


class TestNormaliseReads:
    def test_plain_plate(self):
        assert normalise_reads_plate("SK041H") == "SK041H"

    def test_lowercases_uppercased(self):
        assert normalise_reads_plate("sk041h") == "SK041H"

    def test_strips_whitespace(self):
        assert normalise_reads_plate("  SK041H  ") == "SK041H"

    def test_none_returns_empty(self):
        assert normalise_reads_plate(None) == ""

    def test_empty_returns_empty(self):
        assert normalise_reads_plate("") == ""


class TestNormalisePayments:
    def test_excel_formula_wrapper(self):
        assert normalise_payments_plate('="SK041H"') == "SK041H"

    def test_numeric_looking_plate(self):
        assert normalise_payments_plate('="0006"') == "0006"

    def test_plain_plate_unchanged(self):
        assert normalise_payments_plate("SK041H") == "SK041H"

    def test_none_returns_empty(self):
        assert normalise_payments_plate(None) == ""

    def test_sk041h_not_stripped(self):
        # The SK041H bug: must NOT strip SK from a plate that starts with SK
        result = normalise_payments_plate('="SK041H"')
        assert result == "SK041H", f"Got {result!r} — SK was incorrectly stripped"


class TestNormaliseCitations:
    def test_standard_bc_format(self):
        assert normalise_citations_plate("BC-SK041H-NA") == "SK041H"

    def test_ab_province(self):
        assert normalise_citations_plate("AB-XR099L-NA") == "XR099L"

    def test_sk_province(self):
        # SK province prefix must not strip "SK" from a plate starting with SK
        assert normalise_citations_plate("SK-SK041H-NA") == "SK041H"

    def test_four_part_plate(self):
        assert normalise_citations_plate("BC-SK-041H-NA") == "SK041H"

    def test_non_na_suffix(self):
        assert normalise_citations_plate("BC-XE115F-BIKE") == "XE115F"

    def test_blank_middle(self):
        assert normalise_citations_plate("BC-  -NA") == ""

    def test_header_row(self):
        assert normalise_citations_plate("License #") == ""

    def test_none_returns_empty(self):
        assert normalise_citations_plate(None) == ""

    def test_uppercase_normalised(self):
        assert normalise_citations_plate("bc-sk041h-na") == "SK041H"
