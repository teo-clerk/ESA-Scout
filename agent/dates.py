"""Date extraction for ESA's free-text date fields.

ESA publishes dates as prose, with inconsistent casing, dash characters and
optional years. Observed real examples this module must handle:

    "22 – 26 June 2026"                       -> start 2026-06-22
    "28 September 2026 – 2 October 2026"      -> start 2026-09-28
    "13 – 16 october 2026"                    -> start 2026-10-13
    "5 April 2026"                            -> 2026-04-05
    "19 April"                                -> year inferred
    "7 September 2026 23:59 CET/CEST"         -> 2026-09-07
    "Call for proposals open until 8 October 2026, 13:00 CEST"
    "Next cycle expected to open in 2027"     -> no date

Everything returns `None` rather than raising: a date we cannot read must never
take down a scrape.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

_MONTH_PATTERN = "|".join(sorted(MONTHS, key=len, reverse=True))

# "5 April 2026" / "5 April" / "5th April 2026"
_DAY_MONTH = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{_MONTH_PATTERN})\b"
    rf"(?:\s*,?\s*(?P<year>\d{{4}}))?",
    re.IGNORECASE,
)

# "April 5, 2026". The (?!\d) guard stops the day group from biting off the
# first digits of a year: without it, "31 February 2026" matches day="20".
_MONTH_DAY = re.compile(
    rf"\b(?P<month>{_MONTH_PATTERN})\s+(?P<day>\d{{1,2}})(?!\d)(?:st|nd|rd|th)?"
    rf"(?:\s*,?\s*(?P<year>\d{{4}}))?",
    re.IGNORECASE,
)

# ISO "2026-04-05"
_ISO = re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\b")

# Any 4-digit year, used only to back-fill a bare "22 – 26 June 2026" range.
_YEAR = re.compile(r"\b(20\d{2})\b")

# Dash variants used in ranges: hyphen, en dash, em dash, minus.
_DASHES = "‐‑‒–—―−-"

# How far in the past a year-less date may fall before we roll it to next year.
_PAST_TOLERANCE_DAYS = 120


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def normalise_dashes(text: str) -> str:
    """Replace every unicode dash variant with a plain hyphen."""
    return re.sub(f"[{_DASHES}]", "-", text)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _infer_year(month: int, day: int, reference: date) -> int:
    """Pick the most plausible year for a date written without one.

    Assumes forward-looking listings: if this year's occurrence is already well
    past, the author meant next year.
    """
    candidate = _safe_date(reference.year, month, day)
    if candidate is None:  # e.g. 29 February in a non-leap year
        return reference.year + 1
    if (reference - candidate).days > _PAST_TOLERANCE_DAYS:
        return reference.year + 1
    return reference.year


def parse_date(text: str | None, reference: date | None = None) -> date | None:
    """Extract the first date from free text. Returns None when unreadable."""
    if not text:
        return None
    reference = reference or today_utc()
    cleaned = normalise_dashes(str(text))

    iso = _ISO.search(cleaned)
    if iso:
        return _safe_date(
            int(iso["year"]), int(iso["month"]), int(iso["day"])
        )

    for pattern in (_DAY_MONTH, _MONTH_DAY):
        match = pattern.search(cleaned)
        if not match:
            continue
        month = MONTHS.get(match["month"].lower())
        if month is None:
            continue
        day = int(match["day"])
        if match["year"]:
            year = int(match["year"])
        else:
            # A trailing year elsewhere in the string wins over inference:
            # "22 - 26 June 2026" leaves the first day without its own year.
            trailing = _YEAR.search(cleaned)
            year = int(trailing.group(1)) if trailing else _infer_year(month, day, reference)
        resolved = _safe_date(year, month, day)
        if resolved:
            return resolved
    return None


def parse_range_start(text: str | None, reference: date | None = None) -> date | None:
    """Start date of an activity range such as "22 - 26 June 2026".

    A leading bare day number ("22 - 26 June 2026") borrows the month and year
    from the right-hand side of the range.
    """
    if not text:
        return None
    reference = reference or today_utc()
    cleaned = normalise_dashes(str(text)).strip()

    # Leading bare day followed by a dash: "22 - 26 June 2026".
    bare = re.match(r"^\s*(?P<day>\d{1,2})(?:st|nd|rd|th)?\s*-", cleaned)
    if bare:
        tail = parse_date(cleaned, reference)
        if tail:
            resolved = _safe_date(tail.year, tail.month, int(bare["day"]))
            if resolved:
                return resolved
    return parse_date(cleaned, reference)


def to_iso(value: date | None) -> str:
    """ISO-8601 string, or empty string when there is no date."""
    return value.isoformat() if value else ""


def days_until(value: date | None, reference: date | None = None) -> int | None:
    """Whole days from `reference` until `value`; negative once past."""
    if value is None:
        return None
    return (value - (reference or today_utc())).days


def is_past(value: date | None, reference: date | None = None) -> bool:
    """True when the date has already elapsed."""
    remaining = days_until(value, reference)
    return remaining is not None and remaining < 0


def utc_now_iso() -> str:
    """Current UTC timestamp, second precision, with a trailing Z."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
