"""Small, dependency-free normalization helpers shared by every Silver
transform. Deliberately plain functions (no pandas) -- these transforms are
row-by-row cleanups, not the pandas-heavy business logic that lives in
api_scripts/ collectors."""
from __future__ import annotations

import re
from datetime import date, datetime

_NON_DIGIT_PLUS = re.compile(r"[^0-9+]")

DEFAULT_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S")
DMY_FIRST_DATE_FORMATS = ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y")


def clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def clean_email(value: object) -> str | None:
    text = clean_text(value)
    return text.lower() if text else None


def clean_phone(value: object) -> str | None:
    if not value:
        return None
    cleaned = _NON_DIGIT_PLUS.sub("", str(value))
    return cleaned or None


def upper_or_none(value: object) -> str | None:
    text = clean_text(value)
    return text.upper() if text else None


def lower_or_none(value: object) -> str | None:
    text = clean_text(value)
    return text.lower() if text else None


def parse_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_date(value: object, formats: tuple[str, ...] = DEFAULT_DATE_FORMATS) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
