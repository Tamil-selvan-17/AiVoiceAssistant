/**
 * VoiceController — mic capture, client-side voice activity detection,
 * and the IDLE -> LISTENING -> PROCESSING -> AI_SPEAKING -> LISTENING loop
 * (project spec §17). This is the Phase 3 pipeline test harness: it proves
 * out capture -> VAD -> transcribe -> synthesize -> playback end to end.
 * The full chat UI (message history, corrections, vocabulary) is wired on
 * top of this in Phase 4 once the WebSocket conversation loop exists.
 *
 * Client-side VAD exists purely for a responsive, natural recording
 * experience (stop soon after the user stops talking, without a network
 * round-trip). The server re-checks with webrtcvad before spending an AI
 * request (see app/services/voice/voice_activity_detector.py) -- the
 * client's job is just to decide *when to stop recording*, not to be the
 * source of truth on whether speech occurred.
 */

const VoiceState = Object.freeze({
  IDLE: "idle",
  LISTENING: "listening",
  PROCESSING: "processing",
  AI_SPEAKING: "speaking",
  ERROR: "error",
});

class VoiceController {
  /**
   * @param {{
   *   onStateChange: (state: string) => void,
   *   onTranscript: (result: {text: string, detected_language: string, contains_speech: boolean}) => void,
   *   onError: (message: string) => void,
   *   onAmplitude: (level: number) => void,
   *   onAudioBlob?: (blob: Blob) => void,
   * }} handlers
   *
   * `onAudioBlob` is optional and is how Phase 4's ConversationController
   * reuses this same mic/VAD engine: when provided, a finished recording is
   * handed to `onAudioBlob` instead of being POSTed to /api/voice/transcribe
   * directly, so the caller can send it over the conversation WebSocket
   * instead. Nothing about mic capture or VAD changes either way.
   */
  constructor(handlers) {
    this.handlers = handlers;
    this.state = VoiceState.IDLE;

    this.mediaStream = null;
    this.mediaRecorder = null;
    this.audioChunks = [];

    this.audioContext = null;
    this.analyser = null;
    this.micSource = null;

    this.vadRafId = null;
    this.silenceStartedAt = null;
    this.speechDetectedInClip = false;

    // Tunable client-side endpointing. Natural pauses shouldn't cut the
    // user off mid-sentence (project spec §19), so silence has to persist
    // for a bit before we stop -- but we still cap total recording length
    // as a safety net against a stuck-open mic.
    this.SILENCE_STOP_MS = 1100;
    this.MAX_RECORDING_MS = 30000;
    this.AMPLITUDE_SPEECH_THRESHOLD = 0.02;

    this._maxRecordingTimer = null;
  }

  _setState(next) {
    this.state = next;
    this.handlers.onStateChange(next);
  }

  async start() {
    if (this.state === VoiceState.LISTENING) return;

    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (err) {
      this.handlers.onError(
        "Microphone access was denied or unavailable. Check your browser's mic permissions."
      );
      this._setState(VoiceState.ERROR);
      return;
    }

    this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 1024;
    this.micSource = this.audioContext.createMediaStreamSource(this.mediaStream);
    this.micSource.connect(this.analyser);

    this.audioChunks = [];
    const mimeType = this._pickSupportedMimeType();
    this.mediaRecorder = new MediaRecorder(this.mediaStream, mimeType ? { mimeType } : undefined);
    this.mediaRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) this.audioChunks.push(event.data);
    };
    this.mediaRecorder.onstop = () => this._handleRecordingStopped(mimeType);
    this.mediaRecorder.start();

    this.silenceStartedAt = null;
    this.speechDetectedInClip = false;
    this._setState(VoiceState.LISTENING);
    this._runVadLoop();

    this._maxRecordingTimer = setTimeout(() => {
      if (this.state === VoiceState.LISTENING) this._stopRecording();
    }, this.MAX_RECORDING_MS);
  }

  stop() {
    if (this.state !== VoiceState.LISTENING) return;
    this._stopRecording();
  }

  _pickSupportedMimeType() {
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/mp4",
    ];
    for (const type of candidates) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported(type)) return type;
    }
    return null;
  }

  _stopRecording() {
    clearTimeout(this._maxRecordingTimer);
    cancelAnimationFrame(this.vadRafId);
    this._setState(VoiceState.PROCESSING);
    if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
      this.mediaRecorder.stop();
    }
    this._teardownAudioGraph();
  }

  _teardownAudioGraph() {
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((track) => track.stop());
      this.mediaStream = null;
    }
    if (this.audioContext) {
      this.audioContext.close().catch(() => {});
      this.audioContext = null;
    }
  }

  async _handleRecordingStopped(mimeType) {
    const blob = new Blob(this.audioChunks, { type: mimeType || "audio/webm" });
    this.audioChunks = [];

    if (blob.size < 500) {
      // Effectively nothing was recorded (e.g. instant stop) -- skip the
      // network round trip entirely.
      if (this.handlers.onAudioBlob) {
        this._setState(VoiceState.IDLE);
        return;
      }
      this.handlers.onTranscript({ text: "", detected_language: "", contains_speech: false });
      this._setState(VoiceState.IDLE);
      return;
    }

    if (this.handlers.onAudioBlob) {
      // Streaming mode (Phase 4 conversation loop): hand the blob off and
      // let the caller drive further state transitions from WebSocket
      // events -- we don't know here whether the server will find speech,
      // reply, or end the conversation.
      this.handlers.onAudioBlob(blob);
      return;
    }

    try {
      const result = await Api.transcribe(blob);
      this.handlers.onTranscript(result);
    } catch (err) {
      this.handlers.onError(err.message || "Transcription failed.");
      this._setState(VoiceState.ERROR);
      return;
    }
    this._setState(VoiceState.IDLE);
  }

  _runVadLoop() {
    const buffer = new Uint8Array(this.analyser.fftSize);

    const tick = () => {
      if (this.state !== VoiceState.LISTENING || !this.analyser) return;

      this.analyser.getByteTimeDomainData(buffer);
      let sumSquares = 0;
      for (let i = 0; i < buffer.length; i++) {
        const normalized = (buffer[i] - 128) / 128;
        sumSquares += normalized * normalized;
      }
      const rms = Math.sqrt(sumSquares / buffer.length);
      this.handlers.onAmplitude(rms);

      const now = performance.now();
      if (rms > this.AMPLITUDE_SPEECH_THRESHOLD) {
        this.speechDetectedInClip = true;
        this.silenceStartedAt = null;
      } else if (this.speechDetectedInClip) {
        // Only start counting silence once we've actually heard speech --
        // otherwise a slow-to-start speaker would get cut off immediately.
        if (this.silenceStartedAt === null) this.silenceStartedAt = now;
        if (now - this.silenceStartedAt > this.SILENCE_STOP_MS) {
          this._stopRecording();
          return;
        }
      }

      this.vadRafId = requestAnimationFrame(tick);
    };

    this.vadRafId = requestAnimationFrame(tick);
  }

  /**
   * Let an external driver (Phase 4's ConversationController) reflect a
   * state that isn't reachable from this class's own recording lifecycle
   * (e.g. "processing" while the server does STT+AI, before any audio
   * comes back).
   * @param {string} state
   */
  setExternalState(state) {
    this._setState(state);
  }

  /**
   * Play a synthesized-speech Blob directly (as received from a WebSocket
   * binary frame), without requiring the caller to manage object URL
   * lifecycle themselves.
   * @param {Blob} blob
   */
  async playAudioBlob(blob) {
    const objectUrl = URL.createObjectURL(blob);
    try {
      await this.playResponse(objectUrl);
    } finally {
      URL.revokeObjectURL(objectUrl);
    }
  }

  /**
   * Play back a synthesized response, driving onAmplitude from the actual
   * playing audio (not a fake animation) so the orb reflects real output.
   * Resolves once playback finishes.
   * @param {string} objectUrl
   */
  async playResponse(objectUrl) {
    this._setState(VoiceState.AI_SPEAKING);

    const audioEl = new Audio(objectUrl);
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const source = ctx.createMediaElementSource(audioEl);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
    analyser.connect(ctx.destination);

    const buffer = new Uint8Array(analyser.fftSize);
    let rafId;
    const tick = () => {
      analyser.getByteTimeDomainData(buffer);
      let sumSquares = 0;
      for (let i = 0; i < buffer.length; i++) {
        const normalized = (buffer[i] - 128) / 128;
        sumSquares += normalized * normalized;
      }
      this.handlers.onAmplitude(Math.sqrt(sumSquares / buffer.length));
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);

    await new Promise((resolve) => {
      audioEl.onended = resolve;
      audioEl.onerror = resolve;
      audioEl.play().catch(resolve);
    });

    cancelAnimationFrame(rafId);
    ctx.close().catch(() => {});
    this.handlers.onAmplitude(0);
    this._setState(VoiceState.IDLE);
  }
}
