"""One parser module per ESA source, each independently testable against a
saved HTML fixture in `tests/fixtures/`."""

from __future__ import annotations

from .common import ScrapeResult, slugify

__all__ = ["ScrapeResult", "slugify"]
