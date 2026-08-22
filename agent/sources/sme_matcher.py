"""ESA-star public SME directory: fetch, parse and keyword-filter companies.

The directory at `/PublicEntityDir/PublicEntityDirSme` is an ASP.NET **GridMvc**
grid. Two things about it shape this module:

* The grid body is served by a separate endpoint that returns `{"html": ...}`
  JSON — but only when the request carries `X-Requested-With: XMLHttpRequest`.
  Without that header it returns the full page shell instead.
* Filtering is done through GridMvc's query syntax,
  `grid-filter=NationalityDesc__2__Spain` (2 = "equals"). Applying it server-side
  cuts the walk from 192 pages to 10 (Spain) + 21 (Italy).

Rows carry only name, country, type and size; city, website and the English
description live behind a per-company detail popup. Since the keyword filter
needs the description, every candidate's popup is fetched — concurrently,
because ~620 sequential round trips would dominate the run.

**Domains are derived, not published.** ESA-star exposes no structured activity
field, so `derive_domains` infers tags from the free-text description using the
configured keyword taxonomy. Matching is word-boundary anchored: a substring
test makes "GIS" hit "logistics" and "registration".
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from functools import lru_cache
from html import unescape
from typing import Iterable, Sequence

from .. import html as html_backend
from ..config import (
    ESASTAR_SME_DETAIL_URL,
    ESASTAR_SME_GRID_URL,
    SmeSettings,
)
from ..fetcher import Fetcher, FetchError
from ..sme_models import Sme, country_code_for
from .common import clean, slugify

LOGGER = logging.getLogger(__name__)

# GridMvc's "equals" filter operator.
_FILTER_EQUALS = "2"
# The endpoint only emits its JSON payload for XHR-shaped requests.
_XHR_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

# Long descriptions add little signal but multiply JSON size and prompt cost.
MAX_DESCRIPTION_CHARS = 2000

_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_PAGE_RE = re.compile(r"grid-page=(\d+)")
_DETAIL_ID_RE = re.compile(r"/PublicEntityDirPopupDetailSME/(\d+)")

# Display casing for derived domain tags. Anything not listed is title-cased.
_DOMAIN_LABELS = {
    "gis": "GIS",
    "ai": "Artificial Intelligence",
}

# Extra surface forms that mean the same domain. Kept deliberately small and
# unambiguous — every alias here is a term that would otherwise be missed on
# companies that clearly work in that field (e.g. a remote-sensing firm that
# only ever writes "multispectral and LiDAR sensors").
_KEYWORD_ALIASES: dict[str, tuple[str, ...]] = {
    "artificial intelligence": ("ai", "deep learning", "neural network"),
    "machine learning": ("machine-learning", "predictive model"),
    "remote sensing": ("remotely sensed", "multispectral", "hyperspectral", "lidar"),
    "earth observation": ("earth-observation", "eo data", "satellite imagery"),
    "computer vision": ("image processing", "image analysis"),
    "gis": ("geospatial", "geographic information", "geographical information"),
    "satellite data": ("satellite imagery", "space data"),
    "data processing": ("data analytics", "data analysis", "big data"),
    "software": ("software",),
}


@dataclass(frozen=True)
class ScanResult:
    """Companies that passed the keyword filter, plus non-fatal errors."""

    companies: tuple[Sme, ...] = ()
    scanned: int = 0
    errors: tuple[str, ...] = ()


# --- Text helpers ----------------------------------------------------------
def strip_markup(value: str) -> str:
    """Turn ESA-star's escaped HTML description into readable plain text.

    Descriptions are stored HTML-escaped inside a `<textarea>`, so after the
    parser unescapes once the text still contains literal `<strong>` markup.
    Two bounded passes handle both single- and double-escaped input.
    """
    if not value:
        return ""
    text = str(value)
    for _ in range(2):
        stripped = unescape(_TAG_RE.sub(" ", _BR_RE.sub(" ", text)))
        if stripped == text:
            break  # nothing left to unwrap
        text = stripped
    return clean(text)


def truncate(value: str, limit: int = MAX_DESCRIPTION_CHARS) -> str:
    """Cut over-long text on a word boundary, marking the elision."""
    if len(value) <= limit:
        return value
    head = value[:limit].rsplit(" ", 1)[0]
    return f"{head.rstrip('.,;:')}…"


def display_domain(keyword: str) -> str:
    """Human-facing label for a taxonomy keyword."""
    key = keyword.strip().lower()
    return _DOMAIN_LABELS.get(key, key.title())


def _split_nationality(value: str) -> tuple[str, str]:
    """Split ESA-star's "ES-Spain" into ("Spain", "ES")."""
    raw = clean(value)
    if not raw:
        return "", ""
    code, _, name = raw.partition("-")
    code = code.strip()
    name = name.strip()
    if name and len(code) == 2 and code.isalpha():
        return name, code.upper()
    # Unexpected shape: treat the whole value as the country name.
    return raw, country_code_for(raw)


def _terms_for(keyword: str) -> tuple[str, ...]:
    """A keyword plus its aliases, deduplicated."""
    terms = (keyword, *_KEYWORD_ALIASES.get(keyword, ()))
    seen: dict[str, None] = {}
    for term in terms:
        cleaned = term.strip().lower()
        if cleaned:
            seen.setdefault(cleaned, None)
    return tuple(seen)


@lru_cache(maxsize=8)
def _compile(keywords: tuple[str, ...]) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Pre-compile one word-boundary pattern per keyword.

    Cached because `derive_domains` runs once per company — recompiling the
    whole taxonomy 600 times per scan is pure waste.
    """
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for keyword in keywords:
        key = keyword.strip().lower()
        if not key:
            continue
        alternatives = "|".join(re.escape(term) for term in _terms_for(key))
        compiled.append(
            (key, re.compile(rf"\b(?:{alternatives})\b", re.IGNORECASE))
        )
    return tuple(compiled)


def derive_domains(
    text: str, keywords: Sequence[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Infer domain tags from free text.

    Returns `(display_domains, matched_keywords)` in taxonomy order, so two
    companies matching the same keywords always produce identical tag lists.
    """
    if not text:
        return (), ()
    matched = [
        key for key, pattern in _compile(tuple(keywords)) if pattern.search(text)
    ]
    return tuple(display_domain(key) for key in matched), tuple(matched)


# --- Payload unwrapping ----------------------------------------------------
def unwrap_html(payload: str) -> str:
    """Extract the markup from a `{"html": ...}` response.

    ESA-star sometimes answers the same endpoint with bare HTML, so a payload
    that is not JSON is returned unchanged rather than treated as an error.
    """
    text = (payload or "").strip()
    if not text.startswith("{"):
        return text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict):
        return str(data.get("html") or "")
    return text


# --- Grid parsing ----------------------------------------------------------
def parse_grid_html(markup: str, keywords: Sequence[str] = ()) -> tuple[Sme, ...]:
    """Read one grid page into partially populated `Sme` records.

    Only the columns the grid publishes are filled in; city, website and
    description arrive later from the detail popup.
    """
    if not markup.strip():
        return ()
    document = html_backend.parse(markup)
    companies: list[Sme] = []

    for row in document.css("tr.grid-row"):
        cells = {
            cell.attr("data-name"): cell for cell in row.css("td.grid-cell")
        }
        name = clean(cells["Name"].text()) if "Name" in cells else ""
        if not name:
            continue

        link = cells["EntityId"].css_first("a") if "EntityId" in cells else None
        href = link.attr("href") if link is not None else ""
        match = _DETAIL_ID_RE.search(href)
        if match is None:
            # Without the popup id we cannot enrich or link the company.
            LOGGER.debug("skipping grid row without a detail link: %s", name)
            continue
        entity_id = match.group(1)

        country, code = _split_nationality(
            cells["NationalityDesc"].text() if "NationalityDesc" in cells else ""
        )
        companies.append(
            Sme(
                id=slugify(name, entity_id),
                entity_id=entity_id,
                name=name,
                country=country,
                country_code=code,
                entity_type=clean(
                    cells["EntityTypeDesc"].text() if "EntityTypeDesc" in cells else ""
                ),
                entity_size=clean(
                    cells["EntitySizeDesc"].text() if "EntitySizeDesc" in cells else ""
                ),
                detail_url=f"{ESASTAR_SME_DETAIL_URL}/{entity_id}",
            )
        )
    return tuple(companies)


def last_page(markup: str) -> int:
    """Highest page number advertised by the pager (1 when there is none)."""
    pages = [int(value) for value in _PAGE_RE.findall(markup or "")]
    return max(pages) if pages else 1


# --- Detail parsing --------------------------------------------------------
_DETAIL_FIELDS = ("City", "EntityWebSite", "EntityTypeDesc", "EntitySizeDesc")


def parse_detail_html(markup: str) -> dict[str, str]:
    """Read the fields we care about out of a company's detail popup."""
    if not markup.strip():
        return {}
    document = html_backend.parse(markup)
    values: dict[str, str] = {}

    for field in _DETAIL_FIELDS:
        node = document.css_first(f"#{field}")
        if node is not None:
            values[field] = clean(node.attr("value"))

    description = document.css_first("#Description")
    if description is not None:
        values["Description"] = truncate(strip_markup(description.text(strip=False)))
    return values


def normalise_website(value: str) -> str:
    """Make a bare host usable as a link; drop anything that is not one."""
    website = clean(value)
    if not website or "." not in website:
        return ""
    if website.startswith(("http://", "https://")):
        return website
    return f"https://{website.lstrip('/')}"


def apply_detail(company: Sme, values: dict[str, str], keywords: Sequence[str]) -> Sme:
    """Return a new `Sme` enriched with detail-popup data and derived domains."""
    description = values.get("Description", "")
    # The name often carries the signal too ("… Remote Sensing SL").
    domains, matched = derive_domains(f"{company.name} {description}", keywords)
    return replace(
        company,
        city=values.get("City", company.city),
        website=normalise_website(values.get("EntityWebSite", company.website)),
        description=description,
        entity_type=values.get("EntityTypeDesc") or company.entity_type,
        entity_size=values.get("EntitySizeDesc") or company.entity_size,
        domains=domains,
        matched_keywords=matched,
    )


# --- Fetching --------------------------------------------------------------
def _grid_params(country: str, page: int) -> dict[str, str]:
    params = {
        "term": "",
        "isForRegister": "False",
        "isForEmits": "True",
        "grid-filter": f"NationalityDesc__{_FILTER_EQUALS}__{country}",
    }
    if page > 1:
        params["grid-page"] = str(page)
    return params


def fetch_country(
    fetcher: Fetcher,
    country: str,
    max_pages: int,
    workers: int = 4,
) -> tuple[tuple[Sme, ...], tuple[str, ...]]:
    """Walk every grid page for one country.

    Page 1 is fetched first because it advertises the page count; the remaining
    pages are independent and are fetched concurrently.
    """
    errors: list[str] = []
    try:
        first = fetcher.get(
            ESASTAR_SME_GRID_URL, params=_grid_params(country, 1), headers=_XHR_HEADERS
        )
    except FetchError as exc:
        return (), (f"sme: {country} grid page 1 failed ({exc})",)

    markup = unwrap_html(first.text)
    companies: list[Sme] = list(parse_grid_html(markup))
    total_pages = min(last_page(markup), max(1, max_pages))
    LOGGER.info("sme: %s has %s grid page(s)", country, total_pages)

    def fetch_page(page: int) -> tuple[int, str | None, str]:
        try:
            response = fetcher.get(
                ESASTAR_SME_GRID_URL,
                params=_grid_params(country, page),
                headers=_XHR_HEADERS,
            )
        except FetchError as exc:
            return page, None, str(exc)
        return page, unwrap_html(response.text), ""

    remaining = range(2, total_pages + 1)
    if remaining:
        pool_size = max(1, min(workers, len(remaining)))
        with ThreadPoolExecutor(max_workers=pool_size) as pool:
            for page, page_markup, error in pool.map(fetch_page, remaining):
                if page_markup is None:
                    errors.append(f"sme: {country} grid page {page} failed ({error})")
                    continue
                companies.extend(parse_grid_html(page_markup))

    return tuple(companies), tuple(errors)


def fetch_details(
    fetcher: Fetcher,
    companies: Sequence[Sme],
    keywords: Sequence[str],
    workers: int = 6,
) -> tuple[tuple[Sme, ...], tuple[str, ...]]:
    """Enrich every company from its detail popup, concurrently.

    Companies are returned in input order. A company whose popup fails keeps its
    grid-level data and simply matches no keywords.
    """
    if not companies:
        return (), ()

    # Touch the lazily built client once up front: constructing it inside the
    # pool would race and could open several clients.
    _ = fetcher.client
    failures: list[str] = []

    def enrich(company: Sme) -> Sme:
        try:
            response = fetcher.get(company.detail_url, headers=_XHR_HEADERS)
        except FetchError as exc:
            failures.append(f"{company.name} ({exc})")
            return company
        try:
            values = parse_detail_html(unwrap_html(response.text))
        except Exception as exc:  # a single malformed popup must not stop the scan
            failures.append(f"{company.name} (parse failed: {exc})")
            return company
        return apply_detail(company, values, keywords)

    pool_size = max(1, min(workers, len(companies)))
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        enriched = tuple(pool.map(enrich, companies))

    errors: tuple[str, ...] = ()
    if failures:
        # One line, not 600: the run summary has to stay readable.
        errors = (
            f"sme: {len(failures)} detail lookup(s) failed: "
            + ", ".join(failures[:5])
            + (" …" if len(failures) > 5 else ""),
        )
    return enriched, errors


def dedupe(companies: Iterable[Sme]) -> tuple[Sme, ...]:
    """Drop repeated ids, keeping first occurrence and preserving order.

    A duplicate would otherwise cost a redundant detail fetch and collide as a
    React key in the dashboard list.
    """
    seen: set[str] = set()
    unique: list[Sme] = []
    for company in companies:
        if company.id in seen:
            continue
        seen.add(company.id)
        unique.append(company)
    return tuple(unique)


def keyword_filter(companies: Iterable[Sme]) -> tuple[Sme, ...]:
    """Keep only companies whose text matched at least one taxonomy keyword."""
    return tuple(c for c in companies if c.matched_keywords)


def scan(fetcher: Fetcher, settings: SmeSettings) -> ScanResult:
    """Fetch, enrich and filter the SME directory for the configured countries."""
    all_companies: list[Sme] = []
    errors: list[str] = []

    for country in settings.countries:
        LOGGER.info("sme: scanning %s", country)
        found, country_errors = fetch_country(
            fetcher, country, settings.max_pages, workers=settings.detail_workers
        )
        all_companies.extend(found)
        errors.extend(country_errors)

    if not all_companies:
        errors.append("sme: no companies returned by the ESA-star directory")
        return ScanResult(errors=tuple(errors))

    unique = dedupe(all_companies)
    LOGGER.info("sme: fetching %s company detail pages", len(unique))
    enriched, detail_errors = fetch_details(
        fetcher, unique, settings.keywords, workers=settings.detail_workers
    )
    errors.extend(detail_errors)

    matched = keyword_filter(enriched)
    LOGGER.info(
        "sme: %s of %s companies matched the keyword taxonomy",
        len(matched), len(enriched),
    )
    return ScanResult(
        companies=matched, scanned=len(enriched), errors=tuple(errors)
    )
