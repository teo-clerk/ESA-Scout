"""Helpers shared by the source parsers."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ..models import Opportunity

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_MAX_SLUG_LEN = 70


def slugify(*parts: str) -> str:
    """Build a stable, URL-safe id from text fragments.

    Stability matters: the id is the key used to diff runs, so the same
    opportunity must slugify identically across scrapes.
    """
    joined = " ".join(p for p in parts if p)
    normalised = unicodedata.normalize("NFKD", joined)
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_STRIP.sub("-", ascii_only).strip("-")
    return slug[:_MAX_SLUG_LEN].strip("-") or "unknown"


@dataclass(frozen=True)
class ScrapeResult:
    """Opportunities from one or more sources, plus non-fatal errors.

    Errors are collected rather than raised so that one broken source degrades
    the run instead of ending it.
    """

    opportunities: tuple[Opportunity, ...] = ()
    errors: tuple[str, ...] = field(default=())

    def merge(self, other: "ScrapeResult") -> "ScrapeResult":
        """Combine two results into a new one (no mutation)."""
        return ScrapeResult(
            opportunities=self.opportunities + other.opportunities,
            errors=self.errors + other.errors,
        )

    @classmethod
    def failed(cls, message: str) -> "ScrapeResult":
        return cls(errors=(message,))


def clean(text: str | None) -> str:
    """Collapse whitespace and strip; `None` becomes an empty string."""
    if not text:
        return ""
    return " ".join(str(text).replace("\xa0", " ").split())


def absolutise(href: str, base: str) -> str:
    """Resolve a possibly relative href against a base URL."""
    href = clean(href)
    if not href:
        return ""
    if href.startswith(("http://", "https://", "mailto:")):
        return href
    from urllib.parse import urljoin

    return urljoin(base, href)
