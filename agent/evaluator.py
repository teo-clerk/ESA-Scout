"""LLM evaluation of opportunities against the user's profile.

Uses any OpenAI-compatible endpoint (xAI/Grok, OpenRouter, Groq, OpenAI, a local
server) selected purely through `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`.

Two properties matter for cost and reliability:

* **Caching.** Each evaluation stores a fingerprint of (opportunity content +
  profile + model). On the next run an unchanged opportunity reuses its cached
  evaluation instead of paying for an identical call — so a 12-hourly cron
  normally evaluates only what actually changed.
* **Degradation.** A failed or malformed response yields an `Evaluation` with
  `error` set and a score of 0, never an exception. Losing AI enrichment must
  not lose the scrape.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import dates
from .config import LLMSettings
from .models import Evaluation, Opportunity, Profile

LOGGER = logging.getLogger(__name__)

MAX_WORKERS = 4
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

SYSTEM_PROMPT = """\
You are ESA Scout, an expert advisor on European Space Agency education and \
early-career programmes. You assess how well a specific candidate fits a \
specific ESA opportunity.

Be rigorous and honest. A high score must be earned: reserve 80-100 for \
opportunities where the candidate is a genuinely strong applicant today, \
60-79 where they are competitive but have gaps, 40-59 for a stretch, and \
below 40 where eligibility or field mismatch makes an application a poor use \
of their time. Consider academic level, field of study, demonstrated skills, \
and the practical difficulty of preparing before the deadline.

Respond with a single JSON object and nothing else, using exactly this shape:
{
  "match_score": <integer 0-100>,
  "justification": "<2-3 sentences addressed to the candidate, explaining the score>",
  "why_apply": ["<concrete benefit>", "..."],
  "required_skills": ["<skill the opportunity demands>", "..."],
  "gaps": ["<what the candidate is missing>", "..."],
  "checklist": [
    {"task": "<specific preparation action>", "effort": "<e.g. 2 hours, 1 week>",
     "done_when": "<observable completion criterion>"}
  ],
  "key_deadlines": [{"label": "<what is due>", "date": "<YYYY-MM-DD or as published>"}]
}

Keep why_apply, required_skills and gaps to at most 4 items each, and \
checklist to at most 5 items. Every checklist task must be specific to this \
candidate and this opportunity — never generic advice like "update your CV".\
"""


class EvaluationError(RuntimeError):
    """Raised internally when a provider call cannot be completed."""


# --- Prompt construction ---------------------------------------------------
def _profile_block(profile: Profile) -> str:
    """Render the candidate profile as compact prompt context."""
    lines: list[str] = []
    if profile.name:
        lines.append(f"Name: {profile.name}")
    if profile.headline:
        lines.append(f"Summary: {profile.headline}")
    if profile.education:
        lines.append("Education:")
        lines.extend(f"  - {item}" for item in profile.education[:6])
    if profile.skills:
        lines.append(f"Skills: {', '.join(profile.skills[:30])}")
    if profile.highlights:
        lines.append("Experience & projects:")
        lines.extend(f"  - {item}" for item in profile.highlights[:8])

    github = profile.github
    if github.repos:
        lines.append(f"GitHub (@{github.username}) — active repositories:")
        for repo in github.repos[:8]:
            descriptor = f"  - {repo.name}"
            if repo.language:
                descriptor += f" [{repo.language}]"
            if repo.description:
                descriptor += f": {repo.description[:120]}"
            lines.append(descriptor)
        if github.languages:
            lines.append(f"Primary languages: {', '.join(github.languages[:8])}")
    elif github.error:
        lines.append(f"GitHub: unavailable ({github.error})")

    return "\n".join(lines) or "No profile information available."


def _opportunity_block(opportunity: Opportunity) -> str:
    fields = (
        ("Title", opportunity.title),
        ("Source", opportunity.source_label),
        ("Type", opportunity.kind),
        ("Category", opportunity.category),
        ("Status", opportunity.status),
        ("Location", opportunity.location),
        ("Activity dates", opportunity.activity_dates),
        ("Application deadline", opportunity.deadline_text or opportunity.deadline),
        ("Details", opportunity.summary),
        ("URL", opportunity.url),
    )
    return "\n".join(f"{label}: {value}" for label, value in fields if value)


def build_prompt(opportunity: Opportunity, profile: Profile) -> str:
    return (
        f"Today's date is {dates.today_utc().isoformat()}.\n\n"
        f"=== CANDIDATE ===\n{_profile_block(profile)}\n\n"
        f"=== OPPORTUNITY ===\n{_opportunity_block(opportunity)}\n\n"
        "Assess this opportunity for this candidate and reply with the JSON object."
    )


def fingerprint(opportunity: Opportunity, profile: Profile, model: str) -> str:
    """Cache key covering everything that could change an evaluation."""
    payload = f"{opportunity.content_hash()}|{profile.fingerprint()}|{model}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# --- Response parsing ------------------------------------------------------
def parse_response(
    content: str, model: str, cache_key: str
) -> Evaluation:
    """Parse a model reply into an `Evaluation`.

    Providers sometimes wrap JSON in prose or a ```json fence, so we fall back
    to extracting the outermost brace-delimited block.
    """
    text = (content or "").strip()
    if not text:
        return Evaluation(
            match_score=0, model=model, fingerprint=cache_key, error="empty response"
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
        return Evaluation(
            match_score=0,
            model=model,
            fingerprint=cache_key,
            error="response was not valid JSON",
        )

    evaluation = Evaluation.from_dict(payload)
    from dataclasses import replace

    return replace(
        evaluation,
        model=model,
        fingerprint=cache_key,
        evaluated_at=dates.utc_now_iso(),
    )


# --- Provider client -------------------------------------------------------
def _build_client(settings: LLMSettings):
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
        raise EvaluationError(f"openai package unavailable: {exc}") from exc
    return OpenAI(api_key=settings.api_key, base_url=settings.base_url)


# Substrings that indicate the provider rejected the *parameter* rather than
# failing the request. Anything else (503, auth, rate limit) must surface.
_UNSUPPORTED_PARAM_MARKERS = (
    "response_format",
    "not supported",
    "unsupported",
    "unrecognized",
    "unknown parameter",
    "invalid_request_error",
    "extra fields",
)


def _is_unsupported_parameter(exc: Exception) -> bool:
    """True when the failure looks like 'this provider lacks response_format'."""
    return any(marker in str(exc).lower() for marker in _UNSUPPORTED_PARAM_MARKERS)


def call_model(
    client,
    settings: LLMSettings,
    prompt: str,
    system_prompt: str = SYSTEM_PROMPT,
) -> str:
    """One chat completion, retrying without `response_format` only if needed.

    Not every OpenAI-compatible provider supports `response_format`, so we retry
    plainly when the parameter itself was rejected. A genuine transport or
    quota error is raised instead of being retried, which would otherwise hide
    the real fault and double the request cost.

    `system_prompt` is a parameter so the SME matcher can reuse this transport
    with its own instructions instead of duplicating the retry logic.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    try:
        response = client.chat.completions.create(
            model=settings.model,
            messages=messages,
            temperature=settings.temperature,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        if not _is_unsupported_parameter(exc):
            raise EvaluationError(str(exc)) from exc
        LOGGER.debug("provider rejected response_format (%s); retrying plain", exc)
        try:
            response = client.chat.completions.create(
                model=settings.model,
                messages=messages,
                temperature=settings.temperature,
            )
        except Exception as retry_exc:
            raise EvaluationError(str(retry_exc)) from retry_exc

    choices = getattr(response, "choices", None)
    if not choices:
        raise EvaluationError("provider returned no choices")
    return choices[0].message.content or ""


# --- Orchestration ---------------------------------------------------------
def _cached_evaluations(
    previous: Sequence[Opportunity],
) -> dict[str, Evaluation]:
    """Index usable prior evaluations by their fingerprint."""
    cache: dict[str, Evaluation] = {}
    for opportunity in previous:
        evaluation = opportunity.evaluation
        if evaluation and evaluation.fingerprint and not evaluation.error:
            cache[evaluation.fingerprint] = evaluation
    return cache


def evaluate_all(
    opportunities: Sequence[Opportunity],
    profile: Profile,
    settings: LLMSettings,
    previous: Sequence[Opportunity] = (),
    client: Any | None = None,
    max_workers: int = MAX_WORKERS,
) -> tuple[tuple[Opportunity, ...], tuple[str, ...]]:
    """Attach an `Evaluation` to each opportunity.

    Returns (evaluated_opportunities, errors). Opportunities are returned in
    their original order regardless of completion order.
    """
    if not opportunities:
        return (), ()

    if not settings.enabled:
        message = "LLM_API_KEY not set — opportunities returned without AI evaluation"
        LOGGER.warning(message)
        return tuple(opportunities), (message,)

    cache = _cached_evaluations(previous)
    errors: list[str] = []

    try:
        client = client or _build_client(settings)
    except EvaluationError as exc:
        message = f"LLM client unavailable: {exc}"
        LOGGER.error(message)
        return tuple(opportunities), (message,)

    # Split into cache hits and the work that actually needs a model call.
    pending: list[tuple[int, Opportunity, str]] = []
    results: list[Opportunity] = list(opportunities)

    for index, opportunity in enumerate(opportunities):
        key = fingerprint(opportunity, profile, settings.model)
        cached = cache.get(key)
        if cached is not None:
            results[index] = opportunity.with_evaluation(cached)
        else:
            pending.append((index, opportunity, key))

    budget = max(0, settings.max_opportunities)
    if budget and len(pending) > budget:
        LOGGER.warning(
            "%s opportunities need evaluation but LLM_MAX_OPPORTUNITIES=%s; "
            "evaluating the %s most recent and leaving the rest unscored",
            len(pending), budget, budget,
        )
        errors.append(
            f"evaluation budget reached: {len(pending) - budget} opportunities left unscored"
        )
        pending = pending[:budget]

    LOGGER.info(
        "evaluating %s opportunities (%s served from cache)",
        len(pending), len(opportunities) - len(pending),
    )

    def evaluate_one(item: tuple[int, Opportunity, str]) -> tuple[int, Opportunity]:
        index, opportunity, key = item
        try:
            content = call_model(client, settings, build_prompt(opportunity, profile))
            evaluation = parse_response(content, settings.model, key)
        except EvaluationError as exc:
            LOGGER.warning("evaluation failed for %s: %s", opportunity.id, exc)
            evaluation = Evaluation(
                match_score=0, model=settings.model, fingerprint="", error=str(exc)
            )
        return index, opportunity.with_evaluation(evaluation)

    if pending:
        workers = max(1, min(max_workers, len(pending)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for index, evaluated in pool.map(evaluate_one, pending):
                results[index] = evaluated

    failures = [
        o.id for o in results if o.evaluation is not None and o.evaluation.error
    ]
    if failures:
        errors.append(
            f"{len(failures)} evaluation(s) failed: {', '.join(failures[:5])}"
            + (" ..." if len(failures) > 5 else "")
        )

    return tuple(results), tuple(errors)
