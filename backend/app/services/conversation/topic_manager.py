"""
Conversation topic selection (project spec §25).

"Surprise Me" and an unset topic both fall back to a random pick from the
preset list. Biasing that pick toward the learner's past mistakes ("You
made 8 past-tense mistakes... Recommended Practice: Past Tense
Conversation", spec §40) needs `learning_progress` data that doesn't exist
until Phase 5/6 -- this is a documented extension point, not implemented
here, so it isn't faked with a hardcoded heuristic that would need
throwing away later.
"""
import random

from app.schemas.conversation import CONVERSATION_TOPICS, SURPRISE_ME


def resolve_topic(requested: str | None) -> str:
    if not requested or requested == SURPRISE_ME:
        return random.choice(CONVERSATION_TOPICS)
    return requested
