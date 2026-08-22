"""Tests for persistence and change detection."""

from __future__ import annotations

import json

import pytest

from agent import state_manager
from agent.models import Evaluation, Profile, Snapshot
from tests.conftest import make_opportunity


class TestDiff:
    def test_status_change_is_detected(self):
        previous = (make_opportunity(id="a", status="Pending"),)
        current = (make_opportunity(id="a", status="Open"),)
        events = state_manager.diff(previous, current)
        assert len(events) == 1
        assert events[0].kind == "status_change"
        assert events[0].previous_status == "Pending"
        assert events[0].is_notifiable

    def test_unchanged_opportunity_produces_no_event(self):
        same = (make_opportunity(id="a", status="Open", deadline="2027-06-01"),)
        assert state_manager.diff(same, same) == ()

    def test_new_open_high_scoring_opportunity_is_notifiable(self):
        current = (make_opportunity(id="new", status="Open", score=85),)
        events = state_manager.diff((), current, notify_threshold=70)
        assert events[0].kind == "new_high_match"
        assert events[0].is_notifiable

    def test_new_opportunity_below_threshold_is_informational_only(self):
        current = (make_opportunity(id="new", status="Open", score=40),)
        events = state_manager.diff((), current, notify_threshold=70)
        assert events[0].kind == "new_opportunity"
        assert not events[0].is_notifiable

    def test_new_but_pending_opportunity_is_not_a_high_match(self):
        """A high score on something you cannot apply to yet is not urgent."""
        current = (make_opportunity(id="new", status="Pending", score=95),)
        events = state_manager.diff((), current, notify_threshold=70)
        assert events[0].kind == "new_opportunity"

    def test_score_exactly_at_threshold_notifies(self):
        current = (make_opportunity(id="new", status="Open", score=70),)
        events = state_manager.diff((), current, notify_threshold=70)
        assert events[0].kind == "new_high_match"

    def test_imminent_deadline_is_flagged(self, today, monkeypatch):
        monkeypatch.setattr(state_manager.dates, "today_utc", lambda: today)
        opportunity = make_opportunity(id="a", status="Open", deadline="2026-08-25")
        events = state_manager.diff((opportunity,), (opportunity,))
        assert len(events) == 1
        assert events[0].kind == "deadline_soon"
        assert not events[0].is_notifiable

    def test_distant_deadline_is_not_flagged(self, today, monkeypatch):
        monkeypatch.setattr(state_manager.dates, "today_utc", lambda: today)
        opportunity = make_opportunity(id="a", status="Open", deadline="2027-08-25")
        assert state_manager.diff((opportunity,), (opportunity,)) == ()

    def test_events_are_ordered_by_importance(self):
        previous = (make_opportunity(id="a", status="Pending"),)
        current = (
            make_opportunity(id="b", status="Open", score=90),  # new_high_match
            make_opportunity(id="c", status="Open", score=10),  # new_opportunity
            make_opportunity(id="a", status="Open"),            # status_change
        )
        kinds = [e.kind for e in state_manager.diff(previous, current)]
        assert kinds == ["status_change", "new_high_match", "new_opportunity"]

    def test_disappearing_opportunity_produces_no_event(self):
        """A delisted row is silent — ESA removes rows routinely."""
        previous = (make_opportunity(id="gone"),)
        assert state_manager.diff(previous, ()) == ()


class TestFirstRun:
    def test_empty_previous_state_is_a_first_run(self):
        assert state_manager.is_first_run(Snapshot.empty()) is True

    def test_populated_state_is_not_a_first_run(self):
        snapshot = Snapshot(generated_at="x", opportunities=(make_opportunity(),))
        assert state_manager.is_first_run(snapshot) is False


class TestPersistence:
    def test_save_then_load_round_trips(self, tmp_path, profile):
        path = tmp_path / "opportunities.json"
        snapshot = state_manager.build_snapshot(
            opportunities=(make_opportunity(id="a", score=77),),
            profile=profile,
            errors=("warn",),
        )
        state_manager.save_snapshot(path, snapshot)

        loaded = state_manager.load_snapshot(path)
        assert len(loaded.opportunities) == 1
        assert loaded.opportunities[0].id == "a"
        assert loaded.opportunities[0].match_score == 77
        assert loaded.profile.name == profile.name
        assert loaded.profile.github.username == "teoclerici"

    def test_saved_file_contains_stats_for_the_dashboard(self, tmp_path, profile):
        path = tmp_path / "opportunities.json"
        snapshot = state_manager.build_snapshot(
            opportunities=(
                make_opportunity(id="a", status="Open", score=90),
                make_opportunity(id="b", status="Closed", score=10),
            ),
            profile=profile,
        )
        state_manager.save_snapshot(path, snapshot, high_fit_threshold=80)

        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["stats"] == {
            "total": 2, "open": 1, "pending": 0, "closed": 1,
            "high_fit": 1, "evaluated": 2,
        }

    def test_missing_file_yields_an_empty_snapshot(self, tmp_path):
        loaded = state_manager.load_snapshot(tmp_path / "absent.json")
        assert loaded.opportunities == ()

    def test_corrupt_file_degrades_instead_of_raising(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        assert state_manager.load_snapshot(path).opportunities == ()

    def test_non_object_json_degrades(self, tmp_path):
        path = tmp_path / "list.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        assert state_manager.load_snapshot(path).opportunities == ()

    def test_write_leaves_no_temp_files_behind(self, tmp_path, profile):
        path = tmp_path / "opportunities.json"
        snapshot = state_manager.build_snapshot((make_opportunity(),), profile)
        state_manager.save_snapshot(path, snapshot)
        assert [p.name for p in tmp_path.iterdir()] == ["opportunities.json"]

    def test_save_creates_missing_parent_directories(self, tmp_path, profile):
        path = tmp_path / "nested" / "deep" / "opportunities.json"
        state_manager.save_snapshot(
            path, state_manager.build_snapshot((make_opportunity(),), profile)
        )
        assert path.exists()


class TestCarryForward:
    def test_first_seen_is_preserved_across_runs(self):
        previous = (make_opportunity(id="a").seen_at("2026-01-01T00:00:00Z"),)
        current = (make_opportunity(id="a"),)
        stamped = state_manager.carry_forward(current, previous, "2026-08-17T00:00:00Z")
        assert stamped[0].first_seen == "2026-01-01T00:00:00Z"
        assert stamped[0].last_seen == "2026-08-17T00:00:00Z"

    def test_new_opportunity_gets_first_seen_now(self):
        stamped = state_manager.carry_forward(
            (make_opportunity(id="new"),), (), "2026-08-17T00:00:00Z"
        )
        assert stamped[0].first_seen == stamped[0].last_seen == "2026-08-17T00:00:00Z"

    def test_inputs_are_not_mutated(self):
        original = make_opportunity(id="a")
        state_manager.carry_forward((original,), (), "2026-08-17T00:00:00Z")
        assert original.last_seen == ""


class TestMergeEvaluations:
    def test_prior_score_is_reused_when_this_run_failed(self):
        previous = (make_opportunity(id="a", score=82),)
        current = (
            make_opportunity(id="a").with_evaluation(
                Evaluation(match_score=0, error="provider timeout")
            ),
        )
        merged = state_manager.merge_evaluations(current, previous)
        assert merged[0].match_score == 82

    def test_prior_score_is_reused_when_evaluation_is_absent(self):
        previous = (make_opportunity(id="a", score=82),)
        current = (make_opportunity(id="a"),)
        assert state_manager.merge_evaluations(current, previous)[0].match_score == 82

    def test_fresh_evaluation_wins_over_the_cached_one(self):
        previous = (make_opportunity(id="a", score=82),)
        current = (make_opportunity(id="a", score=91),)
        assert state_manager.merge_evaluations(current, previous)[0].match_score == 91

    def test_unknown_opportunity_passes_through(self):
        current = (make_opportunity(id="brand-new"),)
        assert state_manager.merge_evaluations(current, ())[0].evaluation is None


class TestSortForDisplay:
    def test_open_first_then_score_then_deadline(self):
        opportunities = (
            make_opportunity(id="closed", status="Closed", score=99),
            make_opportunity(id="open-low", status="Open", score=20),
            make_opportunity(id="open-high", status="Open", score=95),
            make_opportunity(id="pending", status="Pending", score=50),
        )
        order = [o.id for o in state_manager.sort_for_display(opportunities)]
        assert order == ["open-high", "open-low", "pending", "closed"]

    def test_undated_opportunities_sort_last_within_a_tie(self):
        opportunities = (
            make_opportunity(id="undated", status="Open", score=50, deadline=""),
            make_opportunity(id="dated", status="Open", score=50, deadline="2026-09-01"),
        )
        order = [o.id for o in state_manager.sort_for_display(opportunities)]
        assert order == ["dated", "undated"]
