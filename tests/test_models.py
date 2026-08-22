"""Tests for the immutable domain models and their JSON contract."""

from __future__ import annotations

import dataclasses

import pytest

from agent.categorize import ALL_CATEGORIES, categorize
from agent.models import (
    STATUS_CLOSED,
    STATUS_OPEN,
    STATUS_UNKNOWN,
    ChangeEvent,
    ChecklistItem,
    Evaluation,
    Opportunity,
    Profile,
    Snapshot,
    index_by_id,
)
from tests.conftest import make_opportunity


class TestImmutability:
    def test_opportunity_cannot_be_mutated(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            make_opportunity().title = "changed"

    def test_with_evaluation_returns_a_new_object(self):
        original = make_opportunity()
        updated = original.with_evaluation(Evaluation(match_score=50))
        assert original.evaluation is None
        assert updated.match_score == 50
        assert updated is not original

    def test_seen_at_returns_a_new_object(self):
        original = make_opportunity()
        updated = original.seen_at("2026-08-17T00:00:00Z")
        assert original.last_seen == ""
        assert updated.last_seen == "2026-08-17T00:00:00Z"


class TestContentHash:
    def test_identical_content_hashes_alike(self):
        assert make_opportunity().content_hash() == make_opportunity().content_hash()

    def test_status_change_changes_the_hash(self):
        assert (
            make_opportunity(status="Open").content_hash()
            != make_opportunity(status="Pending").content_hash()
        )

    def test_timestamps_do_not_affect_the_hash(self):
        """Re-scraping unchanged content must not invalidate the LLM cache."""
        base = make_opportunity()
        assert base.content_hash() == base.seen_at("2026-08-17T00:00:00Z").content_hash()

    def test_evaluation_does_not_affect_the_hash(self):
        base = make_opportunity()
        scored = base.with_evaluation(Evaluation(match_score=90))
        assert base.content_hash() == scored.content_hash()


class TestSerialisation:
    def test_opportunity_round_trips(self):
        original = make_opportunity(score=77, location="Noordwijk, NL")
        restored = Opportunity.from_dict(original.to_dict())
        assert restored.id == original.id
        assert restored.match_score == 77
        assert restored.location == "Noordwijk, NL"

    def test_unknown_status_degrades_rather_than_raising(self):
        assert Opportunity.from_dict({"status": "Bogus"}).status == STATUS_UNKNOWN

    def test_status_matching_is_case_insensitive(self):
        assert Opportunity.from_dict({"status": "OPEN"}).status == STATUS_OPEN

    def test_missing_fields_get_safe_defaults(self):
        restored = Opportunity.from_dict({})
        assert restored.title == "" and restored.evaluation is None

    def test_evaluation_round_trips_with_nested_items(self):
        evaluation = Evaluation(
            match_score=80,
            checklist=(ChecklistItem(task="Do X", effort="1h", done_when="X done"),),
            why_apply=("reason",),
        )
        restored = Evaluation.from_dict(evaluation.to_dict())
        assert restored.checklist[0].done_when == "X done"
        assert restored.why_apply == ("reason",)

    def test_profile_round_trips(self, profile):
        restored = Profile.from_dict(profile.to_dict())
        assert restored.name == profile.name
        assert restored.github.repos[0].name == "synapse"

    def test_raw_cv_text_is_excluded_by_default(self, profile):
        """The CV text should not be published to the dashboard JSON."""
        from dataclasses import replace

        with_text = replace(profile, raw_text="sensitive full CV body")
        assert "raw_text" not in with_text.to_dict()
        assert with_text.to_dict(include_raw=True)["raw_text"] == "sensitive full CV body"

    def test_snapshot_round_trips(self, profile):
        snapshot = Snapshot(
            generated_at="2026-08-17T00:00:00Z",
            opportunities=(make_opportunity(score=90),),
            profile=profile,
            errors=("a warning",),
        )
        restored = Snapshot.from_dict(snapshot.to_dict())
        assert restored.generated_at == snapshot.generated_at
        assert restored.opportunities[0].match_score == 90
        assert restored.errors == ("a warning",)


class TestStats:
    def test_counts_by_status_and_fit(self):
        snapshot = Snapshot(
            generated_at="",
            opportunities=(
                make_opportunity(id="a", status="Open", score=95),
                make_opportunity(id="b", status="Open", score=40),
                make_opportunity(id="c", status="Pending", score=85),
                make_opportunity(id="d", status="Closed"),
            ),
        )
        stats = snapshot.stats(high_fit_threshold=80)
        assert stats == {
            "total": 4, "open": 2, "pending": 1, "closed": 1,
            "high_fit": 2, "evaluated": 3,
        }

    def test_threshold_is_inclusive(self):
        snapshot = Snapshot(
            generated_at="", opportunities=(make_opportunity(score=80),)
        )
        assert snapshot.stats(high_fit_threshold=80)["high_fit"] == 1

    def test_empty_snapshot_stats(self):
        assert Snapshot.empty().stats()["total"] == 0


class TestChangeEvent:
    @pytest.mark.parametrize(
        "kind,expected",
        [
            ("status_change", True),
            ("new_high_match", True),
            ("new_opportunity", False),
            ("deadline_soon", False),
        ],
    )
    def test_notifiability(self, kind, expected):
        assert ChangeEvent(kind=kind, opportunity=make_opportunity()).is_notifiable is expected

    def test_serialises_the_fields_the_dashboard_shows(self):
        payload = ChangeEvent(
            kind="status_change",
            opportunity=make_opportunity(score=88),
            previous_status="Pending",
        ).to_dict()
        assert payload["match_score"] == 88
        assert payload["previous_status"] == "Pending"


class TestHelpers:
    def test_index_by_id(self):
        opportunities = (make_opportunity(id="a"), make_opportunity(id="b"))
        assert set(index_by_id(opportunities)) == {"a", "b"}

    def test_match_score_is_zero_without_an_evaluation(self):
        assert make_opportunity().match_score == 0


class TestCategorize:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("SPAICE (AI in and for space)", "Earth Observation & AI"),
            ("Earth Observation training", "Earth Observation & AI"),
            ("Navigation Training Course", "Robotics & Software"),
            ("Flight Software Engineer", "Robotics & Software"),
            ("CubeSat Hands-On Training Week", "Space Systems"),
            ("14th European Space Power Conference", "Space Systems"),
            ("Mission Operations Engineer", "Operations & Ground Segment"),
            ("Commercialisation of space data", "Business & Policy"),
            ("Planetary science summer school", "Space Science"),
            ("", "Other"),
        ],
    )
    def test_known_titles_land_in_the_right_category(self, text, expected):
        assert categorize(text) == expected

    def test_specific_rules_outrank_the_generic_engineer_fallback(self):
        """"engineer" must never beat a precise signal like "robotic"."""
        assert categorize("Robotics Engineer") == "Robotics & Software"

    def test_generic_engineer_falls_back_to_space_systems(self):
        assert categorize("System and Applications Engineer") == "Space Systems"

    def test_every_result_is_a_declared_category(self):
        for text in ("random text", "engineer", "AI", ""):
            assert categorize(text) in ALL_CATEGORIES

    def test_multiple_fragments_are_considered(self):
        assert categorize("Untitled", "", "Conference on antennas") == "Space Systems"
