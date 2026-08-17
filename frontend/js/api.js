/**
 * Thin fetch wrappers around the Phase 3 voice endpoints. Kept separate
 * from voice.js so the conversation/WebSocket code arriving in Phase 4 can
 * reuse these without depending on the mic-capture/state-machine logic.
 */
const Api = (() => {
  async function parseErrorOrThrow(response) {
    let body = null;
    try {
      body = await response.json();
    } catch (_) {
      // Non-JSON error body -- fall through to a generic message.
    }
    const message = (body && body.message) || `Request failed (${response.status})`;
    const error = new Error(message);
    error.status = response.status;
    error.errorCode = body && body.error_code;
    throw error;
  }

  /**
   * Upload a recorded audio blob for VAD-only analysis (no transcription).
   * @param {Blob} audioBlob
   */
  async function checkVad(audioBlob) {
    const form = new FormData();
    form.append("file", audioBlob, "clip.webm");
    const response = await fetch("/api/voice/vad-check", { method: "POST", body: form });
    if (!response.ok) return parseErrorOrThrow(response);
    return response.json();
  }

  /**
   * Upload a recorded audio blob for transcription.
   * @param {Blob} audioBlob
   * @returns {Promise<{text: string, detected_language: string, contains_speech: boolean}>}
   */
  async function transcribe(audioBlob) {
    const form = new FormData();
    form.append("file", audioBlob, "clip.webm");
    const response = await fetch("/api/voice/transcribe", { method: "POST", body: form });
    if (!response.ok) return parseErrorOrThrow(response);
    return response.json();
  }

  /**
   * Synthesize speech for `text` and return a playable object URL.
   * @param {string} text
   * @param {{speakingSpeed?: number, voiceName?: string}} [opts]
   * @returns {Promise<{objectUrl: string, sampleRate: string, durationSeconds: string}>}
   */
  async function synthesize(text, opts = {}) {
    const response = await fetch("/api/voice/synthesize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        speaking_speed: opts.speakingSpeed ?? 1.0,
        voice_name: opts.voiceName ?? "Kore",
      }),
    });
    if (!response.ok) return parseErrorOrThrow(response);

    const blob = await response.blob();
    return {
      objectUrl: URL.createObjectURL(blob),
      sampleRate: response.headers.get("X-Sample-Rate"),
      durationSeconds: response.headers.get("X-Duration-Seconds"),
    };
  }

  async function getSettings() {
    const response = await fetch("/api/settings");
    if (!response.ok) return parseErrorOrThrow(response);
    return response.json();
  }

  /**
   * Create a new conversation. Unset fields fall back to app_settings
   * server-side (project spec §42).
   * @param {{topic?: string, difficulty?: string, aiProvider?: string}} [opts]
   */
  async function createConversation(opts = {}) {
    const response = await fetch("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topic: opts.topic || null,
        difficulty: opts.difficulty || null,
        ai_provider: opts.aiProvider || null,
      }),
    });
    if (!response.ok) return parseErrorOrThrow(response);
    return response.json();
  }

  /**
   * Request the end-of-conversation summary (project spec §34, §38). Also
   * ends the conversation server-side if it wasn't already.
   * @param {string} conversationId
   */
  async function analyzeConversation(conversationId) {
    const response = await fetch(`/api/conversations/${conversationId}/analyze`, { method: "POST" });
    if (!response.ok) return parseErrorOrThrow(response);
    return response.json();
  }

  return {
    checkVad,
    transcribe,
    synthesize,
    getSettings,
    createConversation,
    analyzeConversation,
  };
})();
