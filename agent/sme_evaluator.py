"""LLM assessment of SME companies as summer-internship targets.

Mirrors `agent/evaluator.py` — same provider, same degradation contract, same
fingerprint cache — but answers a different question: not "should I apply to
this programme?" but "is this company worth a speculative internship email, and
what should that email say?".

Two safeguards keep the cost bounded on a directory of ~600 companies:

* **Fingerprint caching.** An evaluation is keyed by company content, profile,
  model and target term. A re-scan only pays for companies whose description
  actually changed.
* **A hard budget.** `SME_MAX_EVALUATIONS` caps calls per run; the companies
  matching the most taxonomy keywords are evaluated first, so the budget is
  spent on the most relevant targets rather than alphabetically.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any, Mapping, Sequence

from . import dates
from .config import LLMSettings
from .evaluator import EvaluationError, _build_client, _profile_block, call_model
from .models import Profile
from .sme_models import Sme, SmeEvaluation

LOGGER = logging.getLogger(__name__)

MAX_WORKERS = 4
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

SYSTEM_PROMPT = """\
You are ESA Scout, advising a university student on which European space-sector \
SMEs to approach for a speculative summer internship. The companies are drawn \
from the ESA-star supplier directory, so they are all genuine ESA-registered \
suppliers, but none of them has advertised an internship — the student would be \
writing a cold email.

Judge each company on whether a cold approach is worth the student's time. \
Reserve 80-100 for companies whose actual work overlaps strongly with the \
student's demonstrated skills and where a small team plausibly has room for a \
summer student; 60-79 where the overlap is real but partial; 40-59 where the \
connection is thin or the company looks too specialised; below 40 where the \
student would be a poor fit and the email would go unanswered. A vague or \
near-empty company description is itself a reason for a lower score — do not \
reward what you cannot verify.

Respond with a single JSON object and nothing else, using exactly this shape:
{
  "fit_score": <integer 0-100>,
  "rationale": "<exactly two sentences addressed to the student, explaining the score>",
  "suggested_role": "<the specific role or project to propose, e.g. 'EO data pipeline intern'>",
  "focus_areas": ["<technical area to emphasise>", "..."],
  "outreach_tips": ["<concrete, company-specific advice for the email>", "..."]
}

Keep focus_areas to at most 3 items and outreach_tips to at most 3. Every tip \
must be specific to this company — never generic advice like "personalise your \
email" or "attach your CV".\
"""


# --- Prompt construction ---------------------------------------------------
def _company_block(company: Sme) -> str:
    fields = (
        ("Company", company.name),
        ("Country", company.country),
        ("City", company.city),
        ("Entity type", company.entity_type),
        ("Company size", company.entity_size),
        ("Website", company.website),
        ("Derived domains", ", ".join(company.domains)),
        ("Description (published by the company)", company.description),
    )
    return "\n".join(f"{label}: {value}" for label, value in fields if value)


def build_prompt(company: Sme, profile: Profile, target_term: str) -> str:
    return (
        f"Today's date is {dates.today_utc().isoformat()}.\n"
        f"The student is targeting an internship in: {target_term}, between the "
        "second and third year of their bachelor's degree.\n\n"
        f"=== STUDENT ===\n{_profile_block(profile)}\n\n"
        f"=== COMPANY ===\n{_company_block(company)}\n\n"
        "Assess this company as a speculative internship target and reply with "
        "the JSON object."
    )


def fingerprint(company: Sme, profile: Profile, model: str, target_term: str) -> str:
    """Cache key covering everything that could change an assessment."""
    payload = (
        f"{company.content_hash()}|{profile.fingerprint()}|{model}|{target_term}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# --- Response parsing ------------------------------------------------------
def parse_response(content: str, model: str, cache_key: str) -> SmeEvaluation:
    """Parse a model reply into an `SmeEvaluation`; never raises."""
    text = (content or "").strip()
    if not text:
        return SmeEvaluation(
            fit_score=0, model=model, fingerprint=cache_key, error="empty response"
        )

    payload: Any = None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK_RE.search(text)
        if match:
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                payload = None

    if not isinstance(payload, Mapping):
        return SmeEvaluation(
            fit_score=0,
            model=model,
            fingerprint=cache_key,
            error="response was not valid JSON",
        )

    return replace(
        SmeEvaluation.from_dict(payload),
        model=model,
        fingerprint=cache_key,
        evaluated_at=dates.utc_now_iso(),
        error="",
    )


# --- Orchestration ---------------------------------------------------------
def _cached_evaluations(previous: Sequence[Sme]) -> dict[str, SmeEvaluation]:
    """Index reusable prior evaluations by fingerprint."""
    return {
        company.evaluation.fingerprint: company.evaluation
        for company in previous
        if company.evaluation
        and company.evaluation.fingerprint
        and not company.evaluation.error
    }


def _relevance(item: tuple[int, Sme, str]) -> tuple[int, int, str]:
    """Budget priority: most keyword matches first, then longest description."""
    _, company, _ = item
    return (-len(company.matched_keywords), -len(company.description), company.name)


def evaluate_all(
    companies: Sequence[Sme],
    profile: Profile,
    settings: LLMSettings,
    target_term: str,
    previous: Sequence[Sme] = (),
    client: Any | None = None,
    max_evaluations: int = 40,
    max_workers: int = MAX_WORKERS,
) -> tuple[tuple[Sme, ...], tuple[str, ...]]:
    """Attach an `SmeEvaluation` to each company.

    Returns (companies, errors) in the original input order. Companies left
    unevaluated by the budget keep whatever evaluation they already had.
    """
    if not companies:
        return (), ()

    if not settings.enabled:
        message = "LLM_API_KEY not set — SME matches returned without AI ranking"
        LOGGER.warning(message)
        return tuple(companies), (message,)

    cache = _cached_evaluations(previous)
    errors: list[str] = []

    try:
        client = client or _build_client(settings)
    except EvaluationError as exc:
        message = f"LLM client unavailable: {exc}"
        LOGGER.error(message)
        return tuple(companies), (message,)

    results: list[Sme] = list(companies)
    pending: list[tuple[int, Sme, str]] = []

    for index, company in enumerate(companies):
        key = fingerprint(company, profile, settings.model, target_term)
        cached = cache.get(key)
        if cached is not None:
            results[index] = company.with_evaluation(cached)
        else:
            pending.append((index, company, key))

    budget = max(0, max_evaluations)
    if budget and len(pending) > budget:
        pending.sort(key=_relevance)
        skipped = len(pending) - budget
        LOGGER.warning(
            "%s companies need evaluation but the budget is %s; ranking the %s "
            "most relevant and leaving %s unscored",
            len(pending), budget, budget, skipped,
        )
        errors.append(
            f"SME evaluation budget reached: {skipped} company(ies) left unscored"
        )
        pending = pending[:budget]

    LOGGER.info(
        "evaluating %s companies (%s served from cache)",
        len(pending), len(companies) - len(pending),
    )

    def evaluate_one(item: tuple[int, Sme, str]) -> tuple[int, Sme]:
        index, company, key = item
        prompt = build_prompt(company, profile, target_term)
        try:
            content = call_model(client, settings, prompt, SYSTEM_PROMPT)
            evaluation = parse_response(content, settings.model, key)
        except EvaluationError as exc:
            LOGGER.warning("SME evaluation failed for %s: %s", company.name, exc)
            evaluation = SmeEvaluation(
                fit_score=0, model=settings.model, fingerprint="", error=str(exc)
            )
        return index, company.with_evaluation(evaluation)

    if pending:
        workers = max(1, min(max_workers, len(pending)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for index, evaluated in pool.map(evaluate_one, pending):
                results[index] = evaluated

    failures = [
        c.name for c in results if c.evaluation is not None and c.evaluation.error
    ]
    if failures:
        errors.append(
            f"{len(failures)} SME evaluation(s) failed: {', '.join(failures[:5])}"
            + (" …" if len(failures) > 5 else "")
        )

    return tuple(results), tuple(errors)


def merge_evaluations(
    current: Sequence[Sme], previous: Sequence[Sme]
) -> tuple[Sme, ...]:
    """Reuse a prior evaluation when this run produced none for a company.

    Protects the dashboard from a transient LLM outage blanking scores it
    already had. Returns new objects; inputs are untouched.
    """
    previous_by_id = {c.id: c for c in previous if c.id}
    merged: list[Sme] = []
    for company in current:
        if company.evaluation is None or company.evaluation.error:
            prior = previous_by_id.get(company.id)
            if prior is not None and prior.evaluation and not prior.evaluation.error:
                merged.append(company.with_evaluation(prior.evaluation))
                continue
        merged.append(company)
    return tuple(merged)
