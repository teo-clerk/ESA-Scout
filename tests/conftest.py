"""Shared pytest fixtures.

HTML fixtures are real pages captured from ESA in August 2026, so the parser
tests fail loudly if ESA changes its markup — which is exactly the signal we
want from a scraper's test suite.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from agent.models import (
    Evaluation,
    GitHubProfile,
    Opportunity,
    Profile,
    Repository,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# The date the HTML fixtures were captured; keeps date assertions deterministic.
REFERENCE_DATE = date(2026, 8, 17)

# Every environment variable the agent reads. `agent.config` calls `load_dotenv()`
# at import, so a developer's real `.env` would otherwise leak into the suite and
# change outcomes — a run with a real LLM_API_KEY reports no warnings and exits 0
# instead of 2. Tests must depend only on what they set themselves.
_AGENT_ENV_VARS = (
    "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_TEMPERATURE",
    "LLM_MAX_OPPORTUNITIES",
    "GITHUB_USERNAME", "GITHUB_TOKEN",
    "RESEND_API_KEY", "EMAIL_FROM", "EMAIL_TO",
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_STARTTLS",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DISCORD_WEBHOOK_URL",
    "NOTIFY_DRY_RUN", "NOTIFY_MATCH_THRESHOLD", "HIGH_FIT_THRESHOLD",
    "JOB_KEYWORDS", "MAX_JOB_PAGES", "DASHBOARD_URL",
    "HTTP_TIMEOUT", "HTTP_MAX_RETRIES", "HTTP_USER_AGENT",
    "SCRAPLING_FETCHER", "SKIP_WEB_MIRROR",
    "SME_COUNTRIES", "SME_KEYWORDS", "SME_TARGET_TERM", "SME_MAX_PAGES",
    "SME_DETAIL_WORKERS", "SME_MAX_EVALUATIONS", "SME_STRONG_FIT_THRESHOLD",
)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Run every test against a clean, credential-free environment."""
    for name in _AGENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    # Never let a test write into the developer's real web/public/data mirror.
    monkeypatch.setenv("SKIP_WEB_MIRROR", "true")


def _read(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="session")
def today() -> date:
    return REFERENCE_DATE


@pytest.fixture(scope="session")
def tlp_html() -> str:
    return _read("tlp_current_opportunities.html")


@pytest.fixture(scope="session")
def academy_html() -> str:
    return _read("esa_academy_opportunities.html")


@pytest.fixture(scope="session")
def jobs_html() -> str:
    return _read("esa_jobs_search.html")


@pytest.fixture
def profile() -> Profile:
    return Profile(
        name="Teo Clerici Jurado",
        headline="AI & Data Science student at H-Farm Campus.",
        source_file="CV.pdf",
        education=("BSc AI & Data Science, University of Chichester",),
        skills=("Python", "Machine Learning", "OpenCV", "C++"),
        highlights=("Built a multi-modal AI pipeline with Whisper and OCR.",),
        github=GitHubProfile(
            username="teoclerici",
            profile_url="https://github.com/teoclerici",
            repos=(
                Repository(
                    name="synapse",
                    description="Local multi-modal AI pipeline",
                    language="Python",
                    url="https://github.com/teoclerici/synapse",
                ),
            ),
            languages=("Python",),
        ),
    )


def make_opportunity(
    id: str = "esa-tlp-test",
    title: str = "Test Training Course",
    status: str = "Open",
    score: int | None = None,
    deadline: str = "2026-12-01",
    **overrides,
) -> Opportunity:
    """Build an Opportunity for tests, with an optional evaluation."""
    evaluation = (
        Evaluation(match_score=score, justification="Because.", fingerprint="fp-1")
        if score is not None
        else None
    )
    defaults = dict(
        id=id,
        title=title,
        source="esa_tlp",
        source_label="ESA Academy TLP",
        url="https://example.esa.int/opportunity",
        status=status,
        kind="Training Course",
        category="Space Systems",
        deadline=deadline,
        deadline_text=deadline,
        evaluation=evaluation,
    )
    defaults.update(overrides)
    return Opportunity(**defaults)


@pytest.fixture
def opportunity_factory():
    return make_opportunity
