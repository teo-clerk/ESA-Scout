"""Immutable domain models shared by the pipeline and serialised to JSON.

Every model is a frozen dataclass: updates return a new instance via
`dataclasses.replace` rather than mutating in place. The `to_dict`/`from_dict`
pair defines the on-disk contract that the Next.js dashboard consumes, so keep
the two in sync with `web/lib/types.ts`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence

# Canonical status values. Anything unrecognised degrades to UNKNOWN rather
# than raising, so a source markup change never crashes the pipeline.
STATUS_OPEN = "Open"
STATUS_PENDING = "Pending"
STATUS_CLOSED = "Closed"
STATUS_UNKNOWN = "Unknown"
ALL_STATUSES = (STATUS_OPEN, STATUS_PENDING, STATUS_CLOSED, STATUS_UNKNOWN)


def _tuple_of_str(values: Iterable[Any] | None) -> tuple[str, ...]:
    """Coerce arbitrary JSON input into a tuple of non-empty strings."""
    if not values:
        return ()
    if isinstance(values, str):
        return (values,)
    return tuple(str(v).strip() for v in values if str(v).strip())


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    """One actionable preparation step produced by the evaluator."""

    task: str
    effort: str = ""
    done_when: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"task": self.task, "effort": self.effort, "done_when": self.done_when}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | str) -> "ChecklistItem":
        if isinstance(raw, str):
            return cls(task=raw)
        return cls(
            task=str(raw.get("task") or raw.get("step") or "").strip(),
            effort=str(raw.get("effort") or "").strip(),
            done_when=str(raw.get("done_when") or "").strip(),
        )


@dataclass(frozen=True, slots=True)
class KeyDeadline:
    """A date the applicant must not miss, as surfaced by the evaluator."""

    label: str
    date: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "date": self.date}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | str) -> "KeyDeadline":
        if isinstance(raw, str):
            return cls(label=raw)
        return cls(
            label=str(raw.get("label") or raw.get("name") or "").strip(),
            date=str(raw.get("date") or "").strip(),
        )


@dataclass(frozen=True, slots=True)
class Evaluation:
    """AI assessment of one opportunity against the user's profile."""

    match_score: int
    justification: str = ""
    why_apply: tuple[str, ...] = ()
    required_skills: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    checklist: tuple[ChecklistItem, ...] = ()
    key_deadlines: tuple[KeyDeadline, ...] = ()
    model: str = ""
    evaluated_at: str = ""
    # Fingerprint of (opportunity content + profile). Lets a later run reuse a
    # cached evaluation instead of paying for an identical LLM call.
    fingerprint: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_score": self.match_score,
            "justification": self.justification,
            "why_apply": list(self.why_apply),
            "required_skills": list(self.required_skills),
            "gaps": list(self.gaps),
            "checklist": [c.to_dict() for c in self.checklist],
            "key_deadlines": [d.to_dict() for d in self.key_deadlines],
            "model": self.model,
            "evaluated_at": self.evaluated_at,
            "fingerprint": self.fingerprint,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Evaluation":
        return cls(
            match_score=_clamp_score(raw.get("match_score")),
            justification=str(raw.get("justification") or "").strip(),
            why_apply=_tuple_of_str(raw.get("why_apply")),
            required_skills=_tuple_of_str(raw.get("required_skills")),
            gaps=_tuple_of_str(raw.get("gaps")),
            checklist=tuple(
                ChecklistItem.from_dict(c) for c in (raw.get("checklist") or []) if c
            ),
            key_deadlines=tuple(
                KeyDeadline.from_dict(d) for d in (raw.get("key_deadlines") or []) if d
            ),
            model=str(raw.get("model") or ""),
            evaluated_at=str(raw.get("evaluated_at") or ""),
            fingerprint=str(raw.get("fingerprint") or ""),
            error=str(raw.get("error") or ""),
        )


def _clamp_score(value: Any) -> int:
    """Coerce an LLM-provided score into 0-100. Never raises."""
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, score))


@dataclass(frozen=True, slots=True)
class Opportunity:
    """A single scouted opportunity, enriched with optional AI evaluation."""

    id: str
    title: str
    source: str
    source_label: str
    url: str
    status: str = STATUS_UNKNOWN
    kind: str = ""  # "Training Course", "Conference", "Internship", ...
    category: str = "Other"
    location: str = ""
    summary: str = ""
    activity_dates: str = ""
    activity_start: str = ""  # ISO date
    deadline_text: str = ""
    deadline: str = ""  # ISO date
    first_seen: str = ""
    last_seen: str = ""
    evaluation: Evaluation | None = None

    @property
    def match_score(self) -> int:
        return self.evaluation.match_score if self.evaluation else 0

    def content_hash(self) -> str:
        """Fingerprint of the fields that describe the opportunity itself.

        Deliberately excludes `first_seen`/`last_seen` and the evaluation so
        that a re-scrape of unchanged content produces a stable hash.
        """
        parts = (
            self.title,
            self.status,
            self.kind,
            self.location,
            self.summary,
            self.activity_dates,
            self.deadline_text,
            self.url,
        )
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]

    def with_evaluation(self, evaluation: Evaluation | None) -> "Opportunity":
        return replace(self, evaluation=evaluation)

    def seen_at(self, timestamp: str, first_seen: str | None = None) -> "Opportunity":
        return replace(self, last_seen=timestamp, first_seen=first_seen or timestamp)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "source": self.source,
            "source_label": self.source_label,
            "url": self.url,
            "status": self.status,
            "kind": self.kind,
            "category": self.category,
            "location": self.location,
            "summary": self.summary,
            "activity_dates": self.activity_dates,
            "activity_start": self.activity_start,
            "deadline_text": self.deadline_text,
            "deadline": self.deadline,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "content_hash": self.content_hash(),
            "match_score": self.match_score,
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Opportunity":
        evaluation_raw = raw.get("evaluation")
        return cls(
            id=str(raw.get("id") or ""),
            title=str(raw.get("title") or ""),
            source=str(raw.get("source") or ""),
            source_label=str(raw.get("source_label") or ""),
            url=str(raw.get("url") or ""),
            status=_normalise_status(raw.get("status")),
            kind=str(raw.get("kind") or ""),
            category=str(raw.get("category") or "Other"),
            location=str(raw.get("location") or ""),
            summary=str(raw.get("summary") or ""),
            activity_dates=str(raw.get("activity_dates") or ""),
            activity_start=str(raw.get("activity_start") or ""),
            deadline_text=str(raw.get("deadline_text") or ""),
            deadline=str(raw.get("deadline") or ""),
            first_seen=str(raw.get("first_seen") or ""),
            last_seen=str(raw.get("last_seen") or ""),
            evaluation=(
                Evaluation.from_dict(evaluation_raw)
                if isinstance(evaluation_raw, Mapping)
                else None
            ),
        )


def _normalise_status(value: Any) -> str:
    text = str(value or "").strip()
    for status in ALL_STATUSES:
        if text.lower() == status.lower():
            return status
    return STATUS_UNKNOWN


@dataclass(frozen=True, slots=True)
class Repository:
    """A public GitHub repository belonging to the user."""

    name: str
    description: str = ""
    language: str = ""
    url: str = ""
    stars: int = 0
    topics: tuple[str, ...] = ()
    pushed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "language": self.language,
            "url": self.url,
            "stars": self.stars,
            "topics": list(self.topics),
            "pushed_at": self.pushed_at,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Repository":
        return cls(
            name=str(raw.get("name") or ""),
            description=str(raw.get("description") or ""),
            language=str(raw.get("language") or ""),
            url=str(raw.get("url") or ""),
            stars=int(raw.get("stars") or 0),
            topics=_tuple_of_str(raw.get("topics")),
            pushed_at=str(raw.get("pushed_at") or ""),
        )


@dataclass(frozen=True, slots=True)
class GitHubProfile:
    """Public GitHub activity used to contextualise the evaluation."""

    username: str = ""
    profile_url: str = ""
    repos: tuple[Repository, ...] = ()
    languages: tuple[str, ...] = ()
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "profile_url": self.profile_url,
            "repos": [r.to_dict() for r in self.repos],
            "languages": list(self.languages),
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "GitHubProfile":
        return cls(
            username=str(raw.get("username") or ""),
            profile_url=str(raw.get("profile_url") or ""),
            repos=tuple(Repository.from_dict(r) for r in (raw.get("repos") or [])),
            languages=_tuple_of_str(raw.get("languages")),
            error=str(raw.get("error") or ""),
        )


@dataclass(frozen=True, slots=True)
class Profile:
    """The user's background, assembled from a CV PDF plus GitHub."""

    name: str = ""
    headline: str = ""
    source_file: str = ""
    education: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    highlights: tuple[str, ...] = ()
    raw_text: str = field(default="", repr=False)
    github: GitHubProfile = field(default_factory=GitHubProfile)
    error: str = ""

    def fingerprint(self) -> str:
        """Stable hash of everything the evaluator sees about the user."""
        payload = "|".join(
            (
                self.name,
                self.headline,
                "".join(self.education),
                "".join(self.skills),
                "".join(self.highlights),
                self.github.username,
                "".join(r.name for r in self.github.repos),
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_dict(self, include_raw: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "headline": self.headline,
            "source_file": self.source_file,
            "education": list(self.education),
            "skills": list(self.skills),
            "highlights": list(self.highlights),
            "github": self.github.to_dict(),
            "fingerprint": self.fingerprint(),
            "error": self.error,
        }
        if include_raw:
            payload["raw_text"] = self.raw_text
        return payload

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Profile":
        return cls(
            name=str(raw.get("name") or ""),
            headline=str(raw.get("headline") or ""),
            source_file=str(raw.get("source_file") or ""),
            education=_tuple_of_str(raw.get("education")),
            skills=_tuple_of_str(raw.get("skills")),
            highlights=_tuple_of_str(raw.get("highlights")),
            raw_text=str(raw.get("raw_text") or ""),
            github=GitHubProfile.from_dict(raw.get("github") or {}),
            error=str(raw.get("error") or ""),
        )


@dataclass(frozen=True, slots=True)
class ChangeEvent:
    """A notable difference between the previous and current scrape."""

    kind: str  # "status_change" | "new_high_match" | "new_opportunity" | "deadline_soon"
    opportunity: Opportunity
    previous_status: str = ""
    detail: str = ""

    @property
    def is_notifiable(self) -> bool:
        return self.kind in {"status_change", "new_high_match"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "opportunity_id": self.opportunity.id,
            "title": self.opportunity.title,
            "status": self.opportunity.status,
            "previous_status": self.previous_status,
            "match_score": self.opportunity.match_score,
            "url": self.opportunity.url,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class Snapshot:
    """The complete on-disk document: `data/opportunities.json`."""

    generated_at: str
    opportunities: tuple[Opportunity, ...] = ()
    profile: Profile = field(default_factory=Profile)
    events: tuple[ChangeEvent, ...] = ()
    errors: tuple[str, ...] = ()
    version: int = 1

    def stats(self, high_fit_threshold: int = 80) -> dict[str, int]:
        """Counters rendered in the dashboard header."""
        return {
            "total": len(self.opportunities),
            "open": sum(1 for o in self.opportunities if o.status == STATUS_OPEN),
            "pending": sum(1 for o in self.opportunities if o.status == STATUS_PENDING),
            "closed": sum(1 for o in self.opportunities if o.status == STATUS_CLOSED),
            "high_fit": sum(
                1 for o in self.opportunities if o.match_score >= high_fit_threshold
            ),
            "evaluated": sum(1 for o in self.opportunities if o.evaluation),
        }

    def to_dict(self, high_fit_threshold: int = 80) -> dict[str, Any]:
        return {
            "version": self.version,
            "generated_at": self.generated_at,
            "stats": self.stats(high_fit_threshold),
            "profile": self.profile.to_dict(),
            "opportunities": [o.to_dict() for o in self.opportunities],
            "events": [e.to_dict() for e in self.events],
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Snapshot":
        return cls(
            version=int(raw.get("version") or 1),
            generated_at=str(raw.get("generated_at") or ""),
            opportunities=tuple(
                Opportunity.from_dict(o) for o in (raw.get("opportunities") or [])
            ),
            profile=Profile.from_dict(raw.get("profile") or {}),
            errors=_tuple_of_str(raw.get("errors")),
        )

    @classmethod
    def empty(cls) -> "Snapshot":
        return cls(generated_at="")


def index_by_id(opportunities: Sequence[Opportunity]) -> dict[str, Opportunity]:
    """Build an id -> opportunity lookup (last write wins on duplicate ids)."""
    return {o.id: o for o in opportunities}
