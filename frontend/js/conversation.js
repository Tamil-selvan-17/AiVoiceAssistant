/**
 * Wires VoiceController's mic-capture/VAD engine (Phase 3) to the
 * continuous conversation WebSocket loop (Phase 4, project spec §16-17,
 * §32). Recorded utterances go out as binary frames; incoming JSON events
 * drive the chat transcript; incoming binary frames are the AI's spoken
 * reply, played back through the same VoiceController.
 *
 * Sequencing note: the server sends "audio_incoming" + a binary frame +
 * a "listening" status essentially back-to-back, without waiting for
 * playback to finish. If we restarted the mic on every "listening" event
 * as-is, it would start recording while the AI's reply is still playing.
 * So `awaitingAudio` gates that: a "listening" status while audio is still
 * expected is ignored, and the mic instead resumes right after
 * `playAudioBlob` actually finishes.
 */
class ConversationController {
  /**
   * @param {{
   *   onStateChange: (state: string) => void,
   *   onAmplitude: (level: number) => void,
   *   onError: (message: string) => void,
   *   onTranscriptMessage: (msg: {text: string, language: string}) => void,
   *   onAssistantMessage: (msg: {text: string}) => void,
   *   onCorrection: (msg: {original: string, corrected: string, explanation: string}) => void,
   *   onVocabulary: (msg: {word: string, meaning: string, translation: string, example: string, difficulty: string}) => void,
   *   onScoreUpdate: (msg: {grammar: number, fluency: number, confidence: number, vocabulary: number, pronunciation: number|null, pronunciation_note: string}) => void,
   *   onEnded: (reason: string) => void,
   * }} handlers
   */
  constructor(handlers) {
    this.handlers = handlers;
    this.ws = null;
    this.conversationId = null;
    this.awaitingAudio = false;
    this.connected = false;

    this.voice = new VoiceController({
      onStateChange: handlers.onStateChange,
      onAmplitude: handlers.onAmplitude,
      onError: handlers.onError,
      onTranscript: () => {}, // unused: transcript arrives via WS JSON, not the REST result
      onAudioBlob: (blob) => this._sendAudio(blob),
    });
  }

  /**
   * Create a conversation, open its WebSocket, and start listening once the
   * AI's opening turn has played.
   * @param {{topic?: string, difficulty?: string, aiProvider?: string}} [opts]
   */
  async start(opts = {}) {
    const conversation = await Api.createConversation(opts);
    this.conversationId = conversation.id;

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    this.ws = new WebSocket(`${protocol}://${window.location.host}/ws/conversation/${conversation.id}`);
    this.ws.binaryType = "arraybuffer";

    this.ws.onmessage = (event) => this._handleMessage(event);
    this.ws.onerror = () => this.handlers.onError("Connection error. Please try again.");
    this.ws.onclose = () => {
      this.connected = false;
    };

    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("Connection timed out.")), 8000);
      this.ws.onopen = () => {
        clearTimeout(timeout);
        this.connected = true;
        resolve();
      };
    });

    return conversation;
  }

  stop() {
    this.voice.stop();
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.connected = false;
  }

  _sendAudio(blob) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    blob.arrayBuffer().then((buffer) => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(buffer);
    });
  }

  _handleMessage(event) {
    if (typeof event.data === "string") {
      this._handleJson(JSON.parse(event.data));
    } else {
      this._handleAudioFrame(event.data);
    }
  }

  _handleJson(msg) {
    switch (msg.type) {
      case "status":
        this._handleStatus(msg.status, msg.reason);
        break;
      case "transcript":
        this.handlers.onTranscriptMessage({ text: msg.text, language: msg.language });
        break;
      case "assistant":
        this.handlers.onAssistantMessage({ text: msg.text });
        break;
      case "correction":
        if (this.handlers.onCorrection) {
          this.handlers.onCorrection({
            original: msg.original,
            corrected: msg.corrected,
            explanation: msg.explanation,
          });
        }
        break;
      case "vocabulary":
        if (this.handlers.onVocabulary) {
          this.handlers.onVocabulary({
            word: msg.word,
            meaning: msg.meaning,
            translation: msg.translation,
            example: msg.example,
            difficulty: msg.difficulty,
          });
        }
        break;
      case "score_update":
        if (this.handlers.onScoreUpdate) {
          this.handlers.onScoreUpdate({
            grammar: msg.grammar,
            fluency: msg.fluency,
            confidence: msg.confidence,
            vocabulary: msg.vocabulary,
            pronunciation: msg.pronunciation,
            pronunciation_note: msg.pronunciation_note,
          });
        }
        break;
      case "audio_incoming":
        this.awaitingAudio = true;
        break;
      case "error":
        this.handlers.onError(msg.message);
        break;
      default:
        break;
    }
  }

  _handleStatus(status, reason) {
    if (status === "processing") {
      this.voice.setExternalState("processing");
    } else if (status === "listening") {
      if (!this.awaitingAudio) this._resumeListening();
      // else: _handleAudioFrame resumes listening once playback finishes.
    } else if (status === "ended") {
      this.handlers.onEnded(reason || "unknown");
      this.stop();
    }
  }

  async _handleAudioFrame(arrayBuffer) {
    this.awaitingAudio = false;
    const blob = new Blob([arrayBuffer], { type: "audio/wav" });
    await this.voice.playAudioBlob(blob);
    this._resumeListening();
  }

  _resumeListening() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.voice.start();
    }
  }
}
