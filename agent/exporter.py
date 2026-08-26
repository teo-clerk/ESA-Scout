"""Markdown export of the two snapshots the agent produces.

The dashboard is the interactive view; this module is the portable one. It
turns `data/opportunities.json` and `data/sme_matches.json` into documents you
can commit, print, paste into a notebook or hand to a careers advisor.

Rendering is deliberately pure — `render_*` takes a snapshot and returns a
string — so the output can be asserted in tests without touching the disk, and
so the Next.js dashboard can mirror the same layout in `web/lib/markdown.ts`.
Keep the two in sync: the headings, table columns and anchor slugs there are a
port of the ones here.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

from . import dates
from .models import Opportunity, Snapshot
from .sme_models import Sme, SmeSnapshot

LOGGER = logging.getLogger(__name__)

OPPORTUNITIES_FILENAME = "OPPORTUNITIES.md"
SME_FILENAME = "SME_TARGETS.md"

# Long prose reads badly inside a table cell, so summary columns are clipped
# and the full text appears in the item's own section below.
_CELL_LIMIT = 90


# --- Markdown primitives ---------------------------------------------------
# GitHub builds a heading anchor by lower-casing, dropping punctuation and
# turning spaces into hyphens. Reproduced here so the table of contents links
# actually resolve — including on the em dashes used in item headings.
_SLUG_DROP = re.compile(r"[^\w\- ]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def slugify(text: str) -> str:
    """GitHub-compatible heading anchor for `text`."""
    collapsed = _WHITESPACE.sub(" ", text).strip().lower()
    return _SLUG_DROP.sub("", collapsed).replace(" ", "-")


class AnchorAllocator:
    """Hands out unique anchors, suffixing duplicates the way GitHub does."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def take(self, heading: str) -> str:
        base = slugify(heading)
        count = self._seen.get(base, 0)
        self._seen[base] = count + 1
        return base if count == 0 else f"{base}-{count}"


def _inline(text: str) -> str:
    """Collapse a value to a single line so it cannot break a table row."""
    return _WHITESPACE.sub(" ", str(text or "")).strip()


def _cell(text: str, limit: int = 0) -> str:
    """Escape a value for use inside a Markdown table cell."""
    value = _inline(text).replace("|", "\\|")
    if limit and len(value) > limit:
        value = value[: limit - 1].rstrip() + "…"
    return value or "—"


def _table(headers: Sequence[str], aligns: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    """A GitHub table; `aligns` entries are 'left', 'right' or 'center'."""
    rules = {"right": "---:", "center": ":---:", "left": "---"}
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(rules.get(a, "---") for a in aligns) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def _bullets(items: Sequence[str]) -> list[str]:
    return [f"- {_inline(item)}" for item in items if _inline(item)]


def _tags(values: Sequence[str]) -> str:
    """Inline code chips, e.g. `Python` · `OpenCV`."""
    kept = [_inline(v) for v in values if _inline(v)]
    return " · ".join(f"`{v}`" for v in kept) if kept else "—"


def _link(label: str, url: str) -> str:
    """A Markdown link, or the bare label when there is no URL."""
    text = _inline(label) or "link"
    return f"[{text}]({_inline(url)})" if url else text


def _section(lines: list[str], heading: str, body: Sequence[str]) -> None:
    """Append `heading` plus `body` only when there is something to show."""
    if not body:
        return
    lines.extend(("", heading, ""))
    lines.extend(body)


def _score(value: int) -> str:
    """Score for a table cell; an em dash keeps unscored columns aligned."""
    return f"{value}%" if value else "—"


def _rank_label(value: int, absent: str) -> str:
    """Score for a heading, where a bare dash would read as a missing title."""
    return f"{value}%" if value else absent


_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def format_date(iso: str, fallback: str = "") -> str:
    """'5 April 2026' from an ISO date, falling back to the published wording.

    Deliberately strict rather than reusing `agent.dates.parse_date`: this must
    behave identically to `formatDate` in `web/lib/format.ts`, which only ever
    sees an ISO prefix.
    """
    match = _ISO_DATE.match(_inline(iso))
    if match is None:
        return _inline(fallback)
    year, month, day = (int(part) for part in match.groups())
    if not 1 <= month <= 12:
        return _inline(fallback)
    return f"{day} {_MONTH_NAMES[month - 1]} {year}"


def _stamp(generated_on: date | None) -> str:
    return (generated_on or dates.today_utc()).isoformat()


# --- Opportunities ---------------------------------------------------------
def render_opportunities(
    snapshot: Snapshot,
    high_fit_threshold: int = 80,
    generated_on: date | None = None,
) -> str:
    """Render `data/opportunities.json` as a standalone Markdown document."""
    stats = snapshot.stats(high_fit_threshold)
    items = sorted(snapshot.opportunities, key=lambda o: (-o.match_score, o.title.lower()))
    anchors = AnchorAllocator()
    headings = [
        f"{_rank_label(o.match_score, 'Unscored')} — {_inline(o.title)}" for o in items
    ]
    # Allocate every anchor up front so the contents list and the sections
    # below agree on the duplicate suffixes.
    slugs = [anchors.take(heading) for heading in headings]

    lines = [
        "# ESA Scout — Opportunities",
        "",
        f"> Exported {_stamp(generated_on)} · data collected "
        f"{_inline(snapshot.generated_at) or 'never'}.",
    ]
    if snapshot.profile.name:
        lines.append(f"> Scored against **{_inline(snapshot.profile.name)}**"
                     f"{_profile_suffix(snapshot)}.")

    lines.extend(("", "## At a glance", ""))
    lines.extend(
        _table(
            ("Metric", "Count"),
            ("left", "right"),
            (
                ("Open now", str(stats["open"])),
                (f"High fit ≥ {high_fit_threshold}%", str(stats["high_fit"])),
                ("Pending cycles", str(stats["pending"])),
                ("Closed", str(stats["closed"])),
                ("AI-evaluated", str(stats["evaluated"])),
                ("Tracked total", str(stats["total"])),
            ),
        )
    )

    lines.extend(("", "## Contents", ""))
    if items:
        lines.append("- [Summary](#summary)")
        lines.append("- [Opportunities](#opportunities)")
        lines.extend(
            f"  - [{heading}](#{slug})" for heading, slug in zip(headings, slugs)
        )
    else:
        lines.append("- Nothing tracked yet — run `python -m agent.main run`.")

    lines.extend(("", "## Summary", ""))
    lines.extend(
        _table(
            ("Fit", "Title", "Status", "Deadline", "Link"),
            ("right", "left", "left", "left", "left"),
            (
                (
                    _score(o.match_score),
                    _cell(o.title, _CELL_LIMIT),
                    _cell(o.status),
                    _cell(format_date(o.deadline, o.deadline_text), _CELL_LIMIT),
                    _link("Open", o.url) if o.url else "—",
                )
                for o in items
            ),
        )
        if items
        else ["_No opportunities in this snapshot._"]
    )

    if items:
        lines.extend(("", "## Opportunities"))
        for opportunity, heading, slug in zip(items, headings, slugs):
            lines.extend(("", f"### {heading}"))
            lines.extend(_opportunity_body(opportunity))
            lines.append("")
            lines.append("---")

    lines.extend(_warnings(snapshot.errors))
    return "\n".join(lines).rstrip() + "\n"


def _profile_suffix(snapshot: Snapshot) -> str:
    github = snapshot.profile.github.username
    source = snapshot.profile.source_file
    parts = [p for p in (source, f"GitHub @{github}" if github else "") if p]
    return f" ({' + '.join(parts)})" if parts else ""


def _opportunity_body(opportunity: Opportunity) -> list[str]:
    """The facts, AI assessment and checklist for one opportunity."""
    facts: list[tuple[str, str]] = [
        ("Status", opportunity.status),
        ("Fit score", f"{opportunity.match_score}%" if opportunity.match_score else ""),
        ("Source", opportunity.source_label or opportunity.source),
        ("Category", opportunity.category),
        ("Kind", opportunity.kind),
        ("Location", opportunity.location),
        ("Activity dates", opportunity.activity_dates),
        ("Deadline", format_date(opportunity.deadline, opportunity.deadline_text)),
        ("First seen", opportunity.first_seen),
        ("Last seen", opportunity.last_seen),
    ]
    lines = ["", *[f"- **{label}:** {_inline(value)}" for label, value in facts if _inline(value)]]

    if opportunity.summary:
        lines.extend(("", _inline(opportunity.summary)))

    evaluation = opportunity.evaluation
    if evaluation is None:
        lines.extend(("", "_Not evaluated yet._"))
    elif evaluation.error:
        lines.extend(("", f"> Evaluation failed: {_inline(evaluation.error)}"))
    else:
        _section(lines, "#### AI justification", [_inline(evaluation.justification)]
                 if evaluation.justification else [])
        _section(lines, "#### Why apply", _bullets(evaluation.why_apply))
        _section(lines, "#### Required skills", [_tags(evaluation.required_skills)]
                 if evaluation.required_skills else [])
        _section(lines, "#### Gaps to close", _bullets(evaluation.gaps))
        _section(lines, "#### Preparation checklist", _checklist(evaluation.checklist))
        _section(lines, "#### Key deadlines", _key_deadlines(evaluation.key_deadlines))
        if evaluation.model:
            lines.extend(
                ("", f"_Scored by {_inline(evaluation.model)}"
                 f"{' on ' + _inline(evaluation.evaluated_at) if evaluation.evaluated_at else ''}._")
            )

    links = [f"- {_link('Opportunity page', opportunity.url)}"] if opportunity.url else []
    _section(lines, "#### Links", links)
    return lines


def _checklist(items: Sequence) -> list[str]:
    """Checklist entries as GitHub task-list items with their metadata."""
    lines: list[str] = []
    for item in items:
        task = _inline(item.task)
        if not task:
            continue
        lines.append(f"- [ ] {task}")
        if item.effort:
            lines.append(f"  - Effort: {_inline(item.effort)}")
        if item.done_when:
            lines.append(f"  - Done when: {_inline(item.done_when)}")
    return lines


def _key_deadlines(items: Sequence) -> list[str]:
    rows = [
        (_cell(item.label), _cell(format_date(item.date, item.date)))
        for item in items
        if _inline(item.label)
    ]
    return _table(("Milestone", "Date"), ("left", "left"), rows) if rows else []


# --- SME targets -----------------------------------------------------------
def render_sme_targets(
    snapshot: SmeSnapshot,
    strong_fit_threshold: int = 70,
    generated_on: date | None = None,
) -> str:
    """Render `data/sme_matches.json` as a standalone Markdown document."""
    stats = snapshot.stats(strong_fit_threshold)
    items = sorted(snapshot.companies, key=lambda c: (-c.fit_score, c.name.lower()))
    anchors = AnchorAllocator()
    headings = [
        f"{_rank_label(c.fit_score, 'Unranked')} — {_inline(c.name)}" for c in items
    ]
    slugs = [anchors.take(heading) for heading in headings]

    term = _inline(snapshot.target_term) or "the target term"
    countries = " and ".join(snapshot.countries) or "the configured countries"

    lines = [
        "# ESA Scout — SME Internship Targets",
        "",
        f"> Exported {_stamp(generated_on)} · directory analysed "
        f"{_inline(snapshot.last_analyzed) or 'never'}.",
        f"> ESA-registered SMEs in {countries}, ranked as speculative "
        f"**{term}** internship targets.",
        "",
        "None of these companies has advertised an internship — treat every one "
        "as a cold approach.",
        "",
        "## At a glance",
        "",
    ]
    lines.extend(
        _table(
            ("Metric", "Count"),
            ("left", "right"),
            (
                ("Companies scanned", str(stats["scanned"])),
                ("Keyword matches", str(stats["matched"])),
                ("AI-ranked", str(stats["evaluated"])),
                (f"Strong fit ≥ {strong_fit_threshold}%", str(stats["strong_fit"])),
                ("Spain", str(stats["spain"])),
                ("Italy", str(stats["italy"])),
            ),
        )
    )
    if snapshot.keywords:
        lines.extend(("", f"**Keyword filter:** {_tags(snapshot.keywords)}"))
    if not snapshot.evaluated and snapshot.companies:
        lines.extend(
            ("", "> These companies matched the keyword filter but have not been "
             "ranked yet. Re-run with `--evaluate` once `LLM_API_KEY` is set.")
        )

    lines.extend(("", "## Contents", ""))
    if items:
        lines.append("- [Summary](#summary)")
        lines.append("- [Companies](#companies)")
        lines.extend(
            f"  - [{heading}](#{slug})" for heading, slug in zip(headings, slugs)
        )
    else:
        lines.append("- Nothing matched yet — run `python -m agent.main sme --evaluate`.")

    lines.extend(("", "## Summary", ""))
    lines.extend(
        _table(
            ("Fit", "Company", "Country", "City", "Domains", "Link"),
            ("right", "left", "left", "left", "left", "left"),
            (
                (
                    _score(c.fit_score),
                    _cell(c.name, _CELL_LIMIT),
                    _cell(c.country_code or c.country),
                    _cell(c.city),
                    _cell(", ".join(c.domains), _CELL_LIMIT),
                    _link("Site", c.website) if c.website else _link("ESA-star", c.detail_url),
                )
                for c in items
            ),
        )
        if items
        else ["_No companies in this snapshot._"]
    )

    if items:
        lines.extend(("", "## Companies"))
        for company, heading in zip(items, headings):
            lines.extend(("", f"### {heading}"))
            lines.extend(_sme_body(company, term))
            lines.append("")
            lines.append("---")

    lines.extend(_warnings(snapshot.errors))
    return "\n".join(lines).rstrip() + "\n"


def _sme_body(company: Sme, term: str) -> list[str]:
    """The facts, inferred domains and outreach advice for one company."""
    location = ", ".join(p for p in (company.city, company.country) if p)
    facts: list[tuple[str, str]] = [
        ("Fit score", f"{company.fit_score}%" if company.fit_score else ""),
        ("Location", location),
        ("Entity type", company.entity_type),
        ("Entity size", company.entity_size),
        ("Website", f"<{company.website}>" if company.website else ""),
        ("ESA-star entry", _link(company.entity_id or "detail", company.detail_url)
         if company.detail_url else ""),
    ]
    lines = ["", *[f"- **{label}:** {_inline(value)}" for label, value in facts if _inline(value)]]

    if company.domains:
        lines.append(f"- **Domain tags (inferred):** {_tags(company.domains)}")
    if company.matched_keywords:
        lines.append(f"- **Matched keywords:** {_tags(company.matched_keywords)}")
    if company.description:
        lines.extend(("", _inline(company.description)))

    evaluation = company.evaluation
    if evaluation is None:
        lines.extend(("", "_Not ranked yet._"))
    elif evaluation.error:
        lines.extend(("", f"> Ranking failed: {_inline(evaluation.error)}"))
    else:
        _section(lines, f"#### Why this fits for {term}",
                 [_inline(evaluation.rationale)] if evaluation.rationale else [])
        _section(lines, "#### Suggested role",
                 [_inline(evaluation.suggested_role)] if evaluation.suggested_role else [])
        _section(lines, "#### Focus areas",
                 [_tags(evaluation.focus_areas)] if evaluation.focus_areas else [])
        _section(lines, "#### Outreach advice", _bullets(evaluation.outreach_tips))
        if evaluation.model:
            lines.extend(
                ("", f"_Ranked by {_inline(evaluation.model)}"
                 f"{' on ' + _inline(evaluation.evaluated_at) if evaluation.evaluated_at else ''}._")
            )
    return lines


def _warnings(errors: Sequence[str]) -> list[str]:
    """A trailing section listing the warnings the run recorded."""
    if not errors:
        return []
    return ["", f"## Warnings ({len(errors)})", "", *_bullets(errors)]


# --- File output -----------------------------------------------------------
def write_opportunities(
    snapshot: Snapshot,
    output_dir: Path,
    high_fit_threshold: int = 80,
    generated_on: date | None = None,
) -> Path:
    """Write `OPPORTUNITIES.md` into `output_dir` and return its path."""
    return _write(
        output_dir / OPPORTUNITIES_FILENAME,
        render_opportunities(snapshot, high_fit_threshold, generated_on),
    )


def write_sme_targets(
    snapshot: SmeSnapshot,
    output_dir: Path,
    strong_fit_threshold: int = 70,
    generated_on: date | None = None,
) -> Path:
    """Write `SME_TARGETS.md` into `output_dir` and return its path."""
    return _write(
        output_dir / SME_FILENAME,
        render_sme_targets(snapshot, strong_fit_threshold, generated_on),
    )


def _write(path: Path, markdown: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    LOGGER.info("wrote %s (%s bytes)", path, len(markdown.encode("utf-8")))
    return path
