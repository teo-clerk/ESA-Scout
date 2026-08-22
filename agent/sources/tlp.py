"""Parser for the ESA Training and Learning Programme opportunities table.

Source: https://educationforms.esa.int/tlp/table/current-opportunities/

The page is a server-rendered WordPress table (no JS required). Real markup:

    <tr><td></td><td><strong>Date of activity</strong></td><td></td>
        <td><strong>Programme</strong></td><td><strong>Deadline to apply</strong></td>
        <td><strong>Type</strong></td><td><strong>Status</strong></td></tr>
    <tr><td></td><td>22 &#8211; 26 June 2026</td><td></td>
        <td>Navigation Training Course</td><td>5 April 2026</td>
        <td>Training Course</td>
        <td><a href="https://learn.esa.int/...">Open</a></td></tr>

Note the padding `<td></td>` spacers: columns are located by matching the header
labels rather than by fixed index, so an added or reordered column does not
silently shift every field.
"""

from __future__ import annotations

from datetime import date

from .. import dates
from ..categorize import categorize
from ..html import Node, parse
from ..models import (
    STATUS_CLOSED,
    STATUS_OPEN,
    STATUS_PENDING,
    STATUS_UNKNOWN,
    Opportunity,
)
from .common import ScrapeResult, absolutise, clean, slugify

SOURCE = "esa_tlp"
SOURCE_LABEL = "ESA Academy TLP"

# Header label fragment -> logical field name.
_COLUMN_ALIASES: dict[str, str] = {
    "date of activity": "activity_dates",
    "dates": "activity_dates",
    "programme": "title",
    "program": "title",
    "activity": "title",
    "deadline to apply": "deadline",
    "deadline": "deadline",
    "application deadline": "deadline",
    "type": "kind",
    "status": "status",
}

_REQUIRED_FIELDS = ("title", "status")


def _map_columns(header_cells: list[Node]) -> dict[str, int]:
    """Map logical field names to column indices using the header row."""
    columns: dict[str, int] = {}
    for index, cell in enumerate(header_cells):
        label = clean(cell.text()).lower()
        if not label:
            continue
        for alias, field_name in _COLUMN_ALIASES.items():
            if alias in label and field_name not in columns:
                columns[field_name] = index
                break
    return columns


def _is_header_row(cells: list[Node]) -> bool:
    """A header row is the one naming both the programme and status columns."""
    text = " ".join(clean(c.text()).lower() for c in cells)
    return "programme" in text and "status" in text


def normalise_status(raw: str) -> str:
    """Map ESA's status wording onto the canonical vocabulary.

    The source's own label is authoritative. We deliberately do *not* downgrade
    a declared "Open" to "Closed" just because the published deadline has
    elapsed: ESA's table is often stale, deadline text is sometimes year-less
    and ambiguous, and hiding a genuinely open call is far more costly to the
    applicant than showing an expired one. The dashboard flags an elapsed
    deadline separately, computed live from the ISO date.
    """
    text = clean(raw).lower()

    if any(word in text for word in ("closed", "expired", "ended")):
        return STATUS_CLOSED
    if any(word in text for word in ("open", "apply", "available")):
        return STATUS_OPEN
    if any(
        word in text
        for word in ("soon", "pending", "upcoming", "tbc", "tba", "to be", "expected")
    ):
        return STATUS_PENDING
    if not text:
        return STATUS_UNKNOWN
    return STATUS_PENDING


def parse_html(
    markup: str, base_url: str, today: date | None = None
) -> ScrapeResult:
    """Extract every opportunity row from the TLP table."""
    today = today or dates.today_utc()
    try:
        document = parse(markup)
    except Exception as exc:
        return ScrapeResult.failed(f"{SOURCE}: could not parse HTML ({exc})")

    rows = document.css("table tr")
    if not rows:
        return ScrapeResult.failed(f"{SOURCE}: no table rows found — markup may have changed")

    columns: dict[str, int] = {}
    opportunities: list[Opportunity] = []
    errors: list[str] = []

    for row in rows:
        cells = row.css("td") or row.css("th")
        if not cells:
            continue
        if _is_header_row(cells):
            columns = _map_columns(cells)
            continue
        if not columns:
            # Data appeared before we found a header: cannot trust indices.
            continue

        opportunity = _row_to_opportunity(cells, columns, base_url, today)
        if opportunity is not None:
            opportunities.append(opportunity)

    if not columns:
        errors.append(f"{SOURCE}: header row not found — column layout may have changed")
    elif not opportunities:
        errors.append(f"{SOURCE}: header parsed but no data rows matched")

    return ScrapeResult(tuple(opportunities), tuple(errors))


def _cell(cells: list[Node], columns: dict[str, int], name: str) -> Node | None:
    index = columns.get(name)
    if index is None or index >= len(cells):
        return None
    return cells[index]


def _row_to_opportunity(
    cells: list[Node], columns: dict[str, int], base_url: str, today: date
) -> Opportunity | None:
    """Convert one table row into an Opportunity, or None when unusable."""
    title_cell = _cell(cells, columns, "title")
    status_cell = _cell(cells, columns, "status")
    title = clean(title_cell.text()) if title_cell else ""
    if not title:
        return None

    activity_cell = _cell(cells, columns, "activity_dates")
    deadline_cell = _cell(cells, columns, "deadline")
    kind_cell = _cell(cells, columns, "kind")

    activity_dates = clean(activity_cell.text()) if activity_cell else ""
    deadline_text = clean(deadline_cell.text()) if deadline_cell else ""
    kind = clean(kind_cell.text()) if kind_cell else ""
    status_text = clean(status_cell.text()) if status_cell else ""

    # The application link lives on the status cell; fall back to the title cell.
    url = ""
    for candidate in (status_cell, title_cell):
        if candidate is None:
            continue
        link = candidate.css_first("a")
        if link is not None:
            url = absolutise(link.attr("href"), base_url)
            if url:
                break
    url = url or base_url

    deadline = dates.parse_date(deadline_text, today)
    activity_start = dates.parse_range_start(activity_dates, today)
    status = normalise_status(status_text)

    return Opportunity(
        id=slugify(SOURCE, title),
        title=title,
        source=SOURCE,
        source_label=SOURCE_LABEL,
        url=url,
        status=status,
        kind=kind,
        category=categorize(title, kind),
        activity_dates=activity_dates,
        activity_start=dates.to_iso(activity_start),
        deadline_text=deadline_text,
        deadline=dates.to_iso(deadline),
        summary=(
            f"{kind or 'ESA Academy activity'} running {activity_dates}."
            if activity_dates
            else (kind or "ESA Academy activity.")
        ),
    )
