"""Tests for the rule-based mistake pattern categorizer."""
from app.services.analysis.mistake_pattern_analyzer import categorize_correction, find_frequent_mistakes


def test_categorize_past_tense():
    assert categorize_correction("Use past tense for completed actions.") == "Past tense"


def test_categorize_articles():
    assert categorize_correction('You need "the" before this noun.') == "Articles"


def test_categorize_unmatched_falls_back_to_other():
    assert categorize_correction("This is a strange edge case explanation.") == "Other"


def test_find_frequent_mistakes_ranks_by_count():
    explanations = [
        "Use past tense for completed actions.",
        "Use past tense here too.",
        'Missing "the" article.',
    ]
    patterns = find_frequent_mistakes(explanations)
    assert patterns[0].category == "Past tense"
    assert patterns[0].count == 2


def test_find_frequent_mistakes_deprioritizes_other():
    explanations = ["weird one", "weird two", "weird three", "Use past tense here."]
    patterns = find_frequent_mistakes(explanations)
    # "Other" has 3 occurrences (more than "Past tense"'s 1) but should not
    # be ranked first -- it's a catch-all, not an actionable pattern.
    assert patterns[0].category == "Past tense"


def test_find_frequent_mistakes_empty_input():
    assert find_frequent_mistakes([]) == []
