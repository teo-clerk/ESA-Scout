"""HTTP fetching with retries and an optional Scrapling browser backend.

Default transport is httpx: it is light, dependency-stable and sufficient for
all three ESA sources, which are server-rendered. Set `SCRAPLING_FETCHER=1` (and
install the extras in requirements.txt) to route through Scrapling's
`StealthyFetcher` when a source starts requiring JS or anti-bot handling.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

LOGGER = logging.getLogger(__name__)

# Retry only on transient conditions; a 404 will never succeed on retry.
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    """Raised when a URL could not be retrieved after all retries."""


@dataclass(frozen=True)
class FetchResult:
    """A retrieved document plus the transport that produced it."""

    url: str
    status_code: int
    text: str
    backend: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class Fetcher:
    """Retrying HTTP client shared across all scrapers."""

    def __init__(
        self,
        timeout: float = 45.0,
        max_retries: int = 3,
        user_agent: str = "",
        use_scrapling: bool = False,
        backoff_base: float = 1.5,
        sleep=time.sleep,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max(1, max_retries)
        self._user_agent = user_agent
        self._use_scrapling = use_scrapling
        self._backoff_base = backoff_base
        self._sleep = sleep
        self._client: httpx.Client | None = None

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self._timeout,
                follow_redirects=True,
                headers=self._headers(),
            )
        return self._client

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
        }
        if self._user_agent:
            headers["User-Agent"] = self._user_agent
        return headers

    # -- fetching ----------------------------------------------------------
    def get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        """GET a URL, retrying transient failures with exponential backoff.

        `headers` are merged over the client defaults for this request only —
        needed by endpoints that vary their response on `X-Requested-With`.

        Raises `FetchError` when every attempt fails, so callers can degrade one
        source without losing the whole run.
        """
        if self._use_scrapling:
            scrapling_result = self._get_via_scrapling(url, params)
            if scrapling_result is not None:
                return scrapling_result

        last_error: str = "unknown error"
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self.client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                LOGGER.warning(
                    "fetch attempt %s/%s failed for %s: %s",
                    attempt, self._max_retries, url, last_error,
                )
            else:
                if response.status_code in _RETRYABLE_STATUS:
                    last_error = f"HTTP {response.status_code}"
                    LOGGER.warning(
                        "fetch attempt %s/%s got %s for %s",
                        attempt, self._max_retries, response.status_code, url,
                    )
                elif not (200 <= response.status_code < 300):
                    # Permanent failure: do not burn the remaining retries.
                    raise FetchError(f"{url} returned HTTP {response.status_code}")
                else:
                    return FetchResult(
                        url=str(response.url),
                        status_code=response.status_code,
                        text=response.text,
                        backend="httpx",
                    )
            if attempt < self._max_retries:
                self._sleep(self._backoff_base ** attempt)

        raise FetchError(f"{url} failed after {self._max_retries} attempts: {last_error}")

    def _get_via_scrapling(
        self, url: str, params: dict[str, str] | None
    ) -> FetchResult | None:
        """Try Scrapling's browser-backed fetcher; None means 'fall back'."""
        try:
            from scrapling.fetchers import StealthyFetcher
        except Exception as exc:
            LOGGER.warning(
                "SCRAPLING_FETCHER=1 but scrapling.fetchers is unavailable (%s); "
                "falling back to httpx. Install the optional extras in requirements.txt.",
                exc,
            )
            return None
        try:
            target = url
            if params:
                query = "&".join(f"{k}={v}" for k, v in params.items())
                target = f"{url}?{query}"
            page = StealthyFetcher.fetch(target, headless=True, network_idle=True)
            return FetchResult(
                url=target,
                status_code=getattr(page, "status", 200) or 200,
                text=getattr(page, "html_content", "") or str(page),
                backend="scrapling",
            )
        except Exception as exc:
            LOGGER.warning("scrapling fetch failed for %s (%s); using httpx", url, exc)
            return None
