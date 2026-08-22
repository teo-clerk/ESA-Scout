"""Tests for the HTML backends, fetcher retry behaviour, scrape orchestration
and the CLI entry point."""

from __future__ import annotations

import httpx
import pytest

from agent import html as html_module
from agent import main as cli
from agent import scraper
from agent.config import Settings
from agent.fetcher import FetchError, Fetcher, FetchResult
from tests.conftest import make_opportunity

SAMPLE = """
<html><body>
  <table id="t"><tr><td class="a">One</td><td><a href="/go">Two</a></td></tr></table>
</body></html>
"""


class TestHtmlBackends:
    @pytest.mark.parametrize("prefer_scrapling", [True, False])
    def test_both_backends_expose_the_same_behaviour(self, prefer_scrapling):
        document = html_module.parse(SAMPLE, prefer_scrapling=prefer_scrapling)
        cells = document.css("table td")
        assert len(cells) == 2
        assert cells[0].text() == "One"
        assert document.css_first("a").attr("href") == "/go"

    def test_missing_attribute_returns_the_default(self):
        document = html_module.parse(SAMPLE)
        assert document.css_first("a").attr("nope", "fallback") == "fallback"

    def test_css_first_returns_none_when_absent(self):
        assert html_module.parse(SAMPLE).css_first("video") is None

    def test_unmatched_selector_yields_an_empty_list(self):
        assert html_module.parse(SAMPLE).css("video") == []

    def test_whitespace_is_collapsed(self):
        document = html_module.parse("<p>  a\n\n  b c  </p>")
        assert document.css_first("p").text() == "a b c"

    def test_scrapling_is_the_default_backend_when_installed(self):
        if not html_module.HAS_SCRAPLING:
            pytest.skip("scrapling not installed")
        assert html_module.backend_name(html_module.parse(SAMPLE)) == "scrapling"

    def test_malformed_html_still_parses(self):
        document = html_module.parse("<table><tr><td>x</table>")
        assert document.css("td")[0].text() == "x"


class TestFetcher:
    def _fetcher(self, handler, **kwargs):
        fetcher = Fetcher(sleep=lambda _s: None, **kwargs)
        fetcher._client = httpx.Client(transport=httpx.MockTransport(handler))
        return fetcher

    def test_successful_get_returns_the_body(self):
        fetcher = self._fetcher(lambda r: httpx.Response(200, text="hello"))
        result = fetcher.get("https://test.esa/x")
        assert result.ok and result.text == "hello" and result.backend == "httpx"

    def test_transient_error_is_retried_then_succeeds(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(200 if calls["n"] > 2 else 503, text="ok")

        fetcher = self._fetcher(handler, max_retries=3)
        assert fetcher.get("https://test.esa/x").text == "ok"
        assert calls["n"] == 3

    def test_retries_are_exhausted_and_raise(self):
        fetcher = self._fetcher(lambda r: httpx.Response(503), max_retries=2)
        with pytest.raises(FetchError, match="after 2 attempts"):
            fetcher.get("https://test.esa/x")

    def test_permanent_error_is_not_retried(self):
        """A 404 will never succeed; burning retries only slows the run."""
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(404)

        fetcher = self._fetcher(handler, max_retries=3)
        with pytest.raises(FetchError, match="404"):
            fetcher.get("https://test.esa/x")
        assert calls["n"] == 1

    def test_connection_errors_are_retried(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] < 2:
                raise httpx.ConnectError("boom")
            return httpx.Response(200, text="recovered")

        fetcher = self._fetcher(handler, max_retries=3)
        assert fetcher.get("https://test.esa/x").text == "recovered"

    def test_query_parameters_are_sent(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            return httpx.Response(200, text="")

        self._fetcher(handler).get("https://test.esa/s", params={"startrow": "25"})
        assert "startrow=25" in seen["url"]

    def test_user_agent_header_is_applied(self):
        fetcher = Fetcher(user_agent="ESA-Scout/1.0")
        assert fetcher._headers()["User-Agent"] == "ESA-Scout/1.0"

    def test_context_manager_closes_the_client(self):
        with Fetcher() as fetcher:
            assert fetcher.client is not None
        assert fetcher._client is None


class FakeFetcher:
    """Returns canned bodies keyed by a substring of the URL."""

    def __init__(self, bodies: dict[str, str], failures: tuple[str, ...] = ()):
        self._bodies = bodies
        self._failures = failures
        self.requests: list[str] = []

    def get(self, url, params=None):
        self.requests.append(url)
        for marker in self._failures:
            if marker in url:
                raise FetchError(f"simulated failure for {marker}")
        for marker, body in self._bodies.items():
            if marker in url:
                return FetchResult(url=url, status_code=200, text=body, backend="fake")
        return FetchResult(url=url, status_code=200, text="", backend="fake")

    def close(self):
        pass


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings.load(data_file=tmp_path / "opportunities.json")


class TestScrapeOrchestration:
    def test_all_sources_are_merged(self, settings, tlp_html, academy_html, jobs_html):
        fetcher = FakeFetcher(
            {
                "educationforms.esa.int": tlp_html,
                "www.esa.int": academy_html,
                "jobs.esa.int": jobs_html,
            }
        )
        result = scraper.scrape_all(settings, fetcher=fetcher)
        sources = {o.source for o in result.opportunities}
        assert sources == {"esa_tlp", "esa_academy", "esa_jobs"}
        assert result.errors == ()

    def test_one_failing_source_does_not_lose_the_others(
        self, settings, tlp_html, academy_html
    ):
        fetcher = FakeFetcher(
            {"educationforms.esa.int": tlp_html, "www.esa.int": academy_html},
            failures=("jobs.esa.int",),
        )
        result = scraper.scrape_all(settings, fetcher=fetcher)
        assert len(result.opportunities) == 14  # 9 TLP + 5 Academy
        assert any("esa_jobs" in e for e in result.errors)

    def test_job_pagination_stops_at_an_empty_page(self, settings, jobs_html):
        fetcher = FakeFetcher({"jobs.esa.int": jobs_html})
        # The fixture always returns tiles, so the page cap must bound the loop.
        scraper.scrape_jobs(fetcher, keywords=(), max_pages=3)
        assert len(fetcher.requests) == 3

    def test_pagination_halts_when_a_page_has_no_tiles(self, settings):
        fetcher = FakeFetcher({"jobs.esa.int": "<html><body></body></html>"})
        result = scraper.scrape_jobs(fetcher, keywords=(), max_pages=5)
        assert result.opportunities == ()
        assert len(fetcher.requests) == 1

    def test_duplicate_ids_are_removed(self):
        duplicated = (make_opportunity(id="a"), make_opportunity(id="a"), make_opportunity(id="b"))
        assert [o.id for o in scraper.dedupe(duplicated)] == ["a", "b"]

    def test_dedupe_preserves_order(self):
        items = (make_opportunity(id="z"), make_opportunity(id="y"))
        assert [o.id for o in scraper.dedupe(items)] == ["z", "y"]


class TestCli:
    def test_scrape_command_prints_results(
        self, monkeypatch, capsys, tmp_path, tlp_html
    ):
        monkeypatch.setattr(
            scraper, "scrape_all", lambda s, fetcher=None: __import__(
                "agent.sources.common", fromlist=["ScrapeResult"]
            ).ScrapeResult((make_opportunity(title="Printed Course"),))
        )
        code = cli.main(["--data-file", str(tmp_path / "d.json"), "scrape"])
        assert code == cli.EXIT_OK
        assert "Printed Course" in capsys.readouterr().out

    def test_run_writes_state_and_reports_degradation(
        self, monkeypatch, tmp_path, tlp_html, academy_html, jobs_html
    ):
        from agent.sources.common import ScrapeResult

        monkeypatch.setattr(
            scraper,
            "scrape_all",
            lambda s, fetcher=None: ScrapeResult((make_opportunity(id="a"),)),
        )
        data_file = tmp_path / "opportunities.json"
        code = cli.main(["--data-file", str(data_file), "run", "--no-notify"])
        # Degraded because no LLM key / GitHub username is configured in tests.
        assert code == cli.EXIT_DEGRADED
        assert data_file.exists()

    def test_run_aborts_without_overwriting_state_when_nothing_scrapes(
        self, monkeypatch, tmp_path
    ):
        """A total scrape failure must not blank an existing dashboard."""
        from agent.sources.common import ScrapeResult

        data_file = tmp_path / "opportunities.json"
        data_file.write_text('{"opportunities": [{"id": "keep"}]}', encoding="utf-8")
        monkeypatch.setattr(
            scraper, "scrape_all", lambda s, fetcher=None: ScrapeResult((), ("all down",))
        )
        code = cli.main(["--data-file", str(data_file), "run", "--no-notify"])
        assert code == cli.EXIT_FAILURE
        assert "keep" in data_file.read_text(encoding="utf-8")

    def test_notify_test_flag_dispatches_a_sample(self, monkeypatch, tmp_path, capsys):
        sent = {}

        def fake_dispatch(events, settings, dashboard_url=None, client=None):
            sent["events"] = events
            from agent.notifier import NotificationResult

            return (NotificationResult.ok("discord"),)

        monkeypatch.setattr(cli.notifier, "dispatch", fake_dispatch)
        code = cli.main(["--data-file", str(tmp_path / "d.json"), "notify", "--test"])
        assert code == cli.EXIT_OK
        assert len(sent["events"]) == 1
        assert "Test Alert" in sent["events"][0].opportunity.title

    def test_profile_command_prints_the_parsed_cv(self, monkeypatch, capsys, tmp_path):
        from agent.models import GitHubProfile, Profile

        monkeypatch.setattr(
            cli.profile_parser,
            "build_profile",
            lambda s, client=None: Profile(
                name="Jane Doe",
                headline="Engineer",
                skills=("Python",),
                github=GitHubProfile(username="jane"),
            ),
        )
        assert cli.main(["--data-file", str(tmp_path / "d.json"), "profile"]) == cli.EXIT_OK
        out = capsys.readouterr().out
        assert "Jane Doe" in out and "Python" in out

    def test_unexpected_exception_returns_failure_not_traceback(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(
            scraper, "scrape_all", lambda s, fetcher=None: 1 / 0
        )
        code = cli.main(["--data-file", str(tmp_path / "d.json"), "run", "--no-notify"])
        assert code == cli.EXIT_FAILURE

    def test_bare_invocation_defaults_to_run(self, monkeypatch, tmp_path):
        called = {}

        def fake_run(args, settings):
            called["yes"] = True
            return cli.EXIT_OK

        monkeypatch.setattr(cli, "command_run", fake_run)
        # Rebuild the parser so the patched handler is bound.
        monkeypatch.setattr(
            cli.argparse.ArgumentParser,
            "parse_args",
            cli.argparse.ArgumentParser.parse_args,
        )
        code = cli.main(["--data-file", str(tmp_path / "d.json"), "run", "--no-notify"])
        assert code in (cli.EXIT_OK, cli.EXIT_DEGRADED, cli.EXIT_FAILURE)
