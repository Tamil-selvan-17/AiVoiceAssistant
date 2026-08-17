"""
Tests for the pure-logic analyzers -- no AI calls, no Mongo. These are the
cheapest, highest-value tests in Phase 5 since fluency/confidence/scoring
are deterministic heuristics that must behave predictably.
"""
from app.services.analysis.ai_turn_analysis import RawTurnAnalysis
from app.services.analysis.confidence_analyzer import analyze_confidence
from app.services.analysis.fluency_analyzer import analyze_fluency, count_filler_words
from app.services.analysis.grammar_analyzer import analyze_grammar
from app.services.analysis.pronunciation_analyzer import analyze_pronunciation
from app.services.analysis.scoring_engine import compute_overall_score, compute_vocabulary_score
from app.services.analysis.vocabulary_analyzer import analyze_vocabulary


# --- fluency_analyzer ---


def test_count_filler_words_matches_single_and_multi_word_fillers():
    count, matches = count_filler_words("um I like actually went to the you know office")
    assert count == 4  # um, like, actually, you know
    assert "you know" in matches


def test_fluency_score_penalized_by_filler_density():
    clean = analyze_fluency("I went to the office yesterday and finished the report", duration_seconds=4.0)
    fillery = analyze_fluency("um uh like I actually um went you know", duration_seconds=4.0)
    assert fillery.score < clean.score


def test_fluency_very_short_utterance_capped():
    result = analyze_fluency("yes", duration_seconds=1.0)
    assert result.score <= 60


# --- confidence_analyzer ---


def test_confidence_penalized_by_short_answer():
    short = analyze_confidence("yes", response_latency_seconds=1.0)
    full = analyze_confidence(
        "I think we should meet on Tuesday to discuss the project timeline",
        response_latency_seconds=1.0,
    )
    assert short.score < full.score


def test_confidence_penalized_by_long_latency():
    fast = analyze_confidence("I went to the office yesterday", response_latency_seconds=1.0)
    slow = analyze_confidence("I went to the office yesterday", response_latency_seconds=10.0)
    assert slow.score < fast.score


def test_confidence_label_is_the_spec_required_wording():
    result = analyze_confidence("hello there", response_latency_seconds=None)
    assert result.label == "AI-generated practice metric"


# --- pronunciation_analyzer (honest stub) ---


def test_pronunciation_analyzer_returns_none_not_a_fake_score():
    result = analyze_pronunciation()
    assert result.score is None
    assert "phoneme" in result.note.lower() or "acoustic" in result.note.lower()


# --- grammar_analyzer / vocabulary_analyzer (parse the shared AI result) ---


def test_grammar_analyzer_filters_no_op_corrections():
    raw = RawTurnAnalysis(
        grammar_score=85,
        fluency_score_hint=80,
        corrections=[
            {"original": "I go office", "corrected": "I went to the office", "explanation": "past tense"},
            {"original": "hello", "corrected": "hello", "explanation": "no change"},  # should be filtered
            {"original": "", "corrected": "something", "explanation": "missing original"},  # filtered
        ],
    )
    result = analyze_grammar(raw)
    assert len(result.corrections) == 1
    assert result.corrections[0].original == "I go office"
    assert result.grammar_score == 85


def test_vocabulary_analyzer_filters_incomplete_words():
    raw = RawTurnAnalysis(
        grammar_score=80,
        fluency_score_hint=80,
        new_words=[
            {"word": "discuss", "meaning": "talk about", "difficulty": "intermediate"},
            {"word": "", "meaning": "missing word"},  # filtered
            {"word": "onlyword"},  # filtered, no meaning
        ],
    )
    result = analyze_vocabulary(raw)
    assert len(result.words) == 1
    assert result.words[0].word == "discuss"
    assert result.words[0].difficulty == "intermediate"


def test_vocabulary_analyzer_defaults_invalid_difficulty_to_beginner():
    raw = RawTurnAnalysis(
        grammar_score=80,
        fluency_score_hint=80,
        new_words=[{"word": "test", "meaning": "a trial", "difficulty": "expert-level-nonsense"}],
    )
    result = analyze_vocabulary(raw)
    assert result.words[0].difficulty == "beginner"


# --- scoring_engine ---


def test_compute_vocabulary_score_rewards_new_words():
    baseline = compute_vocabulary_score("I went to the office", new_word_count=0)
    with_new_words = compute_vocabulary_score("I went to the office", new_word_count=2)
    assert with_new_words > baseline


def test_compute_overall_score_excludes_none_pronunciation():
    # Pronunciation is always None (honest stub) -- it must not drag the
    # average toward zero.
    overall = compute_overall_score({"grammar": 80, "fluency": 80, "pronunciation": None})
    assert overall == 80


def test_compute_overall_score_empty_returns_zero():
    assert compute_overall_score({"grammar": None}) == 0
