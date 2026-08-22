"""Tests for the ESA-star SME scraper: grid parsing, detail parsing, filtering.

Fixtures are real ESA-star payloads captured in August 2026, so these tests fail
loudly if ESA-star changes its markup — the signal a scraper's suite must give.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.config import DEFAULT_SME_KEYWORDS, SmeSettings
from agent.fetcher import FetchError, FetchResult
from agent.sources import sme_matcher

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def grid_payload() -> str:
    return _fixture("sme_grid_spain.json")


@pytest.fixture(scope="session")
def grid_html(grid_payload: str) -> str:
    return sme_matcher.unwrap_html(grid_payload)


@pytest.fixture(scope="session")
def detail_3edata() -> str:
    return _fixture("sme_detail_3edata.json")


@pytest.fixture(scope="session")
def detail_abionica() -> str:
    return _fixture("sme_detail_abionica.json")


@pytest.fixture
def sme_settings(tmp_path) -> SmeSettings:
    return SmeSettings(
        data_file=tmp_path / "sme_matches.json",
        mirror_file=None,
        countries=("Spain",),
        keywords=DEFAULT_SME_KEYWORDS,
        target_term="Summer 2027",
        max_pages=2,
        detail_workers=2,
        max_evaluations=10,
        strong_fit_threshold=70,
    )


class StubFetcher:
    """Serves fixture payloads and records the requests the scraper makes."""

    def __init__(self, grid_pages: dict[int, str], details: dict[str, str]):
        self._grid_pages = grid_pages
        self._details = details
        self.requests: list[tuple[str, dict, dict]] = []
        self.client = object()  # the real Fetcher exposes a lazily built client

    def get(self, url, params=None, headers=None):
        self.requests.append((url, dict(params or {}), dict(headers or {})))
        if "PopupDetailSME" in url:
            entity_id = url.rsplit("/", 1)[-1]
            if entity_id not in self._details:
                raise FetchError(f"no detail fixture for {entity_id}")
            return FetchResult(url, 200, self._details[entity_id], "stub")
        page = int((params or {}).get("grid-page", 1))
        if page not in self._grid_pages:
            raise FetchError(f"no grid fixture for page {page}")
        return FetchResult(url, 200, self._grid_pages[page], "stub")


class TestUnwrapHtml:
    def test_json_envelope_is_unwrapped(self):
        assert sme_matcher.unwrap_html('{"html": "<p>hi</p>"}') == "<p>hi</p>"

    def test_bare_html_passes_through(self):
        assert sme_matcher.unwrap_html("<p>hi</p>") == "<p>hi</p>"

    def test_malformed_json_is_returned_unchanged(self):
        assert sme_matcher.unwrap_html("{not json") == "{not json"

    def test_empty_payload_is_empty(self):
        assert sme_matcher.unwrap_html("") == ""


class TestGridParsing:
    def test_every_row_becomes_a_company(self, grid_html):
        companies = sme_matcher.parse_grid_html(grid_html)
        assert len(companies) == 20

    def test_row_fields_are_read_by_column_name(self, grid_html):
        first = sme_matcher.parse_grid_html(grid_html)[0]
        assert first.name == "3edata ingeniería ambiental sl"
        assert first.entity_id == "136835"
        assert first.entity_type == "Company"
        assert first.detail_url.endswith("/PublicEntityDirPopupDetailSME/136835")

    def test_nationality_is_split_into_name_and_code(self, grid_html):
        first = sme_matcher.parse_grid_html(grid_html)[0]
        assert (first.country, first.country_code) == ("Spain", "ES")

    def test_ids_are_stable_and_unique(self, grid_html):
        companies = sme_matcher.parse_grid_html(grid_html)
        again = sme_matcher.parse_grid_html(grid_html)
        assert [c.id for c in companies] == [c.id for c in again]
        assert len({c.id for c in companies}) == len(companies)

    def test_pager_reports_the_last_page(self, grid_html):
        assert sme_matcher.last_page(grid_html) == 10

    def test_missing_pager_means_a_single_page(self):
        assert sme_matcher.last_page("<table></table>") == 1

    def test_row_without_a_detail_link_is_skipped(self):
        markup = (
            '<tr class="grid-row"><td class="grid-cell" data-name="Name">Acme</td>'
            '<td class="grid-cell" data-name="EntityId"></td></tr>'
        )
        assert sme_matcher.parse_grid_html(markup) == ()

    def test_empty_markup_yields_nothing(self):
        assert sme_matcher.parse_grid_html("") == ()


class TestDetailParsing:
    def test_city_and_website_are_extracted(self, detail_3edata):
        values = sme_matcher.parse_detail_html(
            sme_matcher.unwrap_html(detail_3edata)
        )
        assert values["City"] == "Lugo"
        assert values["EntityWebSite"] == "https://3edata.es"

    def test_description_markup_is_stripped_to_plain_text(self, detail_3edata):
        values = sme_matcher.parse_detail_html(
            sme_matcher.unwrap_html(detail_3edata)
        )
        description = values["Description"]
        assert "<strong>" not in description and "&lt;" not in description
        assert description.startswith("We are a technology-based company")
        assert "multispectral and LiDAR sensors" in description

    def test_empty_website_stays_empty(self, detail_abionica):
        values = sme_matcher.parse_detail_html(
            sme_matcher.unwrap_html(detail_abionica)
        )
        assert values["EntityWebSite"] == ""
        assert values["City"] == "ALICANTE"

    def test_empty_markup_yields_no_fields(self):
        assert sme_matcher.parse_detail_html("") == {}


class TestStripMarkup:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("<strong>bold</strong> text", "bold text"),
            ("&lt;strong&gt;escaped&lt;/strong&gt; text", "escaped text"),
            ("line one&lt;br /&gt;line two", "line one line two"),
            ("caf&amp;eacute;", "café"),
            ("", ""),
        ],
    )
    def test_markup_and_entities_are_removed(self, raw, expected):
        assert sme_matcher.strip_markup(raw) == expected

    def test_long_text_is_truncated_on_a_word_boundary(self):
        text = "word " * 100
        result = sme_matcher.truncate(text.strip(), limit=20)
        assert result.endswith("…") and len(result) <= 21
        assert "wor…" not in result  # never cuts mid-word


class TestWebsiteNormalisation:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("https://3edata.es", "https://3edata.es"),
            ("http://x.com", "http://x.com"),
            ("www.example.com", "https://www.example.com"),
            ("example.it", "https://example.it"),
            ("", ""),
            ("n/a", ""),
            ("   ", ""),
        ],
    )
    def test_bare_hosts_gain_a_scheme_and_junk_is_dropped(self, raw, expected):
        assert sme_matcher.normalise_website(raw) == expected


class TestDomainDerivation:
    def test_keywords_are_matched_case_insensitively(self):
        domains, matched = sme_matcher.derive_domains(
            "We do Machine Learning and Earth Observation.", DEFAULT_SME_KEYWORDS
        )
        assert "Machine Learning" in domains and "Earth Observation" in domains
        assert set(matched) == {"machine learning", "earth observation"}

    def test_gis_does_not_match_inside_another_word(self):
        _, matched = sme_matcher.derive_domains(
            "A logistics and registration provider.", DEFAULT_SME_KEYWORDS
        )
        assert "gis" not in matched

    def test_gis_matches_as_a_standalone_word(self):
        domains, matched = sme_matcher.derive_domains(
            "We build GIS platforms.", DEFAULT_SME_KEYWORDS
        )
        assert domains == ("GIS",) and matched == ("gis",)

    def test_aliases_catch_equivalent_phrasing(self):
        _, matched = sme_matcher.derive_domains(
            "Drones with multispectral and LiDAR sensors.", DEFAULT_SME_KEYWORDS
        )
        assert "remote sensing" in matched

    def test_domains_follow_taxonomy_order_not_text_order(self):
        first, _ = sme_matcher.derive_domains(
            "software then machine learning", DEFAULT_SME_KEYWORDS
        )
        second, _ = sme_matcher.derive_domains(
            "machine learning then software", DEFAULT_SME_KEYWORDS
        )
        assert first == second

    def test_unrelated_text_matches_nothing(self):
        assert sme_matcher.derive_domains("A catering company.", DEFAULT_SME_KEYWORDS) == ((), ())

    def test_empty_text_matches_nothing(self):
        assert sme_matcher.derive_domains("", DEFAULT_SME_KEYWORDS) == ((), ())


class TestApplyDetail:
    def test_detail_data_enriches_the_grid_stub(self, grid_html, detail_3edata):
        stub = sme_matcher.parse_grid_html(grid_html)[0]
        values = sme_matcher.parse_detail_html(sme_matcher.unwrap_html(detail_3edata))
        enriched = sme_matcher.apply_detail(stub, values, DEFAULT_SME_KEYWORDS)
        assert enriched.city == "Lugo"
        assert enriched.website == "https://3edata.es"
        assert "Remote Sensing" in enriched.domains

    def test_the_stub_is_not_mutated(self, grid_html, detail_3edata):
        stub = sme_matcher.parse_grid_html(grid_html)[0]
        values = sme_matcher.parse_detail_html(sme_matcher.unwrap_html(detail_3edata))
        sme_matcher.apply_detail(stub, values, DEFAULT_SME_KEYWORDS)
        assert stub.city == "" and stub.domains == ()

    def test_the_company_name_also_feeds_domain_derivation(self):
        from agent.sme_models import Sme

        stub = Sme(id="x", entity_id="1", name="Iberian Remote Sensing SL")
        enriched = sme_matcher.apply_detail(stub, {"Description": ""}, DEFAULT_SME_KEYWORDS)
        assert enriched.domains == ("Remote Sensing",)


class TestFetching:
    def test_grid_requests_declare_themselves_as_xhr(self, grid_payload):
        fetcher = StubFetcher({1: grid_payload}, {})
        sme_matcher.fetch_country(fetcher, "Spain", max_pages=1)
        _, _, headers = fetcher.requests[0]
        assert headers["X-Requested-With"] == "XMLHttpRequest"

    def test_country_filter_uses_the_gridmvc_equals_operator(self, grid_payload):
        fetcher = StubFetcher({1: grid_payload}, {})
        sme_matcher.fetch_country(fetcher, "Spain", max_pages=1)
        _, params, _ = fetcher.requests[0]
        assert params["grid-filter"] == "NationalityDesc__2__Spain"

    def test_max_pages_caps_the_walk(self, grid_payload):
        fetcher = StubFetcher({1: grid_payload, 2: grid_payload}, {})
        companies, errors = sme_matcher.fetch_country(fetcher, "Spain", max_pages=2)
        # The pager advertises 10 pages; max_pages=2 must stop at two.
        assert len(fetcher.requests) == 2
        assert len(companies) == 40 and errors == ()

    def test_a_failed_page_degrades_instead_of_aborting(self, grid_payload):
        fetcher = StubFetcher({1: grid_payload}, {})  # page 2 is missing
        companies, errors = sme_matcher.fetch_country(fetcher, "Spain", max_pages=3)
        assert len(companies) == 20
        assert len(errors) == 2 and "page 2" in errors[0]

    def test_a_failed_first_page_returns_no_companies(self):
        fetcher = StubFetcher({}, {})
        companies, errors = sme_matcher.fetch_country(fetcher, "Spain", max_pages=1)
        assert companies == ()
        assert len(errors) == 1 and "page 1" in errors[0]

    def test_details_are_fetched_for_every_company(self, grid_payload, detail_3edata):
        fetcher = StubFetcher({1: grid_payload}, {"136835": detail_3edata})
        companies, _ = sme_matcher.fetch_country(fetcher, "Spain", max_pages=1)
        enriched, _ = sme_matcher.fetch_details(
            fetcher, companies[:1], DEFAULT_SME_KEYWORDS, workers=2
        )
        assert enriched[0].city == "Lugo"

    def test_input_order_is_preserved(self, grid_payload, detail_3edata, detail_abionica):
        fetcher = StubFetcher(
            {1: grid_payload}, {"136835": detail_3edata, "138894": detail_abionica}
        )
        companies, _ = sme_matcher.fetch_country(fetcher, "Spain", max_pages=1)
        subset = (companies[0], companies[2])
        enriched, _ = sme_matcher.fetch_details(
            fetcher, subset, DEFAULT_SME_KEYWORDS, workers=2
        )
        assert [c.name for c in enriched] == [c.name for c in subset]

    def test_failed_details_are_summarised_not_listed_one_by_one(self, grid_payload):
        fetcher = StubFetcher({1: grid_payload}, {})
        companies, _ = sme_matcher.fetch_country(fetcher, "Spain", max_pages=1)
        enriched, errors = sme_matcher.fetch_details(
            fetcher, companies, DEFAULT_SME_KEYWORDS, workers=4
        )
        assert len(enriched) == 20  # every company survives, unenriched
        assert len(errors) == 1 and "20 detail lookup(s) failed" in errors[0]

    def test_no_companies_means_no_detail_requests(self):
        fetcher = StubFetcher({}, {})
        assert sme_matcher.fetch_details(fetcher, (), DEFAULT_SME_KEYWORDS) == ((), ())


class TestScan:
    def test_scan_filters_to_keyword_matches(
        self, grid_payload, detail_3edata, detail_abionica, sme_settings
    ):
        details = {"136835": detail_3edata, "138894": detail_abionica}
        fetcher = StubFetcher({1: grid_payload}, details)
        settings = SmeSettings(**{**sme_settings.__dict__, "max_pages": 1})

        result = sme_matcher.scan(fetcher, settings)

        # 20 companies scanned; only 3edata's description matches the taxonomy.
        assert result.scanned == 20
        assert [c.name for c in result.companies] == ["3edata ingeniería ambiental sl"]
        assert result.companies[0].domains == ("Remote Sensing",)

    def test_scan_reports_an_empty_directory_as_an_error(self, sme_settings):
        fetcher = StubFetcher({}, {})
        result = sme_matcher.scan(fetcher, sme_settings)
        assert result.companies == ()
        assert any("no companies" in e for e in result.errors)


class TestDedupe:
    def test_repeated_ids_are_dropped_keeping_the_first(self, grid_html):
        companies = sme_matcher.parse_grid_html(grid_html)
        doubled = companies + companies
        unique = sme_matcher.dedupe(doubled)
        assert len(unique) == len(companies)
        assert [c.id for c in unique] == [c.id for c in companies]

    def test_scan_does_not_fetch_the_same_company_twice(
        self, grid_payload, detail_3edata, sme_settings
    ):
        # The same page served twice simulates a directory that repeats a row.
        fetcher = StubFetcher(
            {1: grid_payload, 2: grid_payload}, {"136835": detail_3edata}
        )
        settings = SmeSettings(**{**sme_settings.__dict__, "max_pages": 2})

        result = sme_matcher.scan(fetcher, settings)

        assert result.scanned == 20  # not 40
        assert len({c.id for c in result.companies}) == len(result.companies)
