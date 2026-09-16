from __future__ import annotations

import datetime

from processing.silver._normalize import (
    DMY_FIRST_DATE_FORMATS,
    clean_email,
    clean_phone,
    clean_text,
    lower_or_none,
    parse_date,
    parse_int,
    upper_or_none,
)


def test_clean_text_strips_and_maps_blank_to_none() -> None:
    assert clean_text("  Hello  ") == "Hello"
    assert clean_text("") is None
    assert clean_text("   ") is None
    assert clean_text(None) is None


def test_clean_email_lowercases() -> None:
    assert clean_email("  Person@Example.COM ") == "person@example.com"
    assert clean_email(None) is None
    assert clean_email("") is None


def test_clean_phone_keeps_digits_and_plus_only() -> None:
    assert clean_phone("+91 (98) 765-43210") == "+919876543210"
    assert clean_phone("") is None
    assert clean_phone(None) is None
    assert clean_phone("N/A") is None


def test_upper_and_lower_or_none() -> None:
    assert upper_or_none("active") == "ACTIVE"
    assert lower_or_none("ACTIVE") == "active"
    assert upper_or_none(None) is None
    assert upper_or_none("") is None


def test_parse_int_handles_numeric_strings_and_junk() -> None:
    assert parse_int("42") == 42
    assert parse_int(42.9) == 42
    assert parse_int("") is None
    assert parse_int(None) is None
    assert parse_int("not-a-number") is None


def test_parse_date_default_formats() -> None:
    assert parse_date("2026-07-01") == datetime.date(2026, 7, 1)
    # day=25 can't be a month, so this is unambiguous even tried against
    # multiple formats in sequence.
    assert parse_date("25-12-2026") == datetime.date(2026, 12, 25)
    assert parse_date(None) is None
    assert parse_date("") is None
    assert parse_date("garbage") is None


def test_parse_date_dmy_first_disambiguates_correctly() -> None:
    # 01-02-2026 is ambiguous (Jan 2 vs Feb 1). DMY_FIRST must read it as
    # day-month-year, matching Edmingle's actual export format.
    assert parse_date("01-02-2026", DMY_FIRST_DATE_FORMATS) == datetime.date(2026, 2, 1)
