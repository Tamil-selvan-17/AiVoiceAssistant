"""Tests for scoring_engine.build_conversation_summary and the streak logic
in learning_progress_repository -- both pure functions, no I/O."""
from app.services.analysis.scoring_engine import build_conversation_summary
from app.services.storage.learning_progress_repository import compute_next_streak


def test_summary_high_scores_produce_positive_highlights():
    summary = build_conversation_summary(
        grammar_scores=[90, 85],
        fluency_scores=[88, 90],
        confidence_scores=[85, 80],
        vocabulary_scores=[80, 85],
        total_filler_words=1,
        new_words_learned=2,
    )
    assert summary["overall_score"] >= 80
    assert any("grammar" in s.lower() for s in summary["what_went_well"])
    assert summary["improve_next_time"]  # always has at least one item


def test_summary_low_scores_produce_improvement_suggestions():
    summary = build_conversation_summary(
        grammar_scores=[40, 45],
        fluency_scores=[50, 45],
        confidence_scores=[40, 35],
        vocabulary_scores=[45, 40],
        total_filler_words=8,
        new_words_learned=0,
    )
    assert any("grammar" in s.lower() for s in summary["improve_next_time"])
    assert any("filler" in s.lower() for s in summary["improve_next_time"])
    assert summary["what_went_well"]  # always has at least one item, never empty


def test_summary_handles_no_analyzed_turns():
    summary = build_conversation_summary(
        grammar_scores=[], fluency_scores=[], confidence_scores=[], vocabulary_scores=[],
        total_filler_words=0, new_words_learned=0,
    )
    assert summary["overall_score"] == 0
    assert summary["what_went_well"]
    assert summary["improve_next_time"]


# --- streak logic ---


def test_streak_starts_at_one_for_first_conversation():
    assert compute_next_streak(None, "2026-08-12", 0) == 1


def test_streak_unchanged_for_second_conversation_same_day():
    assert compute_next_streak("2026-08-12", "2026-08-12", 3) == 3


def test_streak_increments_for_consecutive_day():
    assert compute_next_streak("2026-08-11", "2026-08-12", 3) == 4


def test_streak_resets_after_a_gap():
    assert compute_next_streak("2026-08-01", "2026-08-12", 5) == 1
