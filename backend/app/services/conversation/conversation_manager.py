"""
Orchestrates a single conversation turn: normalize audio -> VAD -> STT ->
build context -> AI response -> TTS.

This is what both the WebSocket route and (indirectly) the standalone
Phase 3 REST endpoints exist to support -- the WebSocket route calls
straight into this rather than re-implementing the pipeline, and this
module in turn calls straight into the Phase 2 ProviderFactory and Phase 3
voice services rather than duplicating any of that logic.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import uuid

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings
from app.core.exceptions import AIProviderError, RateLimitError
from app.core.logging import get_logger
from app.db.collections import CONVERSATION_ANALYSIS
from app.services.ai.provider_factory import ProviderFactory
from app.services.analysis.ai_turn_analysis import RawTurnAnalysis, run_ai_turn_analysis
from app.services.analysis.confidence_analyzer import analyze_confidence
from app.services.analysis.fluency_analyzer import analyze_fluency
from app.services.analysis.grammar_analyzer import Correction, analyze_grammar
from app.services.analysis.pronunciation_analyzer import analyze_pronunciation
from app.services.analysis.scoring_engine import compute_turn_scores
from app.services.analysis.vocabulary_analyzer import VocabWord, analyze_vocabulary, persist_vocabulary
from app.services.conversation.context_manager import build_recent_messages, build_system_prompt
from app.services.storage import conversation_repository as repo
from app.services.storage.settings_repository import get_settings_doc
from app.services.voice.audio_processor import normalize_to_wav, wav_to_pcm16
from app.services.voice.gemini_stt import GeminiSpeechToText
from app.services.voice.gemini_tts import GeminiTextToSpeech
from app.services.voice.voice_activity_detector import VoiceActivityDetector

logger = get_logger(__name__)
_vad = VoiceActivityDetector(aggressiveness=2)


@dataclass
class TurnResult:
    """
    `contains_speech` only has meaning for `handle_user_turn` results (did
    server-side VAD find speech in the uploaded audio?). Opening-turn
    results from `generate_opening_message` always carry real assistant
    content and are sent via `_send_opening_result`, not `_send_turn_result`,
    so this flag is unused/irrelevant on those.
    """

    contains_speech: bool
    user_text: str = ""
    user_language: str = ""
    assistant_text: str = ""
    assistant_audio_wav: bytes = field(default=b"")
    assistant_sample_rate: int = 0
    conversation_ended: bool = False
    end_reason: str = ""
    corrections: list[Correction] = field(default_factory=list)
    new_words: list[VocabWord] = field(default_factory=list)
    scores: Optional[dict] = None


def is_conversation_expired(conversation: dict, max_minutes: int) -> bool:
    started_at = conversation["started_at"]
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    elapsed_minutes = (datetime.now(timezone.utc) - started_at).total_seconds() / 60
    return elapsed_minutes >= max_minutes


def _build_ai_and_tts(settings: Settings, conversation: dict):
    ai = ProviderFactory.create(
        conversation["ai_provider"], settings, conversation.get("ai_model", "")
    )
    tts = GeminiTextToSpeech(
        api_key=settings.gemini_api_key, timeout_seconds=settings.ai_request_timeout_seconds
    )
    return ai, tts


async def generate_opening_message(
    db: AsyncIOMotorDatabase, settings: Settings, conversation: dict
) -> TurnResult:
    """Called once, right after a conversation is created, so the AI speaks first."""
    system_prompt = build_system_prompt(
        conversation["topic"],
        conversation["difficulty"],
        conversation["mother_language"],
        conversation["target_language"],
    )
    ai, tts = _build_ai_and_tts(settings, conversation)

    opening_instruction = (
        "Start the conversation. Greet the learner briefly and ask an opening "
        "question related to the topic. 1-2 sentences."
    )
    assistant_text = await ai.generate_response(
        [{"role": "user", "content": opening_instruction}], system_prompt
    )
    await repo.add_message(db, conversation["_id"], "assistant", assistant_text, "en")

    synthesis = await tts.synthesize(assistant_text)

    return TurnResult(
        contains_speech=False,
        assistant_text=assistant_text,
        assistant_audio_wav=synthesis.wav_audio,
        assistant_sample_rate=synthesis.sample_rate,
    )


async def handle_user_turn(
    db: AsyncIOMotorDatabase,
    settings: Settings,
    conversation: dict,
    raw_audio: bytes,
    format_hint: str | None = None,
) -> TurnResult:
    if is_conversation_expired(conversation, settings.max_conversation_minutes):
        await repo.end_conversation(db, conversation["_id"])
        return TurnResult(contains_speech=False, conversation_ended=True, end_reason="time_limit")

    daily_count = await repo.count_assistant_messages_today(db)
    if daily_count >= settings.max_daily_ai_requests:
        raise RateLimitError(
            "Daily AI request limit reached. Please try again tomorrow.",
            "DAILY_LIMIT_REACHED",
        )

    normalized = normalize_to_wav(raw_audio, source_format_hint=format_hint)
    pcm, sample_rate = wav_to_pcm16(normalized.wav_bytes)
    vad_result = _vad.analyze(pcm, sample_rate=sample_rate)

    if not vad_result.contains_speech:
        return TurnResult(contains_speech=False)

    stt = GeminiSpeechToText(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_seconds=settings.ai_request_timeout_seconds,
    )
    transcription = await stt.transcribe(normalized.wav_bytes, sample_rate=normalized.sample_rate)

    if not transcription.text:
        # webrtcvad thought it heard speech but Gemini transcribed nothing
        # useful (e.g. a cough, background noise past the VAD threshold).
        return TurnResult(contains_speech=True, user_text="", user_language="")

    history_before = await repo.get_messages(db, conversation["_id"])
    response_latency_seconds = None
    if history_before:
        last_ts = history_before[-1]["timestamp"]
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        response_latency_seconds = (datetime.now(timezone.utc) - last_ts).total_seconds()

    user_message_doc = await repo.add_message(
        db, conversation["_id"], "user", transcription.text, transcription.detected_language
    )
    history = history_before + [user_message_doc]

    system_prompt = build_system_prompt(
        conversation["topic"],
        conversation["difficulty"],
        conversation["mother_language"],
        conversation["target_language"],
    )
    recent = build_recent_messages(history)

    ai, tts = _build_ai_and_tts(settings, conversation)
    assistant_text = await ai.generate_response(recent, system_prompt)
    await repo.add_message(db, conversation["_id"], "assistant", assistant_text, "en")

    synthesis = await tts.synthesize(assistant_text, speaking_speed=1.0)

    corrections, new_words, scores = await _analyze_turn(
        db, settings, conversation, ai, transcription.text, normalized.duration_seconds,
        response_latency_seconds,
    )

    return TurnResult(
        contains_speech=True,
        user_text=transcription.text,
        user_language=transcription.detected_language,
        assistant_text=assistant_text,
        assistant_audio_wav=synthesis.wav_audio,
        assistant_sample_rate=synthesis.sample_rate,
        corrections=corrections,
        new_words=new_words,
        scores=scores,
    )


async def _analyze_turn(
    db: AsyncIOMotorDatabase,
    settings: Settings,
    conversation: dict,
    ai,
    user_text: str,
    duration_seconds: float,
    response_latency_seconds: Optional[float],
) -> tuple[list[Correction], list[VocabWord], dict]:
    """
    Runs the full analysis pipeline for one user turn: grammar/vocabulary
    (one shared AI call, gated by app_settings so it costs nothing when the
    learner has both features turned off) plus fluency/confidence/
    pronunciation (always run -- pure local heuristics, no AI cost).

    Analysis failures never fail the turn itself -- a broken analysis call
    just means no corrections/vocabulary/scores for this turn, logged and
    swallowed, since the conversation reply has already been generated and
    spoken by the time this runs.
    """
    app_settings = await get_settings_doc(db)
    want_grammar_or_vocab = app_settings.get("show_corrections", True) or app_settings.get(
        "show_vocabulary", True
    )

    raw = RawTurnAnalysis(grammar_score=70, fluency_score_hint=70)
    if want_grammar_or_vocab:
        try:
            raw = await run_ai_turn_analysis(
                ai, user_text, conversation["mother_language"], conversation["target_language"]
            )
        except AIProviderError:
            logger.warning("turn_analysis_failed", extra={"conversation_id": conversation["_id"]})

    grammar = analyze_grammar(raw)
    vocabulary = analyze_vocabulary(raw)
    if vocabulary.words:
        await persist_vocabulary(db, vocabulary)

    fluency = analyze_fluency(user_text, duration_seconds)
    confidence = analyze_confidence(user_text, response_latency_seconds)
    pronunciation = analyze_pronunciation()

    turn_scores = compute_turn_scores(grammar, fluency, confidence, vocabulary, pronunciation, user_text)

    await db[CONVERSATION_ANALYSIS].insert_one(
        {
            "_id": uuid.uuid4().hex,
            "conversation_id": conversation["_id"],
            "grammar_score": turn_scores.grammar_score,
            "fluency_score": turn_scores.fluency_score,
            "confidence_score": turn_scores.confidence_score,
            "vocabulary_score": turn_scores.vocabulary_score,
            "pronunciation_score": turn_scores.pronunciation_score,
            "corrections": [c.__dict__ for c in grammar.corrections],
            "new_words": [w.__dict__ for w in vocabulary.words],
            "filler_word_count": fluency.filler_word_count,
            "created_at": datetime.now(timezone.utc),
        }
    )

    scores_payload = {
        "grammar": turn_scores.grammar_score,
        "fluency": turn_scores.fluency_score,
        "confidence": turn_scores.confidence_score,
        "vocabulary": turn_scores.vocabulary_score,
        "pronunciation": turn_scores.pronunciation_score,
        "pronunciation_note": pronunciation.note if turn_scores.pronunciation_score is None else "",
    }

    corrections = grammar.corrections if app_settings.get("show_corrections", True) else []
    new_words = vocabulary.words if app_settings.get("show_vocabulary", True) else []

    return corrections, new_words, scores_payload
