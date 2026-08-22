"""Tests for SME ranking: prompting, parsing, caching, budgeting, degradation.

No network is used — a fake OpenAI-compatible client returns scripted replies.
"""

from __future__ import annotations

import json

import pytest

from agent import sme_evaluator, sme_state
from agent.config import LLMSettings
from agent.sme_models import Sme, SmeEvaluation, SmeSnapshot
from tests.test_evaluator import FakeClient

VALID_RESPONSE = json.dumps(
    {
        "fit_score": 78,
        "rationale": "Their EO pipeline work overlaps your Python and ML projects. A small team like this can absorb a summer student.",
        "suggested_role": "Earth observation data pipeline intern",
        "focus_areas": ["Sentinel-2 preprocessing", "Python tooling"],
        "outreach_tips": ["Reference their LiDAR forestry work", "Offer to prototype a tiling script"],
    }
)


@pytest.fixture
def llm_settings() -> LLMSettings:
    return LLMSettings(
        api_key="test-key",
        base_url="https://api.test/v1",
        model="test-model",
        temperature=0.2,
        max_opportunities=60,
    )


def make_sme(
    id: str = "acme-1",
    name: str = "Acme Geospatial SL",
    description: str = "We process Sentinel-2 imagery.",
    keywords: tuple[str, ...] = ("earth observation",),
    score: int | None = None,
    **overrides,
) -> Sme:
    evaluation = (
        SmeEvaluation(fit_score=score, rationale="Because.", fingerprint="fp-1")
        if score is not None
        else None
    )
    defaults = dict(
        id=id,
        entity_id="1",
        name=name,
        country="Spain",
        country_code="ES",
        city="Madrid",
        website="https://acme.example",
        description=description,
        domains=("Earth Observation",),
        matched_keywords=keywords,
        evaluation=evaluation,
    )
    defaults.update(overrides)
    return Sme(**defaults)


class TestPromptBuilding:
    def test_prompt_states_the_target_term_and_study_stage(self, profile):
        prompt = sme_evaluator.build_prompt(make_sme(), profile, "Summer 2027")
        assert "Summer 2027" in prompt
        assert "second and third year" in prompt

    def test_prompt_includes_company_facts_and_the_candidate(self, profile):
        prompt = sme_evaluator.build_prompt(make_sme(), profile, "Summer 2027")
        assert "Acme Geospatial SL" in prompt
        assert "Sentinel-2 imagery" in prompt
        assert "Teo Clerici Jurado" in prompt

    def test_empty_fields_are_omitted_rather_than_left_blank(self, profile):
        bare = Sme(id="x", entity_id="1", name="Nameless SL")
        prompt = sme_evaluator.build_prompt(bare, profile, "Summer 2027")
        assert "Website:" not in prompt and "City:" not in prompt

    def test_system_prompt_demands_a_two_sentence_rationale(self):
        assert "exactly two sentences" in sme_evaluator.SYSTEM_PROMPT


class TestResponseParsing:
    def test_valid_json_is_parsed_fully(self):
        evaluation = sme_evaluator.parse_response(VALID_RESPONSE, "m", "key")
        assert evaluation.fit_score == 78
        assert evaluation.suggested_role == "Earth observation data pipeline intern"
        assert len(evaluation.outreach_tips) == 2
        assert evaluation.model == "m" and evaluation.fingerprint == "key"
        assert evaluation.error == ""

    def test_json_wrapped_in_prose_is_recovered(self):
        reply = f"Sure, here you go:\n```json\n{VALID_RESPONSE}\n```"
        assert sme_evaluator.parse_response(reply, "m", "k").fit_score == 78

    def test_non_json_reply_becomes_an_error_not_an_exception(self):
        evaluation = sme_evaluator.parse_response("I cannot help.", "m", "k")
        assert evaluation.fit_score == 0 and "not valid JSON" in evaluation.error

    def test_empty_reply_becomes_an_error(self):
        assert "empty response" in sme_evaluator.parse_response("", "m", "k").error

    @pytest.mark.parametrize(
        "raw, expected", [(150, 100), (-20, 0), ("83", 83), (None, 0), ("high", 0)]
    )
    def test_scores_are_clamped_and_coerced(self, raw, expected):
        reply = json.dumps({"fit_score": raw, "rationale": "x"})
        assert sme_evaluator.parse_response(reply, "m", "k").fit_score == expected

    def test_a_legacy_match_score_key_is_still_understood(self):
        reply = json.dumps({"match_score": 64, "rationale": "x"})
        assert sme_evaluator.parse_response(reply, "m", "k").fit_score == 64


class TestEvaluateAll:
    def test_every_company_receives_an_evaluation(self, profile, llm_settings):
        companies = (make_sme(id="a"), make_sme(id="b"))
        client = FakeClient([VALID_RESPONSE, VALID_RESPONSE])
        evaluated, errors = sme_evaluator.evaluate_all(
            companies, profile, llm_settings, "Summer 2027", client=client
        )
        assert all(c.evaluation is not None for c in evaluated)
        assert errors == ()

    def test_original_order_is_preserved(self, profile, llm_settings):
        companies = tuple(make_sme(id=f"c{i}", name=f"Company {i}") for i in range(5))
        client = FakeClient([VALID_RESPONSE] * 5)
        evaluated, _ = sme_evaluator.evaluate_all(
            companies, profile, llm_settings, "Summer 2027", client=client
        )
        assert [c.id for c in evaluated] == [c.id for c in companies]

    def test_cached_evaluation_avoids_a_second_call(self, profile, llm_settings):
        company = make_sme()
        key = sme_evaluator.fingerprint(
            company, profile, llm_settings.model, "Summer 2027"
        )
        previous = (
            company.with_evaluation(SmeEvaluation(fit_score=91, fingerprint=key)),
        )
        client = FakeClient([VALID_RESPONSE])
        evaluated, _ = sme_evaluator.evaluate_all(
            (company,), profile, llm_settings, "Summer 2027",
            previous=previous, client=client,
        )
        assert client.calls == []
        assert evaluated[0].fit_score == 91

    def test_a_changed_description_invalidates_the_cache(self, profile, llm_settings):
        company = make_sme()
        key = sme_evaluator.fingerprint(
            company, profile, llm_settings.model, "Summer 2027"
        )
        previous = (
            company.with_evaluation(SmeEvaluation(fit_score=91, fingerprint=key)),
        )
        changed = make_sme(description="Now we build launchers.")
        client = FakeClient([VALID_RESPONSE])
        evaluated, _ = sme_evaluator.evaluate_all(
            (changed,), profile, llm_settings, "Summer 2027",
            previous=previous, client=client,
        )
        assert len(client.calls) == 1
        assert evaluated[0].fit_score == 78

    def test_a_changed_target_term_invalidates_the_cache(self, profile, llm_settings):
        company = make_sme()
        key = sme_evaluator.fingerprint(
            company, profile, llm_settings.model, "Summer 2027"
        )
        previous = (
            company.with_evaluation(SmeEvaluation(fit_score=91, fingerprint=key)),
        )
        client = FakeClient([VALID_RESPONSE])
        sme_evaluator.evaluate_all(
            (company,), profile, llm_settings, "Summer 2028",
            previous=previous, client=client,
        )
        assert len(client.calls) == 1

    def test_a_failed_cached_evaluation_is_not_reused(self, profile, llm_settings):
        company = make_sme()
        key = sme_evaluator.fingerprint(
            company, profile, llm_settings.model, "Summer 2027"
        )
        previous = (
            company.with_evaluation(
                SmeEvaluation(fit_score=0, fingerprint=key, error="boom")
            ),
        )
        client = FakeClient([VALID_RESPONSE])
        sme_evaluator.evaluate_all(
            (company,), profile, llm_settings, "Summer 2027",
            previous=previous, client=client,
        )
        assert len(client.calls) == 1

    def test_missing_api_key_returns_companies_unranked(self, profile):
        settings = LLMSettings(None, "https://api.test/v1", "m", 0.2, 60)
        companies = (make_sme(),)
        result, errors = sme_evaluator.evaluate_all(
            companies, profile, settings, "Summer 2027"
        )
        assert result == companies
        assert len(errors) == 1 and "LLM_API_KEY not set" in errors[0]

    def test_provider_failure_is_reported_per_company(self, profile, llm_settings):
        client = FakeClient([RuntimeError("gateway timeout")])
        evaluated, errors = sme_evaluator.evaluate_all(
            (make_sme(),), profile, llm_settings, "Summer 2027", client=client
        )
        assert evaluated[0].evaluation.error
        assert evaluated[0].fit_score == 0
        assert any("evaluation(s) failed" in e for e in errors)

    def test_budget_evaluates_the_most_relevant_companies_first(
        self, profile, llm_settings
    ):
        companies = (
            make_sme(id="thin", name="Thin SL", description="Space.", keywords=("software",)),
            make_sme(
                id="rich",
                name="Rich SL",
                description="Earth observation, machine learning and GIS pipelines.",
                keywords=("earth observation", "machine learning", "gis"),
            ),
        )
        client = FakeClient([VALID_RESPONSE])
        evaluated, errors = sme_evaluator.evaluate_all(
            companies, profile, llm_settings, "Summer 2027",
            client=client, max_evaluations=1,
        )
        assert len(client.calls) == 1
        assert "Rich SL" in client.calls[0]["messages"][1]["content"]
        by_id = {c.id: c for c in evaluated}
        assert by_id["rich"].evaluation is not None
        assert by_id["thin"].evaluation is None
        assert any("budget reached" in e for e in errors)

    def test_no_companies_short_circuits(self, profile, llm_settings):
        assert sme_evaluator.evaluate_all((), profile, llm_settings, "Summer 2027") == ((), ())

    def test_the_sme_system_prompt_is_used_not_the_opportunity_one(
        self, profile, llm_settings
    ):
        client = FakeClient([VALID_RESPONSE])
        sme_evaluator.evaluate_all(
            (make_sme(),), profile, llm_settings, "Summer 2027", client=client
        )
        system = client.calls[0]["messages"][0]["content"]
        assert "speculative summer internship" in system


class TestFingerprint:
    def test_same_inputs_produce_the_same_key(self, profile):
        company = make_sme()
        first = sme_evaluator.fingerprint(company, profile, "m", "Summer 2027")
        second = sme_evaluator.fingerprint(company, profile, "m", "Summer 2027")
        assert first == second

    def test_model_change_invalidates_the_key(self, profile):
        company = make_sme()
        assert sme_evaluator.fingerprint(
            company, profile, "m1", "Summer 2027"
        ) != sme_evaluator.fingerprint(company, profile, "m2", "Summer 2027")


class TestMergeEvaluations:
    def test_a_prior_score_is_carried_forward(self):
        current = (make_sme(),)
        previous = (make_sme(score=88),)
        merged = sme_evaluator.merge_evaluations(current, previous)
        assert merged[0].fit_score == 88

    def test_a_fresh_score_wins_over_the_prior_one(self):
        current = (make_sme(score=40),)
        previous = (make_sme(score=88),)
        assert sme_evaluator.merge_evaluations(current, previous)[0].fit_score == 40

    def test_a_failed_evaluation_falls_back_to_the_prior_score(self):
        failed = make_sme().with_evaluation(
            SmeEvaluation(fit_score=0, error="timeout")
        )
        merged = sme_evaluator.merge_evaluations((failed,), (make_sme(score=88),))
        assert merged[0].fit_score == 88

    def test_an_unknown_company_keeps_its_empty_evaluation(self):
        merged = sme_evaluator.merge_evaluations((make_sme(id="new"),), (make_sme(id="old", score=88),))
        assert merged[0].evaluation is None


class TestSmeState:
    def test_round_trip_preserves_the_document(self, tmp_path):
        snapshot = sme_state.build_snapshot(
            companies=[make_sme(score=70), make_sme(id="b", name="Beta", score=90)],
            countries=["Spain", "Italy"],
            keywords=["gis"],
            target_term="Summer 2027",
            scanned=42,
            evaluated=True,
        )
        path = tmp_path / "sme_matches.json"
        sme_state.save_snapshot(path, snapshot)
        loaded = sme_state.load_snapshot(path)
        assert loaded.scanned == 42
        assert loaded.target_term == "Summer 2027"
        assert loaded.evaluated is True
        assert [c.name for c in loaded.companies] == ["Beta", "Acme Geospatial SL"]

    def test_companies_are_stored_best_fit_first(self, tmp_path):
        snapshot = sme_state.build_snapshot(
            companies=[make_sme(id="low", score=10), make_sme(id="high", score=95)],
            countries=["Spain"], keywords=[], target_term="Summer 2027",
        )
        assert [c.id for c in snapshot.companies] == ["high", "low"]

    def test_a_missing_file_yields_an_empty_snapshot(self, tmp_path):
        loaded = sme_state.load_snapshot(tmp_path / "absent.json")
        assert loaded == SmeSnapshot.empty()

    def test_a_corrupt_file_yields_an_empty_snapshot(self, tmp_path):
        path = tmp_path / "sme_matches.json"
        path.write_text("{not json", encoding="utf-8")
        assert sme_state.load_snapshot(path).companies == ()

    def test_the_written_file_is_world_readable(self, tmp_path):
        path = tmp_path / "sme_matches.json"
        sme_state.save_snapshot(path, sme_state.build_snapshot([], [], [], "x"))
        assert path.stat().st_mode & 0o044

    def test_stats_count_by_country_and_strong_fit(self):
        snapshot = sme_state.build_snapshot(
            companies=[
                make_sme(id="a", score=95),
                make_sme(id="b", country_code="IT", country="Italy", score=40),
            ],
            countries=["Spain", "Italy"], keywords=[], target_term="Summer 2027",
        )
        stats = snapshot.stats(strong_fit_threshold=70)
        assert stats == {
            "scanned": 0, "matched": 2, "evaluated": 2,
            "strong_fit": 1, "spain": 1, "italy": 1,
        }
