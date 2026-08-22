"""Configuration loaded from the environment.

Every tunable lives here so no module hardcodes a URL, threshold or credential.
`Settings.load()` is the single boundary where environment values are read,
validated and coerced.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional: local development convenience
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv is optional at runtime
    pass

# --- Source URLs -----------------------------------------------------------
ESA_ACADEMY_URL = "https://www.esa.int/Education/ESA_Academy/ESA_Academy_opportunities3"
ESA_TLP_URL = "https://educationforms.esa.int/tlp/table/current-opportunities/"
ESA_JOBS_SEARCH_URL = "https://jobs.esa.int/search/"
GITHUB_API_URL = "https://api.github.com"

# --- ESA-star public SME directory -----------------------------------------
ESASTAR_BASE_URL = "https://esastar-emr.sso.esa.int"
ESASTAR_SME_PAGE_URL = f"{ESASTAR_BASE_URL}/PublicEntityDir/PublicEntityDirSme"
ESASTAR_SME_GRID_URL = f"{ESASTAR_BASE_URL}/PublicEntityDir/PublicEntityDirGridSme"
ESASTAR_SME_DETAIL_URL = f"{ESASTAR_BASE_URL}/PublicEntityDir/PublicEntityDirPopupDetailSME"

DEFAULT_SME_COUNTRIES = ("Spain", "Italy")
DEFAULT_SME_KEYWORDS = (
    "earth observation",
    "remote sensing",
    "artificial intelligence",
    "machine learning",
    "data processing",
    "software",
    "computer vision",
    "gis",
    "satellite data",
)
DEFAULT_SME_TARGET_TERM = "Summer 2027"
DEFAULT_SME_MAX_PAGES = 40
DEFAULT_SME_DETAIL_WORKERS = 6
DEFAULT_SME_MAX_EVALUATIONS = 40
DEFAULT_SME_STRONG_FIT = 70

# --- Defaults --------------------------------------------------------------
DEFAULT_LLM_BASE_URL = "https://api.x.ai/v1"
DEFAULT_LLM_MODEL = "grok-4"
DEFAULT_NOTIFY_THRESHOLD = 70
DEFAULT_HIGH_FIT_THRESHOLD = 80
DEFAULT_JOB_KEYWORDS = ("internship", "young graduate", "graduate trainee", "student")
DEFAULT_MAX_JOB_PAGES = 4
DEFAULT_TIMEOUT_SECONDS = 45.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
PROFILE_SEARCH_DIRS = (".", "agent/profile")

REPO_ROOT = Path(__file__).resolve().parent.parent


def _env_int(name: str, default: int) -> int:
    """Read an int from the environment, falling back on missing/invalid values."""
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_tuple(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Comma-separated list, lower-cased for case-insensitive matching."""
    raw = os.getenv(name)
    if not raw:
        return default
    parts = tuple(p.strip().lower() for p in raw.split(",") if p.strip())
    return parts or default


def _env_title_tuple(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Comma-separated list preserving case (country names are matched as-is)."""
    raw = os.getenv(name)
    if not raw:
        return default
    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
    return parts or default


@dataclass(frozen=True)
class LLMSettings:
    """OpenAI-compatible endpoint configuration."""

    api_key: str | None
    base_url: str
    model: str
    temperature: float
    max_opportunities: int

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class NotifierSettings:
    """Credentials for each supported notification channel."""

    resend_api_key: str | None
    email_from: str | None
    email_to: tuple[str, ...]
    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_password: str | None
    smtp_starttls: bool
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    discord_webhook_url: str | None
    dry_run: bool

    @property
    def email_enabled(self) -> bool:
        has_transport = bool(self.resend_api_key) or bool(self.smtp_host)
        return has_transport and bool(self.email_from) and bool(self.email_to)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def discord_enabled(self) -> bool:
        return bool(self.discord_webhook_url)

    @property
    def any_enabled(self) -> bool:
        return self.email_enabled or self.telegram_enabled or self.discord_enabled


@dataclass(frozen=True)
class SmeSettings:
    """Configuration for the ESA-star SME internship matcher."""

    data_file: Path
    mirror_file: Path | None
    countries: tuple[str, ...]
    keywords: tuple[str, ...]
    target_term: str
    max_pages: int
    detail_workers: int
    max_evaluations: int
    strong_fit_threshold: int


@dataclass(frozen=True)
class Settings:
    """Top-level runtime configuration."""

    data_file: Path
    mirror_file: Path | None
    sme: SmeSettings
    profile_dirs: tuple[Path, ...]
    github_username: str | None
    github_token: str | None
    llm: LLMSettings
    notifier: NotifierSettings
    notify_threshold: int
    high_fit_threshold: int
    job_keywords: tuple[str, ...]
    max_job_pages: int
    timeout: float
    max_retries: int
    user_agent: str
    use_scrapling_fetcher: bool
    dashboard_url: str | None
    sources: tuple[str, ...] = field(
        default=("esa_academy", "esa_tlp", "esa_jobs"), repr=False
    )

    @classmethod
    def load(cls, data_file: Path | None = None) -> "Settings":
        """Build settings from environment variables."""
        recipients = tuple(
            addr.strip()
            for addr in (os.getenv("EMAIL_TO") or "").split(",")
            if addr.strip()
        )
        return cls(
            data_file=data_file or REPO_ROOT / "data" / "opportunities.json",
            # Mirrored into the Next.js app because only files inside the web
            # project are guaranteed to ship in a Vercel deployment.
            mirror_file=(
                None
                if _env_bool("SKIP_WEB_MIRROR", False)
                else REPO_ROOT / "web" / "public" / "data" / "opportunities.json"
            ),
            sme=SmeSettings(
                data_file=REPO_ROOT / "data" / "sme_matches.json",
                mirror_file=(
                    None
                    if _env_bool("SKIP_WEB_MIRROR", False)
                    else REPO_ROOT / "web" / "public" / "data" / "sme_matches.json"
                ),
                countries=_env_title_tuple("SME_COUNTRIES", DEFAULT_SME_COUNTRIES),
                keywords=_env_tuple("SME_KEYWORDS", DEFAULT_SME_KEYWORDS),
                target_term=os.getenv("SME_TARGET_TERM") or DEFAULT_SME_TARGET_TERM,
                max_pages=_env_int("SME_MAX_PAGES", DEFAULT_SME_MAX_PAGES),
                detail_workers=_env_int(
                    "SME_DETAIL_WORKERS", DEFAULT_SME_DETAIL_WORKERS
                ),
                max_evaluations=_env_int(
                    "SME_MAX_EVALUATIONS", DEFAULT_SME_MAX_EVALUATIONS
                ),
                strong_fit_threshold=_env_int(
                    "SME_STRONG_FIT_THRESHOLD", DEFAULT_SME_STRONG_FIT
                ),
            ),
            profile_dirs=tuple(REPO_ROOT / d for d in PROFILE_SEARCH_DIRS),
            github_username=os.getenv("GITHUB_USERNAME") or None,
            github_token=os.getenv("GITHUB_TOKEN") or None,
            llm=LLMSettings(
                api_key=os.getenv("LLM_API_KEY") or None,
                base_url=os.getenv("LLM_BASE_URL") or DEFAULT_LLM_BASE_URL,
                model=os.getenv("LLM_MODEL") or DEFAULT_LLM_MODEL,
                temperature=_env_float("LLM_TEMPERATURE", 0.2),
                max_opportunities=_env_int("LLM_MAX_OPPORTUNITIES", 60),
            ),
            notifier=NotifierSettings(
                resend_api_key=os.getenv("RESEND_API_KEY") or None,
                email_from=os.getenv("EMAIL_FROM") or None,
                email_to=recipients,
                smtp_host=os.getenv("SMTP_HOST") or None,
                smtp_port=_env_int("SMTP_PORT", 587),
                smtp_user=os.getenv("SMTP_USER") or None,
                smtp_password=os.getenv("SMTP_PASSWORD") or None,
                smtp_starttls=_env_bool("SMTP_STARTTLS", True),
                telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
                telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
                discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL") or None,
                dry_run=_env_bool("NOTIFY_DRY_RUN", False),
            ),
            notify_threshold=_env_int("NOTIFY_MATCH_THRESHOLD", DEFAULT_NOTIFY_THRESHOLD),
            high_fit_threshold=_env_int("HIGH_FIT_THRESHOLD", DEFAULT_HIGH_FIT_THRESHOLD),
            job_keywords=_env_tuple("JOB_KEYWORDS", DEFAULT_JOB_KEYWORDS),
            max_job_pages=_env_int("MAX_JOB_PAGES", DEFAULT_MAX_JOB_PAGES),
            timeout=_env_float("HTTP_TIMEOUT", DEFAULT_TIMEOUT_SECONDS),
            max_retries=_env_int("HTTP_MAX_RETRIES", DEFAULT_MAX_RETRIES),
            user_agent=os.getenv("HTTP_USER_AGENT") or DEFAULT_USER_AGENT,
            use_scrapling_fetcher=_env_bool("SCRAPLING_FETCHER", False),
            dashboard_url=os.getenv("DASHBOARD_URL") or None,
        )
