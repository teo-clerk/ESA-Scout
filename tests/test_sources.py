"""Parser tests against real ESA HTML captured in tests/fixtures/.

These are the suite's canaries: if ESA changes its markup, these fail.
"""

from __future__ import annotations

import pytest

from agent.models import STATUS_CLOSED, STATUS_OPEN, STATUS_PENDING
from agent.sources import academy, jobs, tlp
from agent.sources.common import ScrapeResult, absolutise, slugify

TLP_URL = "https://educationforms.esa.int/tlp/table/current-opportunities/"


# --- TLP -------------------------------------------------------------------
class TestTLP:
    def test_extracts_every_row(self, tlp_html, today):
        result = tlp.parse_html(tlp_html, base_url=TLP_URL, today=today)
        assert result.errors == ()
        assert len(result.opportunities) == 9

    def test_maps_all_columns_of_a_known_row(self, tlp_html, today):
        result = tlp.parse_html(tlp_html, base_url=TLP_URL, today=today)
        first = result.opportunities[0]
        assert first.title == "Navigation Training Course"
        assert first.kind == "Training Course"
        assert first.status == STATUS_OPEN
        assert first.activity_dates == "22 – 26 June 2026"
        assert first.activity_start == "2026-06-22"
        assert first.deadline == "2026-04-05"
        assert first.url == "https://learn.esa.int/explore/navigation-training-course"

    def test_application_link_comes_from_the_status_cell(self, tlp_html, today):
        result = tlp.parse_html(tlp_html, base_url=TLP_URL, today=today)
        assert all(o.url.startswith("http") for o in result.opportunities)

    def test_year_less_deadline_still_parses(self, tlp_html, today):
        """"19 April" (no year) appears verbatim on the live page."""
        result = tlp.parse_html(tlp_html, base_url=TLP_URL, today=today)
        row = next(o for o in result.opportunities if "Disruptive" in o.title)
        assert row.deadline_text == "19 April"
        assert row.deadline.endswith("-04-19")

    def test_ids_are_stable_across_parses(self, tlp_html, today):
        first = tlp.parse_html(tlp_html, base_url=TLP_URL, today=today)
        second = tlp.parse_html(tlp_html, base_url=TLP_URL, today=today)
        assert [o.id for o in first.opportunities] == [o.id for o in second.opportunities]

    def test_categories_are_assigned(self, tlp_html, today):
        result = tlp.parse_html(tlp_html, base_url=TLP_URL, today=today)
        by_title = {o.title: o.category for o in result.opportunities}
        assert by_title["SPAICE (AI in and for space)"] == "Earth Observation & AI"
        assert "Space Systems" in set(by_title.values())

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Open", STATUS_OPEN),
            ("open", STATUS_OPEN),
            ("Apply now", STATUS_OPEN),
            ("Closed", STATUS_CLOSED),
            ("Expired", STATUS_CLOSED),
            ("Opening soon", STATUS_OPEN),  # "open" prefix wins, still actionable
            ("TBC", STATUS_PENDING),
            ("", "Unknown"),
        ],
    )
    def test_status_normalisation(self, raw, expected):
        assert tlp.normalise_status(raw) == expected

    def test_declared_open_survives_an_elapsed_deadline(self, tlp_html, today):
        """Every fixture row has a past deadline but is labelled Open upstream.

        We must not silently reclassify these as Closed — hiding a live call is
        worse than showing a stale one.
        """
        result = tlp.parse_html(tlp_html, base_url=TLP_URL, today=today)
        assert all(o.status == STATUS_OPEN for o in result.opportunities)

    def test_missing_table_is_reported_not_raised(self):
        result = tlp.parse_html("<html><body>redesigned</body></html>", TLP_URL)
        assert result.opportunities == ()
        assert result.errors and "esa_tlp" in result.errors[0]

    def test_header_without_rows_is_reported(self):
        markup = (
            "<table><tr><td>Programme</td><td>Status</td></tr></table>"
        )
        result = tlp.parse_html(markup, TLP_URL)
        assert result.opportunities == ()
        assert any("no data rows" in e for e in result.errors)

    def test_rows_without_a_title_are_skipped(self):
        markup = (
            "<table>"
            "<tr><td>Programme</td><td>Deadline to apply</td><td>Status</td></tr>"
            "<tr><td></td><td>1 May 2027</td><td>Open</td></tr>"
            "</table>"
        )
        result = tlp.parse_html(markup, TLP_URL)
        assert result.opportunities == ()

    def test_reordered_columns_are_followed_by_header_name(self):
        """Columns are located by label, so swapping them must not corrupt data."""
        markup = (
            "<table>"
            "<tr><td>Status</td><td>Programme</td><td>Deadline to apply</td></tr>"
            "<tr><td>Open</td><td>Quantum Course</td><td>3 May 2027</td></tr>"
            "</table>"
        )
        result = tlp.parse_html(markup, TLP_URL)
        assert len(result.opportunities) == 1
        assert result.opportunities[0].title == "Quantum Course"
        assert result.opportunities[0].deadline == "2027-05-03"


# --- ESA Academy -----------------------------------------------------------
class TestAcademy:
    def test_extracts_project_programmes(self, academy_html, today):
        result = academy.parse_html(academy_html, today=today)
        assert result.errors == ()
        assert len(result.opportunities) == 5

    def test_open_call_is_detected_with_its_deadline(self, academy_html, today):
        result = academy.parse_html(academy_html, today=today)
        rexus = next(o for o in result.opportunities if "REXUS" in o.title)
        assert rexus.status == STATUS_OPEN
        assert rexus.deadline == "2026-10-08"

    def test_future_cycle_is_pending_not_open(self, academy_html, today):
        """"Next cycle expected to open in 2027" contains "open" but is Pending."""
        result = academy.parse_html(academy_html, today=today)
        fys = next(
            o for o in result.opportunities if o.title == "CubeSats: Fly Your Satellite!"
        )
        assert fys.status == STATUS_PENDING

    def test_contact_email_is_kept_in_the_summary(self, academy_html, today):
        result = academy.parse_html(academy_html, today=today)
        rexus = next(o for o in result.opportunities if "REXUS" in o.title)
        assert "rexus-bexus@esa.int" in rexus.summary

    def test_mailto_links_are_not_used_as_the_url(self, academy_html, today):
        result = academy.parse_html(academy_html, today=today)
        assert all(not o.url.startswith("mailto:") for o in result.opportunities)

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Call for proposals open until 8 October 2026", STATUS_OPEN),
            ("Next cycle expected to open in 2027", STATUS_PENDING),
            ("Applications closed", STATUS_CLOSED),
            ("To be announced", STATUS_PENDING),
            ("", "Unknown"),
        ],
    )
    def test_cycle_status(self, raw, expected):
        assert academy.cycle_status(raw) == expected

    def test_missing_table_is_reported(self):
        result = academy.parse_html("<html><body>nothing</body></html>")
        assert result.opportunities == ()
        assert result.errors


# --- ESA Jobs --------------------------------------------------------------
class TestJobs:
    def test_reads_every_tile_when_unfiltered(self, jobs_html, today):
        result = jobs.parse_html(jobs_html, keywords=(), today=today)
        assert len(result.opportunities) == 25

    def test_keyword_filter_selects_early_career_roles(self, jobs_html, today):
        result = jobs.parse_html(
            jobs_html, keywords=("graduate trainee", "internship"), today=today
        )
        assert len(result.opportunities) == 1
        assert "Graduate Trainee" in result.opportunities[0].title

    def test_closing_date_is_read_from_the_department_field(self, jobs_html, today):
        """ESA's SuccessFactors puts the closing date in `department`."""
        result = jobs.parse_html(jobs_html, keywords=(), today=today)
        trainee = next(o for o in result.opportunities if "Graduate Trainee" in o.title)
        assert trainee.deadline == "2026-09-07"
        assert trainee.location == "Noordwijk, NL"
        assert trainee.kind == "ESA Graduate Trainee"

    def test_urls_are_absolute(self, jobs_html, today):
        result = jobs.parse_html(jobs_html, keywords=(), today=today)
        assert all(o.url.startswith("https://jobs.esa.int/") for o in result.opportunities)

    def test_desktop_and_mobile_duplicates_collapse_to_one_entry(self, jobs_html, today):
        """Each tile renders twice; ids must not duplicate."""
        result = jobs.parse_html(jobs_html, keywords=(), today=today)
        ids = [o.id for o in result.opportunities]
        assert len(ids) == len(set(ids))

    def test_past_closing_date_marks_the_vacancy_closed(self, jobs_html, today):
        """Unlike ESA's editorial pages, SuccessFactors dates are authoritative."""
        from datetime import date

        result = jobs.parse_html(jobs_html, keywords=(), today=date(2027, 1, 1))
        assert all(o.status == STATUS_CLOSED for o in result.opportunities)

    def test_empty_results_page_is_not_an_error(self):
        result = jobs.parse_html("<html><body><ul></ul></body></html>")
        assert result.opportunities == ()
        assert result.errors == ()

    @pytest.mark.parametrize(
        "title,kind,keywords,expected",
        [
            ("Internship in Robotics", "", ("internship",), True),
            ("Senior Engineer", "ESA Graduate Trainee", ("graduate trainee",), True),
            ("Senior Engineer", "Fixed-Term", ("internship",), False),
            ("Anything", "", (), True),  # no filter configured
        ],
    )
    def test_matches_keywords(self, title, kind, keywords, expected):
        assert jobs.matches_keywords(title, kind, keywords) is expected

    def test_page_params_advance_by_page_size(self):
        assert jobs.page_params(0) == {"q": "", "startrow": "0"}
        assert jobs.page_params(2) == {"q": "", "startrow": "50"}


# --- Shared helpers --------------------------------------------------------
class TestCommon:
    @pytest.mark.parametrize(
        "parts,expected",
        [
            (("esa_tlp", "Navigation Training Course"), "esa-tlp-navigation-training-course"),
            (("Café Münster",), "cafe-munster"),
            (("!!!",), "unknown"),
            (("",), "unknown"),
        ],
    )
    def test_slugify(self, parts, expected):
        assert slugify(*parts) == expected

    def test_slugify_is_length_capped(self):
        assert len(slugify("x" * 200)) <= 70

    @pytest.mark.parametrize(
        "href,base,expected",
        [
            ("/job/1", "https://jobs.esa.int", "https://jobs.esa.int/job/1"),
            ("https://a.test/x", "https://b.test", "https://a.test/x"),
            ("mailto:a@b.test", "https://b.test", "mailto:a@b.test"),
            ("", "https://b.test", ""),
        ],
    )
    def test_absolutise(self, href, base, expected):
        assert absolutise(href, base) == expected

    def test_merge_combines_without_mutating(self, opportunity_factory):
        left = ScrapeResult((opportunity_factory(id="a"),), ("e1",))
        right = ScrapeResult((opportunity_factory(id="b"),), ("e2",))
        merged = left.merge(right)
        assert len(merged.opportunities) == 2
        assert merged.errors == ("e1", "e2")
        assert len(left.opportunities) == 1  # unchanged
