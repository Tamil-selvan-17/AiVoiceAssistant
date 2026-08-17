"""
Minimal tests for topic/context selection logic. Pure functions, no I/O --
kept lean since the heavier integration coverage lives in
test_conversation_websocket.py.
"""
from app.schemas.conversation import CONVERSATION_TOPICS
from app.services.conversation.context_manager import (
    MAX_RECENT_MESSAGES,
    build_recent_messages,
    build_system_prompt,
)
from app.services.conversation.topic_manager import resolve_topic


def test_resolve_topic_passes_through_explicit_choice():
    assert resolve_topic("Job Interview") == "Job Interview"


def test_resolve_topic_surprise_me_picks_a_known_topic():
    for _ in range(10):
        assert resolve_topic("Surprise Me") in CONVERSATION_TOPICS


def test_resolve_topic_none_picks_a_known_topic():
    assert resolve_topic(None) in CONVERSATION_TOPICS


def test_build_system_prompt_includes_learner_details():
    prompt = build_system_prompt("Job Interview", "advanced", "Tamil", "English")
    assert "Job Interview" in prompt
    assert "advanced" in prompt
    assert "Tamil" in prompt


def test_build_recent_messages_maps_speaker_to_role():
    messages = [
        {"speaker": "user", "text": "Hi"},
        {"speaker": "assistant", "text": "Hello!"},
    ]
    result = build_recent_messages(messages)
    assert result == [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
    ]


def test_build_recent_messages_truncates_to_max_recent():
    messages = [{"speaker": "user", "text": f"msg {i}"} for i in range(MAX_RECENT_MESSAGES + 5)]
    result = build_recent_messages(messages)
    assert len(result) == MAX_RECENT_MESSAGES
    # Truncation should keep the most recent ones, not the oldest.
    assert result[-1]["content"] == f"msg {MAX_RECENT_MESSAGES + 4}"
