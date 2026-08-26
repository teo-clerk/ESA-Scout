"""Tests for the Markdown export.

The documents are the portable copy of the dashboard, so the assertions here
pin the things a reader depends on: the metrics, the summary table, the
per-item sections, and contents links that actually resolve to a heading.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from agent import exporter
from agent.models import (
    ChecklistItem,
    Evaluation,
    KeyDeadline,
    Profile,
    Snapshot,
)
from agent.sme_models import Sme, SmeEvaluation, SmeSnapshot
from tests.conftest import make_opportunity
from tests.test_sme_evaluator import make_sme

EXPORT_DAY = date(2026, 8, 27)


def snapshot_of(*opportunities, **overrides) -> Snapshot:
    defaults = dict(
        generated_at="2026-08-17T14:22:37Z",
        opportunities=tuple(opportunities),
        profile=Profile(name="Teo", source_file="CV.pdf"),
    )
    defaults.update(overrides)
    return Snapshot(**defaults)


def sme_snapshot_of(*companies, **overrides) -> SmeSnapshot:
    defaults = dict(
        last_analyzed="2026-08-23T11:42:39Z",
        companies=tuple(companies),
        countries=("Spain", "Italy"),
        keywords=("earth observation",),
        target_term="Summer 2027",
        scanned=618,
        evaluated=True,
    )
    defaults.update(overrides)
    return SmeSnapshot(**defaults)


def headings_of(markdown: str) -> list[str]:
    return re.findall(r"^### (.+)$", markdown, flags=re.MULTILINE)


def contents_links_of(markdown: str) -> list[str]:
    """The anchors the contents list points at, in order."""
    return re.findall(r"^  - \[.+?\]\(#(.+?)\)$", markdown, flags=re.MULTILINE)


class TestSlugs:
    def test_lower_cases_and_hyphenates(self):
        assert exporter.slugify("Navigation Training Course") == "navigation-training-course"

    def test_drops_punctuation_the_way_github_does(self):
        # "%" and the em dash vanish; the spaces around them survive as hyphens.
        assert exporter.slugify("42% — REXUS/BEXUS") == "42--rexusbexus"

    def test_keeps_accented_letters(self):
        assert exporter.slugify("Teledetección Espacial") == "teledetección-espacial"

    def test_duplicate_headings_get_distinct_anchors(self):
        allocator = exporter.AnchorAllocator()
        taken = [allocator.take("Acme SL") for _ in range(3)]
        assert taken == ["acme-sl", "acme-sl-1", "acme-sl-2"]


class TestFormatDate:
    def test_renders_an_iso_date_in_long_form(self):
        assert exporter.format_date("2026-04-05") == "5 April 2026"

    def test_falls_back_to_the_published_wording(self):
        assert exporter.format_date("", "Next cycle in 2027") == "Next cycle in 2027"

    @pytest.mark.parametrize("value", ["2026-13-01", "not a date", "2026"])
    def test_rejects_anything_that_is_not_an_iso_date(self, value):
        assert exporter.format_date(value, "fallback") == "fallback"


class TestOpportunitiesDocument:
    def test_reports_the_headline_metrics(self):
        markdown = exporter.render_opportunities(
            snapshot_of(
                make_opportunity(id="a", title="Alpha", status="Open", score=88),
                make_opportunity(id="b", title="Beta", status="Pending", score=30),
            ),
            high_fit_threshold=80,
            generated_on=EXPORT_DAY,
        )
        assert "| Open now | 1 |" in markdown
        assert "| High fit ≥ 80% | 1 |" in markdown
        assert "| Pending cycles | 1 |" in markdown
        assert "| Tracked total | 2 |" in markdown
        assert "> Exported 2026-08-27" in markdown

    def test_orders_sections_by_descending_fit(self):
        markdown = exporter.render_opportunities(
            snapshot_of(
                make_opportunity(id="a", title="Low", score=20),
                make_opportunity(id="b", title="High", score=90),
            ),
            generated_on=EXPORT_DAY,
        )
        assert headings_of(markdown) == ["90% — High", "20% — Low"]

    def test_summary_table_carries_fit_status_deadline_and_link(self):
        markdown = exporter.render_opportunities(
            snapshot_of(
                make_opportunity(
                    title="Navigation Training Course",
                    status="Open",
                    score=61,
                    deadline="2026-04-05",
                    url="https://esa.example/nav",
                )
            ),
            generated_on=EXPORT_DAY,
        )
        assert (
            "| 61% | Navigation Training Course | Open | 5 April 2026 | "
            "[Open](https://esa.example/nav) |"
        ) in markdown

    def test_every_contents_link_resolves_to_a_heading(self):
        markdown = exporter.render_opportunities(
            snapshot_of(
                make_opportunity(id="a", title="Acme Course", score=50),
                # Same title and score: the anchors must still differ.
                make_opportunity(id="b", title="Acme Course", score=50),
                make_opportunity(id="c", title="A/B & C: Testing", score=10),
            ),
            generated_on=EXPORT_DAY,
        )
        anchors = {exporter.slugify(h) for h in headings_of(markdown)}
        links = contents_links_of(markdown)
        assert len(links) == 3
        assert len(set(links)) == 3, "duplicate headings must get distinct anchors"
        # Every link is either a heading's slug or that slug plus a suffix.
        for link in links:
            assert link in anchors or re.sub(r"-\d+$", "", link) in anchors

    def test_renders_the_full_evaluation_for_one_opportunity(self):
        evaluation = Evaluation(
            match_score=74,
            justification="Strong overlap with your ML work.",
            why_apply=("Flight hardware access",),
            required_skills=("Python", "Proposal writing"),
            gaps=("No aerospace coursework",),
            checklist=(
                ChecklistItem(
                    task="Draft a concept note",
                    effort="1 week",
                    done_when="Shared with the programme office",
                ),
            ),
            key_deadlines=(KeyDeadline(label="Proposal due", date="2026-10-08"),),
            model="grok-4",
            evaluated_at="2026-08-17T14:22:36Z",
        )
        markdown = exporter.render_opportunities(
            snapshot_of(
                make_opportunity(title="REXUS/BEXUS", url="https://esa.example/rb").with_evaluation(
                    evaluation
                )
            ),
            generated_on=EXPORT_DAY,
        )

        assert "#### AI justification" in markdown
        assert "Strong overlap with your ML work." in markdown
        assert "- Flight hardware access" in markdown
        assert "`Python` · `Proposal writing`" in markdown
        assert "- No aerospace coursework" in markdown
        assert "- [ ] Draft a concept note" in markdown
        assert "  - Effort: 1 week" in markdown
        assert "  - Done when: Shared with the programme office" in markdown
        assert "| Proposal due | 8 October 2026 |" in markdown
        assert "_Scored by grok-4 on 2026-08-17T14:22:36Z._" in markdown
        assert "- [Opportunity page](https://esa.example/rb)" in markdown

    def test_marks_an_unevaluated_opportunity_instead_of_omitting_it(self):
        markdown = exporter.render_opportunities(
            snapshot_of(make_opportunity(title="Unscored Thing")),
            generated_on=EXPORT_DAY,
        )
        assert "### Unscored — Unscored Thing" in markdown
        assert "_Not evaluated yet._" in markdown

    def test_surfaces_an_evaluation_error_rather_than_pretending_it_scored(self):
        broken = make_opportunity(title="Broken").with_evaluation(
            Evaluation(match_score=0, error="LLM timed out")
        )
        markdown = exporter.render_opportunities(
            snapshot_of(broken), generated_on=EXPORT_DAY
        )
        assert "> Evaluation failed: LLM timed out" in markdown

    def test_pipes_in_a_title_cannot_break_the_summary_table(self):
        markdown = exporter.render_opportunities(
            snapshot_of(make_opportunity(title="A | B", score=10)),
            generated_on=EXPORT_DAY,
        )
        row = next(line for line in markdown.splitlines() if line.startswith("| 10%"))
        assert "A \\| B" in row
        # Only unescaped pipes delimit cells: 5 columns => 6 delimiters.
        assert len(re.findall(r"(?<!\\)\|", row)) == 6

    def test_lists_the_run_warnings(self):
        markdown = exporter.render_opportunities(
            snapshot_of(make_opportunity(), errors=("github: rate limited",)),
            generated_on=EXPORT_DAY,
        )
        assert "## Warnings (1)" in markdown
        assert "- github: rate limited" in markdown

    def test_an_empty_snapshot_still_produces_a_readable_document(self):
        markdown = exporter.render_opportunities(
            Snapshot(generated_at=""), generated_on=EXPORT_DAY
        )
        assert markdown.startswith("# ESA Scout — Opportunities")
        assert "_No opportunities in this snapshot._" in markdown
        assert "python -m agent.main run" in markdown

    def test_ends_with_exactly_one_newline(self):
        markdown = exporter.render_opportunities(
            snapshot_of(make_opportunity(score=10)), generated_on=EXPORT_DAY
        )
        assert markdown.endswith("\n") and not markdown.endswith("\n\n")


class TestSmeDocument:
    def test_reports_the_overview_metrics(self):
        markdown = exporter.render_sme_targets(
            sme_snapshot_of(
                make_sme(id="a", name="Alpha SL", score=85),
                make_sme(id="b", name="Beta Srl", score=40, country="Italy", country_code="IT"),
            ),
            strong_fit_threshold=70,
            generated_on=EXPORT_DAY,
        )
        assert "| Companies scanned | 618 |" in markdown
        assert "| Keyword matches | 2 |" in markdown
        assert "| Strong fit ≥ 70% | 1 |" in markdown
        assert "| Spain | 1 |" in markdown
        assert "| Italy | 1 |" in markdown

    def test_names_the_target_term_in_the_header_and_the_rationale_section(self):
        markdown = exporter.render_sme_targets(
            sme_snapshot_of(make_sme(score=85)), generated_on=EXPORT_DAY
        )
        assert "**Summer 2027** internship targets" in markdown
        assert "#### Why this fits for Summer 2027" in markdown

    def test_summary_table_carries_country_city_and_domains(self):
        markdown = exporter.render_sme_targets(
            sme_snapshot_of(make_sme(name="Acme Geospatial SL", score=85)),
            generated_on=EXPORT_DAY,
        )
        assert (
            "| 85% | Acme Geospatial SL | ES | Madrid | Earth Observation | "
            "[Site](https://acme.example) |"
        ) in markdown

    def test_renders_domain_tags_rationale_and_outreach_advice(self):
        company = Sme(
            id="deep-1",
            entity_id="138796",
            name="Deepleey Srl",
            country="Italy",
            country_code="IT",
            city="Genova",
            website="https://deepleey.example",
            description="AI and computer vision for ESG.",
            entity_type="Company",
            entity_size="Small",
            detail_url="https://esastar.example/138796",
            domains=("Remote Sensing", "Computer Vision"),
            matched_keywords=("remote sensing",),
            evaluation=SmeEvaluation(
                fit_score=85,
                rationale="Your CV work maps onto their AI stack.",
                suggested_role="Remote sensing AI intern",
                focus_areas=("Computer Vision",),
                outreach_tips=("Reference their Genoa base", "Offer a mini-project"),
                model="grok-4",
                evaluated_at="2026-08-23T11:41:55Z",
            ),
        )
        markdown = exporter.render_sme_targets(
            sme_snapshot_of(company), generated_on=EXPORT_DAY
        )

        assert "### 85% — Deepleey Srl" in markdown
        assert "- **Location:** Genova, Italy" in markdown
        assert "- **Website:** <https://deepleey.example>" in markdown
        assert "- **ESA-star entry:** [138796](https://esastar.example/138796)" in markdown
        assert "- **Domain tags (inferred):** `Remote Sensing` · `Computer Vision`" in markdown
        assert "AI and computer vision for ESG." in markdown
        assert "Your CV work maps onto their AI stack." in markdown
        assert "#### Suggested role" in markdown
        assert "#### Outreach advice" in markdown
        assert "- Reference their Genoa base" in markdown
        assert "_Ranked by grok-4 on 2026-08-23T11:41:55Z._" in markdown

    def test_says_so_when_a_company_has_not_been_ranked(self):
        markdown = exporter.render_sme_targets(
            sme_snapshot_of(make_sme(name="Unranked SL")), generated_on=EXPORT_DAY
        )
        assert "### Unranked — Unranked SL" in markdown
        assert "_Not ranked yet._" in markdown

    def test_warns_when_the_whole_scan_was_keyword_only(self):
        markdown = exporter.render_sme_targets(
            sme_snapshot_of(make_sme(), evaluated=False), generated_on=EXPORT_DAY
        )
        assert "have not been ranked yet" in markdown
        assert "`--evaluate`" in markdown

    def test_falls_back_to_the_esa_star_link_when_there_is_no_website(self):
        markdown = exporter.render_sme_targets(
            sme_snapshot_of(
                make_sme(
                    score=50,
                    website="",
                    detail_url="https://esastar.example/9",
                )
            ),
            generated_on=EXPORT_DAY,
        )
        assert "[ESA-star](https://esastar.example/9)" in markdown

    def test_states_that_none_of_these_companies_advertised_a_role(self):
        markdown = exporter.render_sme_targets(
            sme_snapshot_of(make_sme(score=85)), generated_on=EXPORT_DAY
        )
        assert "cold approach" in markdown

    def test_an_empty_snapshot_still_produces_a_readable_document(self):
        markdown = exporter.render_sme_targets(
            SmeSnapshot(last_analyzed=""), generated_on=EXPORT_DAY
        )
        assert markdown.startswith("# ESA Scout — SME Internship Targets")
        assert "_No companies in this snapshot._" in markdown


class TestFileOutput:
    def test_writes_both_documents_into_the_given_directory(self, tmp_path):
        opportunities = exporter.write_opportunities(
            snapshot_of(make_opportunity(score=50)), tmp_path
        )
        companies = exporter.write_sme_targets(sme_snapshot_of(make_sme(score=50)), tmp_path)

        assert opportunities == tmp_path / "OPPORTUNITIES.md"
        assert companies == tmp_path / "SME_TARGETS.md"
        assert opportunities.read_text(encoding="utf-8").startswith("# ESA Scout")
        assert companies.read_text(encoding="utf-8").startswith("# ESA Scout")

    def test_creates_a_missing_output_directory(self, tmp_path):
        target = tmp_path / "nested" / "docs"
        path = exporter.write_opportunities(snapshot_of(make_opportunity()), target)
        assert path.exists()


class TestExportCommand:
    """`python -m agent.main export` — what it writes and what it refuses to."""

    @pytest.fixture
    def stored(self, monkeypatch):
        """Both snapshots present, without touching the repository's real data."""
        from agent import main as cli

        state = {
            "opportunities": snapshot_of(make_opportunity(score=50)),
            "sme": sme_snapshot_of(make_sme(score=50)),
        }
        monkeypatch.setattr(
            cli.state_manager, "load_snapshot", lambda path: state["opportunities"]
        )
        monkeypatch.setattr(cli.sme_state, "load_snapshot", lambda path: state["sme"])
        return state

    def test_writes_both_documents_by_default(self, stored, tmp_path, capsys):
        from agent import main as cli

        code = cli.main(["export", "--output-dir", str(tmp_path)])

        assert code == cli.EXIT_OK
        assert (tmp_path / "OPPORTUNITIES.md").exists()
        assert (tmp_path / "SME_TARGETS.md").exists()
        assert "OPPORTUNITIES.md" in capsys.readouterr().out

    def test_opportunities_only_skips_the_sme_document(self, stored, tmp_path):
        from agent import main as cli

        code = cli.main(["export", "--opportunities-only", "--output-dir", str(tmp_path)])

        assert code == cli.EXIT_OK
        assert (tmp_path / "OPPORTUNITIES.md").exists()
        assert not (tmp_path / "SME_TARGETS.md").exists()

    def test_sme_only_skips_the_opportunities_document(self, stored, tmp_path):
        from agent import main as cli

        code = cli.main(["export", "--sme-only", "--output-dir", str(tmp_path)])

        assert code == cli.EXIT_OK
        assert (tmp_path / "SME_TARGETS.md").exists()
        assert not (tmp_path / "OPPORTUNITIES.md").exists()

    def test_reports_degraded_when_only_one_source_has_data(self, stored, tmp_path):
        from agent import main as cli

        stored["sme"] = SmeSnapshot(last_analyzed="")

        code = cli.main(["export", "--output-dir", str(tmp_path)])

        # The opportunities file is still written — a missing SME scan must not
        # cost the user the export they can have.
        assert code == cli.EXIT_DEGRADED
        assert (tmp_path / "OPPORTUNITIES.md").exists()
        assert not (tmp_path / "SME_TARGETS.md").exists()

    def test_fails_without_writing_an_empty_file_when_there_is_no_data(
        self, stored, tmp_path
    ):
        from agent import main as cli

        stored["opportunities"] = Snapshot(generated_at="")
        stored["sme"] = SmeSnapshot(last_analyzed="")

        code = cli.main(["export", "--output-dir", str(tmp_path)])

        assert code == cli.EXIT_FAILURE
        assert list(tmp_path.iterdir()) == []
