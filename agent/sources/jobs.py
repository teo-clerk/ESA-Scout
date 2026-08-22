"""Parser for the ESA careers portal (SAP SuccessFactors).

Source: https://jobs.esa.int/search/

Results are server-rendered job tiles, 25 per page, paginated with `startrow`:

    <li class="job-tile job-id-1288869001 ..." data-url="/job/Noordwijk-ESA-Graduate-Trainee-.../1288869001/">
      <a class="jobTitle-link" href="/job/...">ESA Graduate Trainee in the ...</a>
      <div id="job-1288869001-desktop-section-shifttype-value">ESA Graduate Trainee</div>
      <div id="job-1288869001-desktop-section-department-value">7 September 2026 23:59 CET/CEST</div>
      <div id="job-1288869001-desktop-section-multilocation-value">Noordwijk, NL</div>

ESA's SuccessFactors instance puts the *application closing date* in the field
labelled `department`, so fields are resolved by content shape (does it parse as
a date?) with the observed names as hints, rather than trusting the name alone.

Each tile is duplicated for the desktop and mobile layouts; `id*=` matching
takes the first occurrence and the caller dedupes by job id.
"""

from __future__ import annotations

from datetime import date

from .. import dates
from ..categorize import categorize
from ..html import Node, parse
from ..models import STATUS_CLOSED, STATUS_OPEN, Opportunity
from .common import ScrapeResult, absolutise, clean, slugify

SOURCE = "esa_jobs"
SOURCE_LABEL = "ESA Careers"
BASE_URL = "https://jobs.esa.int"
RESULTS_PER_PAGE = 25

# Field names seen on ESA's careers site, in the order we try them.
_DATE_FIELD_ORDER = ("closingdate", "date", "department", "shifttype")
_LOCATION_FIELD_ORDER = ("multilocation", "location", "city")
_KNOWN_FIELDS = (
    "shifttype", "department", "multilocation", "location", "city",
    "date", "closingdate",
)


def _field(tile: Node, name: str) -> str:
    """Read one SuccessFactors section field from a tile."""
    node = tile.css_first(f'div[id*="-section-{name}-value"]')
    if node is not None:
        return clean(node.text())
    # Fallback for themes that expose the field as a class instead of an id.
    node = tile.css_first(f"div.section-field.{name} div")
    return clean(node.text()) if node is not None else ""


def matches_keywords(title: str, kind: str, keywords: tuple[str, ...]) -> bool:
    """True when a posting looks relevant to a student/early-career applicant.

    An empty keyword tuple disables filtering and keeps every posting.
    """
    if not keywords:
        return True
    haystack = f"{title} {kind}".lower()
    return any(keyword.lower() in haystack for keyword in keywords)


def parse_html(
    markup: str,
    base_url: str = BASE_URL,
    keywords: tuple[str, ...] = (),
    today: date | None = None,
) -> ScrapeResult:
    """Extract job tiles from one results page."""
    today = today or dates.today_utc()
    try:
        document = parse(markup)
    except Exception as exc:
        return ScrapeResult.failed(f"{SOURCE}: could not parse HTML ({exc})")

    tiles = document.css("li.job-tile")
    if not tiles:
        # A legitimately empty results page (end of pagination) is not an error;
        # the orchestrator stops paging when it gets zero opportunities.
        return ScrapeResult()

    opportunities: list[Opportunity] = []
    for tile in tiles:
        opportunity = _tile_to_opportunity(tile, base_url, keywords, today)
        if opportunity is not None:
            opportunities.append(opportunity)
    return ScrapeResult(tuple(opportunities))


def _tile_to_opportunity(
    tile: Node, base_url: str, keywords: tuple[str, ...], today: date
) -> Opportunity | None:
    link = tile.css_first("a.jobTitle-link") or tile.css_first("a")
    title = clean(link.text()) if link is not None else ""
    if not title:
        return None

    href = tile.attr("data-url") or (link.attr("href") if link is not None else "")
    url = absolutise(href, base_url) or base_url

    raw = {name: _field(tile, name) for name in _KNOWN_FIELDS}

    # Resolve the deadline by content shape, not by field name.
    deadline_text = ""
    deadline: date | None = None
    for name in _DATE_FIELD_ORDER:
        value = raw.get(name, "")
        parsed = dates.parse_date(value, today) if value else None
        if parsed is not None:
            deadline_text, deadline = value, parsed
            break

    location = next(
        (raw[name] for name in _LOCATION_FIELD_ORDER if raw.get(name)), ""
    )

    # `shifttype` is the contract type unless it was consumed as the deadline.
    kind = raw.get("shifttype", "")
    if kind and kind == deadline_text:
        kind = ""
    kind = kind or "Vacancy"

    if not matches_keywords(title, kind, keywords):
        return None

    status = STATUS_CLOSED if dates.is_past(deadline, today) else STATUS_OPEN
    summary_parts = [p for p in (kind, location) if p]
    summary = " · ".join(summary_parts) if summary_parts else "ESA vacancy."

    return Opportunity(
        id=slugify(SOURCE, title, location),
        title=title,
        source=SOURCE,
        source_label=SOURCE_LABEL,
        url=url,
        status=status,
        kind=kind,
        category=categorize(title, kind),
        location=location,
        summary=summary,
        deadline_text=deadline_text,
        deadline=dates.to_iso(deadline),
    )


def page_params(page_index: int, query: str = "") -> dict[str, str]:
    """Query parameters for the Nth results page (0-based)."""
    return {"q": query, "startrow": str(page_index * RESULTS_PER_PAGE)}
