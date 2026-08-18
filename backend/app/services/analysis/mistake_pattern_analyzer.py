"""
Categorizes grammar corrections into broad mistake patterns (project spec
§40: "Frequent mistakes: 1. Past tense 2. Articles 3. Prepositions...").

Deliberately rule-based keyword matching on each correction's `explanation`
text -- not another AI call, and not real grammatical-error-type
classification (which would need a dedicated NLP model). This is a
best-effort bucket, not a linguistically rigorous taxonomy; corrections
that don't match a keyword land in "Other" rather than being force-fit
into a category they don't belong in.
"""
from collections import Counter
from dataclasses import dataclass

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Past tense": ["past tense", "past-tense", "completed action"],
    "Articles": ["article", '"a"', '"an"', '"the"'],
    "Prepositions": ["preposition"],
    "Subject-verb agreement": ["subject-verb", "subject verb", "agreement", "singular", "plural"],
    "Word choice": ["word choice", "wrong word", "collocation", "discuss about"],
}

_TIPS: dict[str, str] = {
    "Past tense": "Review regular/irregular past tense verb forms.",
    "Articles": 'Practice when to use "a", "an", and "the".',
    "Prepositions": "Review common preposition + verb/noun combinations.",
    "Subject-verb agreement": "Check that verbs match singular/plural subjects.",
    "Word choice": 'Watch for common word-choice slips like "discuss about" -> "discuss".',
    "Other": "Keep practicing -- review the corrections shown during your conversations.",
}


@dataclass
class MistakePattern:
    category: str
    count: int
    tip: str


def categorize_correction(explanation: str) -> str:
    lowered = explanation.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return category
    return "Other"


def find_frequent_mistakes(explanations: list[str], top_n: int = 5) -> list[MistakePattern]:
    categories = [categorize_correction(e) for e in explanations if e]
    counts = Counter(categories)

    # "Other" is a catch-all, not a genuinely actionable pattern -- keep it
    # from crowding out real categories at the top of the list even if
    # it happens to be the largest bucket.
    ranked = sorted(counts.items(), key=lambda kv: (kv[0] == "Other", -kv[1]))

    return [
        MistakePattern(category=category, count=count, tip=_TIPS.get(category, _TIPS["Other"]))
        for category, count in ranked[:top_n]
    ]
