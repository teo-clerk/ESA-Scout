"""Parser for the ESA Academy opportunities overview page.

Source: https://www.esa.int/Education/ESA_Academy/ESA_Academy_opportunities3

This page carries the *Projects & Testing* programmes (REXUS/BEXUS, Fly Your
Satellite!, the Experiments Programme, ...) in a three-column table:

    <table class="default" summary="Programmes and deadlines">
      <tr><td>Programme</td><td>Current cycle</td><td>Contact</td></tr>
      <tr><td>Rocket and Balloon Experiments: REXUS/BEXUS</td>
          <td>Call for proposals open until 8 October 2026, 13:00 CEST</td>
          <td>rexus-bexus@esa.int</td></tr>

Status is inferred from the free-text "Current cycle" wording, which is the only
signal the page provides. Note that "Next cycle expected to open in 2027"
contains the word "open" but means *Pending* — deferral wording is therefore
checked before openness wording.
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

SOURCE = "esa_academy"
SOURCE_LABEL = "ESA Academy Projects"
BASE_URL = "https://www.esa.int"

_COLUMN_ALIASES: dict[str, str] = {
    "programme": "title",
    "program": "title",
    "opportunity": "title",
    "current cycle": "cycle",
    "cycle": "cycle",
    "deadline": "cycle",
    "contact": "contact",
}

# Checked in order: deferral wording wins over the bare word "open".
_PENDING_MARKERS = (
    "expected", "next cycle", "will open", "to be announced", "tbc", "tba",
    "coming soon", "in preparation", "upcoming", "not yet",
)
_CLOSED_MARKERS = ("closed", "no longer", "has ended", "ended", "expired")
_OPEN_MARKERS = ("open until", "open unti", "now open", "is open", "open ", "apply")


def cycle_status(raw: str) -> str:
    """Infer a canonical status from the free-text 'Current cycle' cell."""
    text = clean(raw).lower()

    if not text:
        return STATUS_UNKNOWN
    if any(marker in text for marker in _CLOSED_MARKERS):
        return STATUS_CLOSED
    if any(marker in text for marker in _PENDING_MARKERS):
        return STATUS_PENDING
    if any(marker in text for marker in _OPEN_MARKERS):
        # The source label is authoritative; an elapsed deadline is surfaced by
        # the dashboard rather than silently reclassifying the row as Closed.
        return STATUS_OPEN
    return STATUS_PENDING


def _map_columns(cells: list[Node]) -> dict[str, int]:
    columns: dict[str, int] = {}
    for index, cell in enumerate(cells):
        label = clean(cell.text()).lower()
        if not label:
            continue
        for alias, field_name in _COLUMN_ALIASES.items():
            if alias in label and field_name not in columns:
                columns[field_name] = index
                break
    return columns


def _is_header_row(cells: list[Node]) -> bool:
    text = " ".join(clean(c.text()).lower() for c in cells)
    return "programme" in text and ("cycle" in text or "contact" in text)


def parse_html(markup: str, base_url: str = BASE_URL, today: date | None = None) -> ScrapeResult:
    """Extract the Projects & Testing programmes table."""
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
            continue
        opportunity = _row_to_opportunity(cells, columns, base_url, today)
        if opportunity is not None:
            opportunities.append(opportunity)

    if not columns:
        errors.append(f"{SOURCE}: header row not found — column layout may have changed")
    elif not opportunities:
        errors.append(f"{SOURCE}: header parsed but no data rows matched")

    return ScrapeResult(tuple(opportunities), tuple(errors))


def _row_to_opportunity(
    cells: list[Node], columns: dict[str, int], base_url: str, today: date
) -> Opportunity | None:
    def cell_at(name: str) -> Node | None:
        index = columns.get(name)
        if index is None or index >= len(cells):
            return None
        return cells[index]

    title_cell = cell_at("title")
    title = clean(title_cell.text()) if title_cell else ""
    if not title:
        return None

    cycle_cell = cell_at("cycle")
    cycle_text = clean(cycle_cell.text()) if cycle_cell else ""
    contact_cell = cell_at("contact")
    contact = clean(contact_cell.text()) if contact_cell else ""

    # Prefer an http(s) link from the programme cell; ignore mailto: contacts.
    url = ""
    for candidate in (title_cell, cycle_cell):
        if candidate is None:
            continue
        for link in candidate.css("a"):
            resolved = absolutise(link.attr("href"), base_url)
            if resolved and not resolved.startswith("mailto:"):
                url = resolved
                break
        if url:
            break

    deadline = dates.parse_date(cycle_text, today)
    status = cycle_status(cycle_text)
    summary = cycle_text or "ESA Academy projects & testing programme."
    if contact and "@" in contact:
        summary = f"{summary} Contact: {contact}."

    return Opportunity(
        id=slugify(SOURCE, title),
        title=title,
        source=SOURCE,
        source_label=SOURCE_LABEL,
        url=url or f"{base_url}/Education/ESA_Academy",
        status=status,
        kind="Project / Hands-on Programme",
        category=categorize(title, cycle_text),
        summary=summary,
        deadline_text=cycle_text,
        deadline=dates.to_iso(deadline),
    )
