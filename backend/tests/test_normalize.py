from datetime import date, datetime, timezone

from app.verification.normalize import extract_dates, extract_numbers, norm_cell


def test_numbers_ignore_identifiers_and_dates():
    text = "Subject 01-701-1015 (PT701-1015, kit K-000123) had SBP 300 on 2026-03-04, outside 60-250; WEEK 8 visit"
    assert extract_numbers(text) == [300.0, 60.0, 250.0, 8.0]
    assert extract_dates(text) == ["2026-03-04"]


def test_decimals_and_negatives():
    assert extract_numbers("ALT 5.25x ULN, change -7 days") == [5.25, -7.0]


def test_cell_normalization():
    assert norm_cell(300) == norm_cell("300.0") == norm_cell(300.004) == "300.00"
    assert norm_cell("  Not   Recovered ") == "not recovered"
    assert norm_cell(date(2026, 3, 4)) == norm_cell("2026-03-04T08:00:00+00:00") == norm_cell(datetime(2026, 3, 4, 8, tzinfo=timezone.utc)) == "2026-03-04"
    assert norm_cell(None) == "" and norm_cell(True) == "true"


def test_numbers_with_unit_suffixes_are_not_truncated():
    assert extract_numbers("ALT was 5.25x ULN and SBP 300mmHg") == [5.25, 300.0]
    assert extract_numbers("Week 8, 3.0x, 1/2 dose") == [8.0, 3.0]
