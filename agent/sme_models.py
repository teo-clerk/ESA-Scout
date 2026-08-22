"""Immutable models for the ESA-star SME internship matcher.

Kept separate from `agent/models.py` so the SME feature's contract stays
cohesive and neither file grows unwieldy. The `to_dict` methods here define the
schema of `data/sme_matches.json`, mirrored in `web/lib/sme-types.ts`.

Note on `domains`: ESA-star publishes no structured activity-domain field — only
a free-text English description. Domains are therefore *derived* from that text
by keyword matching, and the UI labels them as such rather than implying ESA
supplies them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence

# ISO-3166 alpha-2 for the countries the matcher supports. Used for the flag in
# the UI and for turning ESA-star's "ES-Spain" into a clean country name.
COUNTRY_CODES: dict[str, str] = {
    "spain": "ES",
    "italy": "IT",
    "portugal": "PT",
    "france": "FR",
    "germany": "DE",
    "netherlands": "NL",
    "belgium": "BE",
    "austria": "AT",
    "poland": "PL",
    "greece": "GR",
    "romania": "RO",
    "ireland": "IE",
    "united kingdom": "GB",
}


def _tuple_of_str(values: Iterable[Any] | None) -> tuple[str, ...]:
    if not values:
        return ()
    if isinstance(values, str):
        return (values,)
    return tuple(str(v).strip() for v in values if str(v).strip())


def _clamp_score(value: Any) -> int:
    """Coerce an LLM-provided score into 0-100. Never raises."""
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, score))


@dataclass(frozen=True, slots=True)
class SmeEvaluation:
    """AI assessment of one company as a summer-internship target."""

    fit_score: int
    rationale: str = ""
    suggested_role: str = ""
    focus_areas: tuple[str, ...] = ()
    outreach_tips: tuple[str, ...] = ()
    model: str = ""
    evaluated_at: str = ""
    # Hash of (company content + profile + model + target term). Lets a later
    # run reuse this evaluation instead of paying for an identical LLM call.
    fingerprint: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "fit_score": self.fit_score,
            "rationale": self.rationale,
            "suggested_role": self.suggested_role,
            "focus_areas": list(self.focus_areas),
            "outreach_tips": list(self.outreach_tips),
            "model": self.model,
            "evaluated_at": self.evaluated_at,
            "fingerprint": self.fingerprint,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SmeEvaluation":
        return cls(
            fit_score=_clamp_score(raw.get("fit_score", raw.get("match_score"))),
            rationale=str(raw.get("rationale") or "").strip(),
            suggested_role=str(raw.get("suggested_role") or "").strip(),
            focus_areas=_tuple_of_str(raw.get("focus_areas")),
            outreach_tips=_tuple_of_str(raw.get("outreach_tips")),
            model=str(raw.get("model") or ""),
            evaluated_at=str(raw.get("evaluated_at") or ""),
            fingerprint=str(raw.get("fingerprint") or ""),
            error=str(raw.get("error") or ""),
        )


@dataclass(frozen=True, slots=True)
class Sme:
    """One company from the ESA-star public SME directory."""

    id: str
    entity_id: str
    name: str
    country: str = ""
    country_code: str = ""
    city: str = ""
    website: str = ""
    description: str = ""
    entity_type: str = ""
    entity_size: str = ""
    detail_url: str = ""
    # Derived from `description` by keyword matching — see the module docstring.
    domains: tuple[str, ...] = ()
    matched_keywords: tuple[str, ...] = ()
    evaluation: SmeEvaluation | None = None

    @property
    def fit_score(self) -> int:
        return self.evaluation.fit_score if self.evaluation else 0

    def content_hash(self) -> str:
        """Fingerprint of the company facts an evaluation depends on."""
        parts = (
            self.name,
            self.country,
            self.city,
            self.website,
            self.description,
            "|".join(self.domains),
        )
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]

    def with_evaluation(self, evaluation: SmeEvaluation | None) -> "Sme":
        return replace(self, evaluation=evaluation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "name": self.name,
            "country": self.country,
            "country_code": self.country_code,
            "city": self.city,
            "website": self.website,
            "description": self.description,
            "entity_type": self.entity_type,
            "entity_size": self.entity_size,
            "detail_url": self.detail_url,
            "domains": list(self.domains),
            "matched_keywords": list(self.matched_keywords),
            "content_hash": self.content_hash(),
            "fit_score": self.fit_score,
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Sme":
        evaluation_raw = raw.get("evaluation")
        return cls(
            id=str(raw.get("id") or ""),
            entity_id=str(raw.get("entity_id") or ""),
            name=str(raw.get("name") or ""),
            country=str(raw.get("country") or ""),
            country_code=str(raw.get("country_code") or ""),
            city=str(raw.get("city") or ""),
            website=str(raw.get("website") or ""),
            description=str(raw.get("description") or ""),
            entity_type=str(raw.get("entity_type") or ""),
            entity_size=str(raw.get("entity_size") or ""),
            detail_url=str(raw.get("detail_url") or ""),
            domains=_tuple_of_str(raw.get("domains")),
            matched_keywords=_tuple_of_str(raw.get("matched_keywords")),
            evaluation=(
                SmeEvaluation.from_dict(evaluation_raw)
                if isinstance(evaluation_raw, Mapping)
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class SmeSnapshot:
    """The complete on-disk document: `data/sme_matches.json`."""

    last_analyzed: str
    companies: tuple[Sme, ...] = ()
    countries: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    target_term: str = ""
    scanned: int = 0
    errors: tuple[str, ...] = ()
    # True when the companies carry AI evaluations; false when the scan ran
    # without an LLM key and produced keyword-only results.
    evaluated: bool = False
    version: int = 1

    def stats(self, strong_fit_threshold: int = 70) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "matched": len(self.companies),
            "evaluated": sum(
                1
                for c in self.companies
                if c.evaluation is not None and not c.evaluation.error
            ),
            "strong_fit": sum(
                1 for c in self.companies if c.fit_score >= strong_fit_threshold
            ),
            "spain": sum(1 for c in self.companies if c.country_code == "ES"),
            "italy": sum(1 for c in self.companies if c.country_code == "IT"),
        }

    def to_dict(self, strong_fit_threshold: int = 70) -> dict[str, Any]:
        return {
            "version": self.version,
            "last_analyzed": self.last_analyzed,
            "countries": list(self.countries),
            "keywords": list(self.keywords),
            "target_term": self.target_term,
            "evaluated": self.evaluated,
            "strong_fit_threshold": strong_fit_threshold,
            "stats": self.stats(strong_fit_threshold),
            "companies": [c.to_dict() for c in self.companies],
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SmeSnapshot":
        return cls(
            version=int(raw.get("version") or 1),
            last_analyzed=str(raw.get("last_analyzed") or ""),
            companies=tuple(Sme.from_dict(c) for c in (raw.get("companies") or [])),
            countries=_tuple_of_str(raw.get("countries")),
            keywords=_tuple_of_str(raw.get("keywords")),
            target_term=str(raw.get("target_term") or ""),
            scanned=int(raw.get("scanned") or (raw.get("stats") or {}).get("scanned") or 0),
            errors=_tuple_of_str(raw.get("errors")),
            evaluated=bool(raw.get("evaluated")),
        )

    @classmethod
    def empty(cls) -> "SmeSnapshot":
        return cls(last_analyzed="")


def sort_by_fit(companies: Sequence[Sme]) -> tuple[Sme, ...]:
    """Best fit first; ties broken by name so ordering is deterministic."""
    return tuple(sorted(companies, key=lambda c: (-c.fit_score, c.name.lower())))


def country_code_for(country: str) -> str:
    """ISO code for a country name, or '' when unknown."""
    return COUNTRY_CODES.get(country.strip().lower(), "")
