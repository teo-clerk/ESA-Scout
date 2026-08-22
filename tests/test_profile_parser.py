"""Tests for CV extraction and GitHub sync.

The PDF tests run against the real `CV.pdf` in the repository root when present
and skip otherwise, so the suite stays green in a fresh clone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent import profile_parser
from agent.config import REPO_ROOT
from agent.models import GitHubProfile

CV_PATH = REPO_ROOT / "CV.pdf"
requires_cv = pytest.mark.skipif(not CV_PATH.exists(), reason="CV.pdf not present")

SAMPLE_CV = """\
JANE DOE
jane@example.com | +34 600 000 000 | Venice, Italy

PROFESSIONAL SUMMARY
Aerospace engineering student focused on onboard software. Passionate about
small satellites and autonomy.

EDUCATION
BSc AEROSPACE ENGINEERING: Politecnico di Milano
September 2024 - Expected 2027
• Coursework in orbital mechanics, control systems and embedded programming

PROFESSIONAL EXPERIENCE
• RESEARCH ASSISTANT: CubeSat Lab | Jan 2025 - Present
Developed attitude determination software and ran hardware-in-the-loop coun-
tries tests for a 3U platform.

PROJECTS & INITIATIVES
Ground Station Toolkit: Independent Project
Built an open-source toolkit for decoding satellite telemetry.

SKILLS
Technical Skills:
• Programming: Python, C, Rust
• Tools: Git, KiCad, MATLAB
"""


class TestPdfDiscovery:
    def test_finds_a_cv_named_pdf(self, tmp_path):
        (tmp_path / "notes.pdf").write_bytes(b"%PDF-1.4")
        (tmp_path / "CV.pdf").write_bytes(b"%PDF-1.4")
        found = profile_parser.find_profile_pdf((tmp_path,))
        assert found is not None and found.name == "CV.pdf"

    def test_prefers_cv_over_resume_over_unrelated(self, tmp_path):
        for name in ("zzz.pdf", "resume.pdf", "my_cv_2026.pdf"):
            (tmp_path / name).write_bytes(b"%PDF-1.4")
        assert profile_parser.find_profile_pdf((tmp_path,)).name == "my_cv_2026.pdf"

    def test_falls_back_to_any_pdf(self, tmp_path):
        (tmp_path / "document.pdf").write_bytes(b"%PDF-1.4")
        assert profile_parser.find_profile_pdf((tmp_path,)).name == "document.pdf"

    def test_returns_none_when_no_pdf_exists(self, tmp_path):
        assert profile_parser.find_profile_pdf((tmp_path,)) is None

    def test_missing_directory_is_tolerated(self, tmp_path):
        assert profile_parser.find_profile_pdf((tmp_path / "absent",)) is None

    def test_searches_every_configured_directory(self, tmp_path):
        nested = tmp_path / "agent" / "profile"
        nested.mkdir(parents=True)
        (nested / "CV.pdf").write_bytes(b"%PDF-1.4")
        found = profile_parser.find_profile_pdf((tmp_path, nested))
        assert found is not None and found.name == "CV.pdf"


class TestTextRepair:
    def test_orphaned_accent_is_recombined(self):
        assert profile_parser.repair_text("Fundaci´o CIC") == "Fundació CIC"

    def test_missing_space_before_bracket_is_restored(self):
        assert profile_parser.repair_text("Campus(University)") == "Campus (University)"

    def test_clean_text_is_unchanged(self):
        assert profile_parser.repair_text("Nothing to fix here.") == "Nothing to fix here."

    def test_empty_input(self):
        assert profile_parser.repair_text("") == ""


class TestGlueRatio:
    def test_well_spaced_text_scores_low(self):
        assert profile_parser._glue_ratio("this is normal prose") == 0.0

    def test_run_together_text_scores_high(self):
        assert profile_parser._glue_ratio("humancenteredsolutionsthroughtechnology") == 1.0

    def test_empty_text_is_worst(self):
        assert profile_parser._glue_ratio("") == 1.0


class TestCvParsing:
    def test_sections_are_split_by_heading(self):
        sections = profile_parser.split_sections(SAMPLE_CV)
        assert {"summary", "education", "experience", "projects", "skills"} <= set(sections)

    def test_name_is_taken_from_the_header(self):
        assert profile_parser.parse_cv(SAMPLE_CV).name == "JANE DOE"

    def test_headline_is_the_first_summary_sentence(self):
        headline = profile_parser.parse_cv(SAMPLE_CV).headline
        assert headline.startswith("Aerospace engineering student")
        assert headline.endswith(".")

    def test_skills_are_flattened_and_deduplicated(self):
        skills = profile_parser.parse_cv(SAMPLE_CV).skills
        assert "Python" in skills and "Rust" in skills and "KiCad" in skills
        # The "Programming:" label must not become a skill.
        assert not any(s.endswith(":") for s in skills)
        assert len(skills) == len(set(skills))

    def test_wrapped_bullet_lines_are_rejoined(self):
        highlights = profile_parser.parse_cv(SAMPLE_CV).highlights
        research = next(h for h in highlights if "RESEARCH ASSISTANT" in h)
        assert "attitude determination software" in research

    def test_line_break_hyphenation_is_repaired(self):
        """"coun-\\ntries" must rejoin as "countries", not "coun- tries"."""
        highlights = profile_parser.parse_cv(SAMPLE_CV).highlights
        assert any("countries" in h for h in highlights)

    def test_projects_reach_the_highlights(self):
        highlights = profile_parser.parse_cv(SAMPLE_CV).highlights
        assert any("Ground Station Toolkit" in h for h in highlights)

    def test_source_file_is_recorded(self):
        assert profile_parser.parse_cv(SAMPLE_CV, "CV.pdf").source_file == "CV.pdf"

    def test_empty_cv_does_not_raise(self):
        profile = profile_parser.parse_cv("")
        assert profile.name == "" and profile.skills == ()

    def test_fingerprint_changes_with_content(self):
        a = profile_parser.parse_cv(SAMPLE_CV)
        b = profile_parser.parse_cv(SAMPLE_CV.replace("Rust", "Go"))
        assert a.fingerprint() != b.fingerprint()


@requires_cv
class TestRealCv:
    def test_text_is_extracted(self):
        text, error = profile_parser.extract_pdf_text(CV_PATH)
        assert error == ""
        assert len(text) > 500

    def test_extraction_is_well_spaced(self):
        """Guards the extractor-selection heuristic against regressions."""
        text, _ = profile_parser.extract_pdf_text(CV_PATH)
        assert profile_parser._glue_ratio(text) < 0.02

    def test_structured_fields_are_populated(self):
        text, _ = profile_parser.extract_pdf_text(CV_PATH)
        profile = profile_parser.parse_cv(text, CV_PATH.name)
        assert profile.name
        assert profile.headline
        assert profile.skills
        assert profile.education

    def test_missing_pdf_reports_an_error(self, tmp_path):
        text, error = profile_parser.extract_pdf_text(tmp_path / "nope.pdf")
        assert text == "" and error


class TestGitHubSync:
    def test_repositories_are_mapped(self):
        class Client:
            def get(self, url, params=None, headers=None):
                class R:
                    status_code = 200

                    @staticmethod
                    def json():
                        return [
                            {
                                "name": "synapse",
                                "description": "AI pipeline",
                                "language": "Python",
                                "html_url": "https://github.com/u/synapse",
                                "stargazers_count": 7,
                                "topics": ["ai"],
                                "pushed_at": "2026-08-01T00:00:00Z",
                                "fork": False,
                            }
                        ]

                return R()

            def close(self):
                pass

        result = profile_parser.fetch_github("u", client=Client())
        assert result.error == ""
        assert result.repos[0].name == "synapse"
        assert result.repos[0].stars == 7
        assert result.languages == ("Python",)
        assert result.profile_url == "https://github.com/u"

    def test_forks_are_excluded(self):
        class Client:
            def get(self, url, params=None, headers=None):
                class R:
                    status_code = 200

                    @staticmethod
                    def json():
                        return [
                            {"name": "mine", "fork": False},
                            {"name": "theirs", "fork": True},
                        ]

                return R()

            def close(self):
                pass

        result = profile_parser.fetch_github("u", client=Client())
        assert [r.name for r in result.repos] == ["mine"]

    @pytest.mark.parametrize(
        "status,fragment",
        [(404, "not found"), (403, "rate limit"), (500, "HTTP 500")],
    )
    def test_api_errors_degrade_gracefully(self, status, fragment):
        class Client:
            def get(self, url, params=None, headers=None):
                class R:
                    status_code = status
                    text = "err"

                    @staticmethod
                    def json():
                        return {}

                return R()

            def close(self):
                pass

        result = profile_parser.fetch_github("u", client=Client())
        assert result.repos == ()
        assert fragment.lower() in result.error.lower()

    def test_network_exception_degrades_gracefully(self):
        class Client:
            def get(self, *a, **k):
                raise OSError("dns failure")

            def close(self):
                pass

        result = profile_parser.fetch_github("u", client=Client())
        assert "dns failure" in result.error

    def test_missing_username_is_reported(self):
        assert "GITHUB_USERNAME" in profile_parser.fetch_github(None).error

    def test_token_is_sent_as_a_bearer_header(self):
        seen = {}

        class Client:
            def get(self, url, params=None, headers=None):
                seen.update(headers or {})

                class R:
                    status_code = 200

                    @staticmethod
                    def json():
                        return []

                return R()

            def close(self):
                pass

        profile_parser.fetch_github("u", token="ghp_x", client=Client())
        assert seen["Authorization"] == "Bearer ghp_x"
