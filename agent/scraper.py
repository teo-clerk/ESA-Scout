"""Scrape orchestration across all ESA sources.

Each source is fetched and parsed independently: a failure is recorded as an
error string and the remaining sources still run. `scrape_all` returns a single
deduplicated `ScrapeResult`.
"""

from __future__ import annotations

import logging
from datetime import date

from . import dates
from .config import (
    ESA_ACADEMY_URL,
    ESA_JOBS_SEARCH_URL,
    ESA_TLP_URL,
    Settings,
)
from .fetcher import Fetcher, FetchError
from .models import Opportunity
from .sources import academy, jobs, tlp
from .sources.common import ScrapeResult

LOGGER = logging.getLogger(__name__)


def scrape_tlp(fetcher: Fetcher, today: date | None = None) -> ScrapeResult:
    """ESA Academy Training and Learning Programme table."""
    try:
        response = fetcher.get(ESA_TLP_URL)
    except FetchError as exc:
        return ScrapeResult.failed(f"esa_tlp: fetch failed ({exc})")
    return tlp.parse_html(response.text, base_url=ESA_TLP_URL, today=today)


def scrape_academy(fetcher: Fetcher, today: date | None = None) -> ScrapeResult:
    """ESA Academy projects & testing programmes overview."""
    try:
        response = fetcher.get(ESA_ACADEMY_URL)
    except FetchError as exc:
        return ScrapeResult.failed(f"esa_academy: fetch failed ({exc})")
    return academy.parse_html(response.text, today=today)


def scrape_jobs(
    fetcher: Fetcher,
    keywords: tuple[str, ...],
    max_pages: int,
    today: date | None = None,
) -> ScrapeResult:
    """ESA careers portal, paginated until exhausted or `max_pages` reached."""
    collected: list[Opportunity] = []
    errors: list[str] = []

    for page_index in range(max(1, max_pages)):
        try:
            response = fetcher.get(
                ESA_JOBS_SEARCH_URL, params=jobs.page_params(page_index)
            )
        except FetchError as exc:
            errors.append(f"esa_jobs: fetch failed on page {page_index + 1} ({exc})")
            break

        result = jobs.parse_html(
            response.text,
            base_url=jobs.BASE_URL,
            keywords=keywords,
            today=today,
        )
        errors.extend(result.errors)

        # An empty page means we have walked past the last result.
        if not _has_tiles(response.text):
            break
        collected.extend(result.opportunities)

    return ScrapeResult(tuple(collected), tuple(errors))


def _has_tiles(markup: str) -> bool:
    """Cheap check for 'this page had results at all', independent of filtering."""
    return "job-tile" in markup


def dedupe(opportunities: tuple[Opportunity, ...]) -> tuple[Opportunity, ...]:
    """Drop repeated ids, keeping first occurrence and preserving order."""
    seen: set[str] = set()
    unique: list[Opportunity] = []
    for opportunity in opportunities:
        if opportunity.id in seen:
            continue
        seen.add(opportunity.id)
        unique.append(opportunity)
    return tuple(unique)


def scrape_all(settings: Settings, fetcher: Fetcher | None = None) -> ScrapeResult:
    """Run every enabled source and merge the results."""
    today = dates.today_utc()
    owns_fetcher = fetcher is None
    fetcher = fetcher or Fetcher(
        timeout=settings.timeout,
        max_retries=settings.max_retries,
        user_agent=settings.user_agent,
        use_scrapling=settings.use_scrapling_fetcher,
    )

    try:
        result = ScrapeResult()
        if "esa_tlp" in settings.sources:
            LOGGER.info("scraping ESA TLP opportunities table")
            result = result.merge(scrape_tlp(fetcher, today))
        if "esa_academy" in settings.sources:
            LOGGER.info("scraping ESA Academy projects overview")
            result = result.merge(scrape_academy(fetcher, today))
        if "esa_jobs" in settings.sources:
            LOGGER.info("scraping ESA careers portal")
            result = result.merge(
                scrape_jobs(
                    fetcher,
                    keywords=settings.job_keywords,
                    max_pages=settings.max_job_pages,
                    today=today,
                )
            )
    finally:
        if owns_fetcher:
            fetcher.close()

    unique = dedupe(result.opportunities)
    LOGGER.info(
        "scraped %s opportunities (%s after dedupe), %s errors",
        len(result.opportunities), len(unique), len(result.errors),
    )
    return ScrapeResult(unique, result.errors)
