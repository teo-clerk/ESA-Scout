"""Persistence for `data/sme_matches.json`.

Thin counterpart to `agent/state_manager.py`: the SME feature has no change
detection (a supplier directory does not "open" or "close"), so this only needs
load, save and assembly. Writes are atomic — see `agent.storage`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from . import dates, storage
from .sme_models import Sme, SmeSnapshot, sort_by_fit

LOGGER = logging.getLogger(__name__)


def load_snapshot(path: Path) -> SmeSnapshot:
    """Read the previous SME snapshot; an unreadable file yields an empty one."""
    raw = storage.read_json(path)
    if raw is None:
        return SmeSnapshot.empty()
    return SmeSnapshot.from_dict(raw)


def save_snapshot(
    path: Path, snapshot: SmeSnapshot, strong_fit_threshold: int = 70
) -> None:
    """Atomically write the SME snapshot to `path`."""
    storage.write_json(path, snapshot.to_dict(strong_fit_threshold))
    LOGGER.info("wrote %s companies to %s", len(snapshot.companies), path)


def build_snapshot(
    companies: Sequence[Sme],
    countries: Sequence[str],
    keywords: Sequence[str],
    target_term: str,
    scanned: int = 0,
    errors: Sequence[str] = (),
    evaluated: bool = False,
    last_analyzed: str | None = None,
) -> SmeSnapshot:
    """Assemble the document to persist, best fit first."""
    return SmeSnapshot(
        last_analyzed=last_analyzed or dates.utc_now_iso(),
        companies=sort_by_fit(companies),
        countries=tuple(countries),
        keywords=tuple(keywords),
        target_term=target_term,
        scanned=scanned,
        errors=tuple(errors),
        evaluated=evaluated,
    )
