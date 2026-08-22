"""Tests for parsing ESA's free-text dates."""

from __future__ import annotations

from datetime import date

import pytest

from agent import dates

REF = date(2026, 8, 17)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("5 April 2026", date(2026, 4, 5)),
        ("15 May 2026", date(2026, 5, 15)),
        ("31 August 2026 - 1 September 2026", date(2026, 8, 31)),
        ("13 - 16 october 2026", date(2026, 10, 16)),  # lower-case; range end
        ("2026-04-05", date(2026, 4, 5)),
        ("April 5, 2026", date(2026, 4, 5)),
        ("7 September 2026 23:59 CET/CEST", date(2026, 9, 7)),
        ("Call for proposals open until 8 October 2026, 13:00 CEST", date(2026, 10, 8)),
        ("1st March 2027", date(2027, 3, 1)),
    ],
)
def test_parse_date_reads_real_formats(text, expected):
    assert dates.parse_date(text, REF) == expected


@pytest.mark.parametrize(
    "text", ["", None, "Next cycle expected to open in 2027", "TBC", "no date here"]
)
def test_parse_date_returns_none_when_unreadable(text):
    assert dates.parse_date(text, REF) is None


def test_year_is_inferred_forward_when_absent():
    """A year-less date long past rolls forward; a recent or future one does not.

    The tolerance window matters for real data: the live TLP table lists a
    "19 April" deadline for a July 2026 activity, which must stay in 2026 rather
    than jumping to 2027.
    """
    # ~7 months behind the reference date -> the author meant next year.
    assert dates.parse_date("10 January", REF) == date(2027, 1, 10)
    # Still ahead of us -> current year.
    assert dates.parse_date("10 December", REF) == date(2026, 12, 10)
    # Recently past but inside the tolerance window -> current year.
    assert dates.parse_date("19 April", REF) == date(2026, 4, 19)


def test_trailing_year_wins_over_inference():
    """"19 April" inside a string ending in 2026 must resolve to 2026."""
    assert dates.parse_date("19 April 2026", REF) == date(2026, 4, 19)


def test_invalid_calendar_date_is_rejected():
    assert dates.parse_date("31 February 2026", REF) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("22 - 26 June 2026", date(2026, 6, 22)),
        ("22 – 26 June 2026", date(2026, 6, 22)),  # en dash
        ("28 September 2026 – 2 October 2026", date(2026, 9, 28)),
        ("5 April 2026", date(2026, 4, 5)),
    ],
)
def test_parse_range_start_borrows_month_from_range_end(text, expected):
    assert dates.parse_range_start(text, REF) == expected


def test_parse_range_start_handles_empty():
    assert dates.parse_range_start("", REF) is None


def test_normalise_dashes_converts_every_variant():
    assert dates.normalise_dashes("a–b—c−d") == "a-b-c-d"


def test_days_until_and_is_past():
    assert dates.days_until(date(2026, 8, 20), REF) == 3
    assert dates.days_until(date(2026, 8, 10), REF) == -7
    assert dates.days_until(None, REF) is None
    assert dates.is_past(date(2026, 8, 10), REF) is True
    assert dates.is_past(date(2026, 8, 20), REF) is False
    assert dates.is_past(None, REF) is False


def test_to_iso():
    assert dates.to_iso(date(2026, 4, 5)) == "2026-04-05"
    assert dates.to_iso(None) == ""


def test_utc_now_iso_has_zulu_suffix():
    value = dates.utc_now_iso()
    assert value.endswith("Z")
    assert "T" in value
