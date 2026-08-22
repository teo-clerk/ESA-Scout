"""Tests for LLM evaluation: prompting, parsing, caching and degradation.

No network is used — a fake OpenAI-compatible client records calls and returns
scripted responses.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent import evaluator
from agent.config import LLMSettings
from agent.models import Evaluation
from tests.conftest import make_opportunity

VALID_RESPONSE = json.dumps(
    {
        "match_score": 84,
        "justification": "Strong overlap with your ML background.",
        "why_apply": ["Direct ESA exposure"],
        "required_skills": ["Python", "Remote sensing"],
        "gaps": ["No prior SAR experience"],
        "checklist": [
            {"task": "Read the Sentinel-1 primer", "effort": "3 hours", "done_when": "Notes written"}
        ],
        "key_deadlines": [{"label": "Application", "date": "2026-11-01"}],
    }
)


class FakeClient:
    """Minimal stand-in for the OpenAI client surface the evaluator uses."""

    def __init__(self, responses, fail_on_response_format=False):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self._fail_on_response_format = fail_on_response_format
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        if self._fail_on_response_format and "response_format" in kwargs:
            raise TypeError("response_format is not supported by this provider")
        self.calls.append(kwargs)
        content = self._responses.pop(0) if self._responses else VALID_RESPONSE
        if isinstance(content, Exception):
            raise content
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
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


class TestPromptBuilding:
    def test_prompt_includes_profile_and_opportunity(self, profile):
        prompt = evaluator.build_prompt(make_opportunity(title="EO Course"), profile)
        assert "Teo Clerici Jurado" in prompt
        assert "EO Course" in prompt
        assert "Machine Learning" in prompt

    def test_prompt_includes_github_repositories(self, profile):
        prompt = evaluator.build_prompt(make_opportunity(), profile)
        assert "synapse" in prompt
        assert "@teoclerici" in prompt

    def test_prompt_reports_github_failure_rather_than_omitting_it(self, profile):
        from dataclasses import replace

        from agent.models import GitHubProfile

        degraded = replace(profile, github=GitHubProfile(error="rate limited"))
        assert "unavailable (rate limited)" in evaluator.build_prompt(
            make_opportunity(), degraded
        )

    def test_empty_profile_does_not_break_prompting(self):
        from agent.models import Profile

        prompt = evaluator.build_prompt(make_opportunity(), Profile())
        assert "No profile information available." in prompt


class TestResponseParsing:
    def test_valid_json_is_parsed_fully(self):
        result = evaluator.parse_response(VALID_RESPONSE, "m", "fp")
        assert result.match_score == 84
        assert result.required_skills == ("Python", "Remote sensing")
        assert result.checklist[0].task == "Read the Sentinel-1 primer"
        assert result.key_deadlines[0].date == "2026-11-01"
        assert result.fingerprint == "fp"
        assert result.error == ""

    def test_json_wrapped_in_prose_is_recovered(self):
        wrapped = f"Sure! Here you go:\n```json\n{VALID_RESPONSE}\n```\nHope that helps."
        assert evaluator.parse_response(wrapped, "m", "fp").match_score == 84

    def test_non_json_reply_becomes_an_error_not_an_exception(self):
        result = evaluator.parse_response("I cannot help with that.", "m", "fp")
        assert result.match_score == 0
        assert "not valid JSON" in result.error

    def test_empty_reply_becomes_an_error(self):
        assert "empty response" in evaluator.parse_response("", "m", "fp").error

    @pytest.mark.parametrize(
        "raw,expected", [(150, 100), (-20, 0), ("77", 77), (None, 0), ("abc", 0), (66.7, 67)]
    )
    def test_scores_are_clamped_and_coerced(self, raw, expected):
        payload = json.dumps({"match_score": raw})
        assert evaluator.parse_response(payload, "m", "fp").match_score == expected

    def test_checklist_accepts_plain_strings(self):
        payload = json.dumps({"match_score": 50, "checklist": ["Do the thing"]})
        result = evaluator.parse_response(payload, "m", "fp")
        assert result.checklist[0].task == "Do the thing"


class TestEvaluateAll:
    def test_every_opportunity_receives_an_evaluation(self, profile, llm_settings):
        client = FakeClient([VALID_RESPONSE, VALID_RESPONSE])
        opportunities = (make_opportunity(id="a"), make_opportunity(id="b", title="B"))
        result, errors = evaluator.evaluate_all(
            opportunities, profile, llm_settings, client=client
        )
        assert errors == ()
        assert all(o.evaluation is not None for o in result)
        assert len(client.calls) == 2

    def test_original_order_is_preserved(self, profile, llm_settings):
        client = FakeClient([VALID_RESPONSE] * 3)
        opportunities = tuple(
            make_opportunity(id=f"id-{i}", title=f"T{i}") for i in range(3)
        )
        result, _ = evaluator.evaluate_all(
            opportunities, profile, llm_settings, client=client
        )
        assert [o.id for o in result] == ["id-0", "id-1", "id-2"]

    def test_cached_evaluation_avoids_a_second_call(self, profile, llm_settings):
        opportunity = make_opportunity(id="a")
        key = evaluator.fingerprint(opportunity, profile, llm_settings.model)
        previous = (
            opportunity.with_evaluation(
                Evaluation(match_score=73, fingerprint=key, justification="cached")
            ),
        )
        client = FakeClient([])
        result, _ = evaluator.evaluate_all(
            (opportunity,), profile, llm_settings, previous=previous, client=client
        )
        assert client.calls == []
        assert result[0].match_score == 73

    def test_changed_content_invalidates_the_cache(self, profile, llm_settings):
        original = make_opportunity(id="a", status="Pending")
        key = evaluator.fingerprint(original, profile, llm_settings.model)
        previous = (
            original.with_evaluation(Evaluation(match_score=73, fingerprint=key)),
        )
        # Same id, different status -> different content hash -> re-evaluate.
        changed = make_opportunity(id="a", status="Open")
        client = FakeClient([VALID_RESPONSE])
        result, _ = evaluator.evaluate_all(
            (changed,), profile, llm_settings, previous=previous, client=client
        )
        assert len(client.calls) == 1
        assert result[0].match_score == 84

    def test_a_failed_cached_evaluation_is_not_reused(self, profile, llm_settings):
        opportunity = make_opportunity(id="a")
        key = evaluator.fingerprint(opportunity, profile, llm_settings.model)
        previous = (
            opportunity.with_evaluation(
                Evaluation(match_score=0, fingerprint=key, error="timeout")
            ),
        )
        client = FakeClient([VALID_RESPONSE])
        evaluator.evaluate_all(
            (opportunity,), profile, llm_settings, previous=previous, client=client
        )
        assert len(client.calls) == 1

    def test_missing_api_key_returns_unevaluated_opportunities(self, profile):
        settings = LLMSettings(
            api_key=None, base_url="x", model="m", temperature=0.0, max_opportunities=10
        )
        result, errors = evaluator.evaluate_all(
            (make_opportunity(),), profile, settings
        )
        assert result[0].evaluation is None
        assert "LLM_API_KEY not set" in errors[0]

    def test_provider_failure_is_reported_per_opportunity(self, profile, llm_settings):
        client = FakeClient([RuntimeError("503 upstream"), VALID_RESPONSE])
        result, errors = evaluator.evaluate_all(
            (make_opportunity(id="a"), make_opportunity(id="b")),
            profile,
            llm_settings,
            client=client,
            max_workers=1,
        )
        assert any("evaluation(s) failed" in e for e in errors)
        # The healthy one still scored.
        assert max(o.match_score for o in result) == 84

    def test_provider_rejecting_response_format_falls_back(self, profile, llm_settings):
        client = FakeClient([VALID_RESPONSE], fail_on_response_format=True)
        result, errors = evaluator.evaluate_all(
            (make_opportunity(),), profile, llm_settings, client=client
        )
        assert errors == ()
        assert result[0].match_score == 84
        assert "response_format" not in client.calls[0]

    def test_budget_limits_the_number_of_calls(self, profile):
        settings = LLMSettings(
            api_key="k", base_url="x", model="m", temperature=0.0, max_opportunities=2
        )
        client = FakeClient([VALID_RESPONSE] * 5)
        opportunities = tuple(make_opportunity(id=f"i{n}", title=f"T{n}") for n in range(5))
        _, errors = evaluator.evaluate_all(
            opportunities, profile, settings, client=client
        )
        assert len(client.calls) == 2
        assert any("budget reached" in e for e in errors)

    def test_no_opportunities_short_circuits(self, profile, llm_settings):
        assert evaluator.evaluate_all((), profile, llm_settings) == ((), ())


class TestFingerprint:
    def test_same_inputs_produce_the_same_key(self, profile, llm_settings):
        opportunity = make_opportunity()
        a = evaluator.fingerprint(opportunity, profile, "m")
        b = evaluator.fingerprint(opportunity, profile, "m")
        assert a == b

    def test_model_change_invalidates_the_key(self, profile):
        opportunity = make_opportunity()
        assert evaluator.fingerprint(opportunity, profile, "m1") != evaluator.fingerprint(
            opportunity, profile, "m2"
        )

    def test_profile_change_invalidates_the_key(self, profile):
        from dataclasses import replace

        opportunity = make_opportunity()
        updated = replace(profile, skills=profile.skills + ("Rust",))
        assert evaluator.fingerprint(opportunity, profile, "m") != evaluator.fingerprint(
            opportunity, updated, "m"
        )
