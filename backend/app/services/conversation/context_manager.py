"""
Builds what gets sent to the AI provider for a given conversation turn: the
persona/system prompt and the recent message window.

Token-usage control (project spec §27, §47): rather than sending full
conversation history, only the most recent MAX_RECENT_MESSAGES are sent
verbatim, oldest ones dropped. Summarizing older context into a running
digest via an extra AI call would trim this further, but that's a second
paid AI request every turn purely to shrink the *next* request -- for a
coaching conversation capped at MAX_CONVERSATION_MINUTES (30 min default),
plain truncation keeps prompts small without that extra cost. Left as a
documented future enhancement rather than implemented here.
"""
from app.services.ai.base_provider import ChatMessage

MAX_RECENT_MESSAGES = 12

_PERSONA_TEMPLATE = """You are an AI English-speaking coach having a natural spoken conversation \
with a learner. Speak like a friendly, patient, encouraging conversation partner -- not a \
teacher lecturing. Keep replies SHORT: 1-3 sentences, since this is spoken aloud, not read.

Learner details:
- Mother tongue: {mother_language}
- Learning: {target_language}
- Level: {difficulty}
- Conversation topic: {topic}

Guidelines:
- Stay in character as a conversation partner discussing "{topic}".
- Don't correct every mistake -- keep the conversation flowing naturally. Corrections are \
shown separately in the UI, not spoken by you.
- Don't repeat back what the learner just said before responding.
- If the learner mixes in {mother_language}, respond naturally in English anyway.
- Never mock or point out mistakes sarcastically.
"""


def build_system_prompt(
    topic: str, difficulty: str, mother_language: str, target_language: str
) -> str:
    return _PERSONA_TEMPLATE.format(
        topic=topic,
        difficulty=difficulty,
        mother_language=mother_language,
        target_language=target_language,
    )


def build_recent_messages(messages: list[dict]) -> list[ChatMessage]:
    """
    `messages` is a list of stored message docs, oldest-first (as returned
    by conversation_repository.get_messages). Returns at most the last
    MAX_RECENT_MESSAGES, converted to the AIProvider's ChatMessage shape.
    """
    recent = messages[-MAX_RECENT_MESSAGES:]
    return [
        {"role": "assistant" if m["speaker"] == "assistant" else "user", "content": m["text"]}
        for m in recent
        if m.get("text")
    ]
