"""Persistence and change detection for `data/opportunities.json`.

The state file is both the dashboard's data source and the memory used to
decide what is *new* on the next run. Writes go through `agent.storage`, which
makes them atomic: a crash mid-write must never leave the dashboard reading a
truncated document.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from . import dates, storage
from .models import (
    STATUS_OPEN,
    ChangeEvent,
    Opportunity,
    Profile,
    Snapshot,
    index_by_id,
)

LOGGER = logging.getLogger(__name__)

# Warn about an approaching deadline once it is inside this window.
DEADLINE_SOON_DAYS = 14


def load_snapshot(path: Path) -> Snapshot:
    """Read the previous snapshot; an unreadable file yields an empty one.

    A corrupt state file is recoverable — the next run simply rebuilds it — so
    this logs and degrades rather than raising.
    """
    raw = storage.read_json(path)
    if raw is None:
        return Snapshot.empty()
    return Snapshot.from_dict(raw)


def save_snapshot(path: Path, snapshot: Snapshot, high_fit_threshold: int = 80) -> None:
    """Atomically write the snapshot to `path`."""
    storage.write_json(path, snapshot.to_dict(high_fit_threshold))
    LOGGER.info("wrote %s opportunities to %s", len(snapshot.opportunities), path)


def carry_forward(
    current: Sequence[Opportunity],
    previous: Sequence[Opportunity],
    timestamp: str | None = None,
) -> tuple[Opportunity, ...]:
    """Stamp `last_seen` and preserve each opportunity's original `first_seen`."""
    timestamp = timestamp or dates.utc_now_iso()
    previous_by_id = index_by_id(previous)
    return tuple(
        opportunity.seen_at(
            timestamp,
            first_seen=(
                previous_by_id[opportunity.id].first_seen
                if opportunity.id in previous_by_id
                and previous_by_id[opportunity.id].first_seen
                else timestamp
            ),
        )
        for opportunity in current
    )


def diff(
    previous: Sequence[Opportunity],
    current: Sequence[Opportunity],
    notify_threshold: int = 70,
    deadline_soon_days: int = DEADLINE_SOON_DAYS,
) -> tuple[ChangeEvent, ...]:
    """Detect what changed between two scrapes.

    Emits, in priority order:

    * `status_change`   — an existing opportunity changed status (Pending -> Open).
    * `new_high_match`  — a newly listed *open* opportunity scoring at or above
                          `notify_threshold`.
    * `new_opportunity` — any other newly listed opportunity (informational).
    * `deadline_soon`   — an open opportunity whose deadline is imminent
                          (informational).

    Only the first two are notifiable; see `ChangeEvent.is_notifiable`.
    """
    previous_by_id = index_by_id(previous)
    events: list[ChangeEvent] = []
    today = dates.today_utc()

    for opportunity in current:
        prior = previous_by_id.get(opportunity.id)

        if prior is None:
            # On the very first run `previous` is empty; every opportunity would
            # otherwise be "new". The caller suppresses notifications for that
            # case (see `is_first_run`).
            if (
                opportunity.status == STATUS_OPEN
                and opportunity.match_score >= notify_threshold
            ):
                events.append(
                    ChangeEvent(
                        kind="new_high_match",
                        opportunity=opportunity,
                        detail=(
                            f"New open opportunity scoring "
                            f"{opportunity.match_score}% (threshold {notify_threshold}%)"
                        ),
                    )
                )
            else:
                events.append(
                    ChangeEvent(
                        kind="new_opportunity",
                        opportunity=opportunity,
                        detail="Newly listed",
                    )
                )
            continue

        if prior.status != opportunity.status:
            events.append(
                ChangeEvent(
                    kind="status_change",
                    opportunity=opportunity,
                    previous_status=prior.status,
                    detail=f"Status changed {prior.status} -> {opportunity.status}",
                )
            )
            continue

        remaining = dates.days_until(
            dates.parse_date(opportunity.deadline, today), today
        )
        if (
            opportunity.status == STATUS_OPEN
            and remaining is not None
            and 0 <= remaining <= deadline_soon_days
        ):
            events.append(
                ChangeEvent(
                    kind="deadline_soon",
                    opportunity=opportunity,
                    detail=f"Deadline in {remaining} day(s)",
                )
            )

    events.sort(key=_event_priority)
    return tuple(events)


_EVENT_ORDER = {
    "status_change": 0,
    "new_high_match": 1,
    "deadline_soon": 2,
    "new_opportunity": 3,
}


def _event_priority(event: ChangeEvent) -> tuple[int, int]:
    """Most important events first; higher match score wins within a kind."""
    return (_EVENT_ORDER.get(event.kind, 99), -event.opportunity.match_score)


def is_first_run(previous: Snapshot) -> bool:
    """True when there is no usable prior state.

    The first run would otherwise report every opportunity as new and send a
    notification storm, so callers suppress notifications when this holds.
    """
    return not previous.opportunities


def build_snapshot(
    opportunities: Sequence[Opportunity],
    profile: Profile,
    events: Sequence[ChangeEvent] = (),
    errors: Sequence[str] = (),
    generated_at: str | None = None,
) -> Snapshot:
    """Assemble the document to persist."""
    return Snapshot(
        generated_at=generated_at or dates.utc_now_iso(),
        opportunities=tuple(opportunities),
        profile=profile,
        events=tuple(events),
        errors=tuple(errors),
    )


def sort_for_display(opportunities: Sequence[Opportunity]) -> tuple[Opportunity, ...]:
    """Order for the dashboard: open first, then by score, then by deadline."""
    status_rank = {"Open": 0, "Pending": 1, "Unknown": 2, "Closed": 3}

    def key(opportunity: Opportunity) -> tuple[int, int, str]:
        return (
            status_rank.get(opportunity.status, 4),
            -opportunity.match_score,
            opportunity.deadline or "9999-12-31",
        )

    return tuple(sorted(opportunities, key=key))


def merge_evaluations(
    current: Sequence[Opportunity], previous: Sequence[Opportunity]
) -> tuple[Opportunity, ...]:
    """Reuse a prior evaluation when the current run produced none.

    Guards against a transient LLM outage wiping scores the dashboard already
    had. Returns new objects; inputs are untouched.
    """
    previous_by_id = index_by_id(previous)
    merged: list[Opportunity] = []
    for opportunity in current:
        if opportunity.evaluation is None or opportunity.evaluation.error:
            prior = previous_by_id.get(opportunity.id)
            if prior is not None and prior.evaluation and not prior.evaluation.error:
                merged.append(replace(opportunity, evaluation=prior.evaluation))
                continue
        merged.append(opportunity)
    return tuple(merged)
