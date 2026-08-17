/**
 * Wires the DOM (orb, buttons, panels) to VoiceController and the API
 * helpers. This is the Phase 3 test-harness wiring; Phase 4 replaces the
 * transcript box with a full chat thread over WebSocket.
 */
(() => {
  const orb = document.querySelector(".voice-console");
  const bars = Array.from(document.querySelectorAll(".orb-bar"));
  const statusLabel = document.querySelector(".voice-status-label");
  const statusHint = document.querySelector(".voice-status-hint");
  const micButton = document.querySelector(".mic-button");
  const errorBanner = document.querySelector(".error-banner");

  const transcriptBox = document.querySelector(".transcript-box");
  const ttsInput = document.querySelector(".tts-input");
  const ttsSpeed = document.querySelector(".speed-slider");
  const ttsSpeedLabel = document.querySelector(".speed-value");
  const ttsButton = document.querySelector(".tts-submit");

  const STATUS_TEXT = {
    idle: ["Tap to speak", "Press start and speak naturally"],
    listening: ["Listening…", "Speak naturally — I'll notice when you pause"],
    processing: ["Thinking…", "Transcribing what you said"],
    speaking: ["Speaking…", "Playing the response"],
    error: ["Something went wrong", "See the message below"],
  };

  function setStatus(state) {
    orb.dataset.state = state;
    const [label, hint] = STATUS_TEXT[state] || STATUS_TEXT.idle;
    statusLabel.textContent = label;
    statusHint.textContent = hint;
    micButton.dataset.active = String(state === "listening");
    micButton.textContent = state === "listening" ? "◼ Stop" : "◉ Start";
    micButton.disabled = state === "processing" || state === "speaking";
    if (state !== "error") showError(null);
  }

  function showError(message) {
    if (!message) {
      errorBanner.dataset.visible = "false";
      errorBanner.textContent = "";
      return;
    }
    errorBanner.dataset.visible = "true";
    errorBanner.textContent = message;
  }

  function setAmplitude(level) {
    // Map RMS (roughly 0..0.3 in practice) across the bar set with a slight
    // per-bar phase offset so it reads as a waveform, not a single meter.
    const clamped = Math.min(1, level * 4.5);
    bars.forEach((bar, i) => {
      const phase = Math.sin(Date.now() / 120 + i) * 0.15;
      const scale = 0.25 + clamped * 2.2 + Math.max(0, phase * clamped);
      bar.style.transform = `scaleY(${Math.max(0.25, scale).toFixed(2)})`;
    });
  }

  function renderTranscript(result) {
    transcriptBox.innerHTML = "";
    if (!result.contains_speech || !result.text) {
      const empty = document.createElement("p");
      empty.className = "transcript-empty";
      empty.textContent = result.contains_speech
        ? "Heard something, but couldn't make out words. Try again a bit closer to the mic."
        : "No speech detected in that clip.";
      transcriptBox.appendChild(empty);
      return;
    }

    const isTamil = /[\u0B80-\u0BFF]/.test(result.text);
    const text = document.createElement("p");
    if (isTamil) text.classList.add("lang-ta");
    text.textContent = result.text;
    transcriptBox.appendChild(text);

    const meta = document.createElement("div");
    meta.className = "transcript-meta";
    meta.innerHTML = `<span>lang: ${result.detected_language || "unknown"}</span>`;
    transcriptBox.appendChild(meta);
  }

  const controller = new VoiceController({
    onStateChange: setStatus,
    onTranscript: renderTranscript,
    onError: showError,
    onAmplitude: setAmplitude,
  });

  micButton.addEventListener("click", () => {
    if (controller.state === "listening") {
      controller.stop();
    } else {
      controller.start();
    }
  });

  ttsSpeed.addEventListener("input", () => {
    ttsSpeedLabel.textContent = `${parseFloat(ttsSpeed.value).toFixed(2)}x`;
  });

  ttsButton.addEventListener("click", async () => {
    const text = ttsInput.value.trim();
    if (!text) return;

    ttsButton.disabled = true;
    try {
      const { objectUrl } = await Api.synthesize(text, {
        speakingSpeed: parseFloat(ttsSpeed.value),
      });
      await controller.playResponse(objectUrl);
    } catch (err) {
      showError(err.message || "Speech synthesis failed.");
      setStatus("error");
    } finally {
      ttsButton.disabled = false;
    }
  });

  setStatus("idle");
})();

/**
 * Phase 4: the full conversation panel, driven by ConversationController.
 * Deliberately a separate IIFE with its own DOM/state -- it reuses
 * VoiceController's mic/VAD engine (via ConversationController) but never
 * touches the standalone test panel's orb or transcript box above.
 */
(() => {
  const topicSelect = document.querySelector(".topic-select");
  const toggleButton = document.querySelector(".conversation-toggle");
  const statusBox = document.querySelector(".conversation-status");
  const statusLabel = document.querySelector(".conversation-status-label");
  const chatThread = document.querySelector(".chat-thread");
  const scoreReadout = document.querySelector(".score-readout");
  const summaryBox = document.querySelector(".conversation-summary");

  const CONVERSATION_STATUS_TEXT = {
    idle: "Not started",
    listening: "Listening…",
    processing: "Thinking…",
    speaking: "Speaking…",
    error: "Something went wrong",
  };

  let conversation = null;
  let conversationId = null;
  let chatEmptyNotice = document.querySelector(".chat-empty");

  function setConversationStatus(state, customLabel) {
    statusBox.dataset.state = state;
    statusLabel.textContent = customLabel || CONVERSATION_STATUS_TEXT[state] || state;
  }

  function appendChatBubble(speaker, text) {
    if (!text) return null;
    if (chatEmptyNotice) {
      chatEmptyNotice.remove();
      chatEmptyNotice = null;
    }

    const bubble = document.createElement("div");
    bubble.className = `chat-bubble chat-bubble-${speaker}`;

    const meta = document.createElement("span");
    meta.className = "chat-bubble-meta";
    meta.textContent = speaker === "user" ? "You" : "Coach";
    bubble.appendChild(meta);

    const body = document.createElement("p");
    body.style.margin = "0";
    if (/[\u0B80-\u0BFF]/.test(text)) body.classList.add("lang-ta");
    body.textContent = text;
    bubble.appendChild(body);

    chatThread.appendChild(bubble);
    chatThread.scrollTop = chatThread.scrollHeight;
    return bubble;
  }

  /**
   * Corrections/vocabulary render as small annotation cards appended right
   * after the most recent bubble, matching the "✏️ Better" / "📚 New Word"
   * cards in the chat UI mockup (project spec §31).
   */
  function appendAnnotation(kind, title, lines) {
    const card = document.createElement("div");
    card.className = `chat-annotation chat-annotation-${kind}`;

    const heading = document.createElement("span");
    heading.className = "chat-annotation-title";
    heading.textContent = title;
    card.appendChild(heading);

    lines.filter(Boolean).forEach((line) => {
      const p = document.createElement("p");
      p.textContent = line;
      card.appendChild(p);
    });

    chatThread.appendChild(card);
    chatThread.scrollTop = chatThread.scrollHeight;
  }

  function renderCorrection(msg) {
    appendAnnotation("correction", "✏️ Better", [
      `"${msg.corrected}"`,
      msg.explanation,
    ]);
  }

  function renderVocabulary(msg) {
    const lines = [msg.meaning];
    if (msg.translation) lines.push(msg.translation);
    if (msg.example) lines.push(`"${msg.example}"`);
    appendAnnotation("vocabulary", `📚 New Word: ${msg.word}`, lines);
  }

  function updateScores(scores) {
    scoreReadout.dataset.visible = "true";
    for (const key of ["grammar", "fluency", "confidence", "vocabulary"]) {
      const item = scoreReadout.querySelector(`[data-score="${key}"] .score-item-value`);
      if (item) item.textContent = scores[key] != null ? String(scores[key]) : "—";
    }
  }

  function renderSummary(summary) {
    summaryBox.dataset.visible = "true";
    summaryBox.innerHTML = "";

    const heading = document.createElement("h3");
    heading.textContent = `Conversation complete — Overall ${summary.overall_score}/100`;
    summaryBox.appendChild(heading);

    const wentWell = document.createElement("div");
    wentWell.innerHTML = "<strong>What you did well</strong>";
    const wentWellList = document.createElement("ul");
    summary.what_went_well.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      wentWellList.appendChild(li);
    });
    wentWell.appendChild(wentWellList);
    summaryBox.appendChild(wentWell);

    const improve = document.createElement("div");
    improve.innerHTML = "<strong>Improve next time</strong>";
    const improveList = document.createElement("ul");
    summary.improve_next_time.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      improveList.appendChild(li);
    });
    improve.appendChild(improveList);
    summaryBox.appendChild(improve);

    if (summary.new_words_learned > 0) {
      const vocab = document.createElement("p");
      vocab.className = "summary-meta";
      vocab.textContent = `${summary.new_words_learned} new word${summary.new_words_learned === 1 ? "" : "s"} learned this conversation.`;
      summaryBox.appendChild(vocab);
    }

    const pronunciation = document.createElement("p");
    pronunciation.className = "summary-meta summary-meta-muted";
    pronunciation.textContent = summary.pronunciation_note;
    summaryBox.appendChild(pronunciation);
  }

  function resetToIdle(customLabel) {
    toggleButton.dataset.active = "false";
    toggleButton.textContent = "◉ Start Conversation";
    toggleButton.disabled = false;
    topicSelect.disabled = false;
    setConversationStatus("idle", customLabel);
  }

  async function startConversation() {
    toggleButton.disabled = true;
    topicSelect.disabled = true;
    summaryBox.dataset.visible = "false";
    scoreReadout.dataset.visible = "false";

    conversation = new ConversationController({
      onStateChange: setConversationStatus,
      onAmplitude: () => {}, // no dedicated meter in the conversation panel
      onError: (message) => setConversationStatus("error", message),
      onTranscriptMessage: (msg) => appendChatBubble("user", msg.text),
      onAssistantMessage: (msg) => appendChatBubble("assistant", msg.text),
      onCorrection: renderCorrection,
      onVocabulary: renderVocabulary,
      onScoreUpdate: updateScores,
      onEnded: async (reason) => {
        const label = reason === "time_limit" ? "Conversation ended (time limit reached)" : "Conversation ended";
        resetToIdle(label);
        await fetchAndRenderSummary();
      },
    });

    try {
      const created = await conversation.start({ topic: topicSelect.value });
      conversationId = created.id;
      toggleButton.dataset.active = "true";
      toggleButton.textContent = "◼ End Conversation";
      toggleButton.disabled = false;
    } catch (err) {
      setConversationStatus("error", err.message || "Could not start the conversation.");
      resetToIdle();
      conversation = null;
    }
  }

  async function fetchAndRenderSummary() {
    if (!conversationId) return;
    try {
      const summary = await Api.analyzeConversation(conversationId);
      renderSummary(summary);
    } catch (err) {
      // Summary is a nice-to-have on top of an already-completed
      // conversation -- a failure here shouldn't look like the whole
      // conversation failed.
      console.error("Could not load conversation summary:", err.message);
    }
  }

  async function endConversation() {
    if (conversation) conversation.stop();
    conversation = null;
    resetToIdle();
    await fetchAndRenderSummary();
  }

  toggleButton.addEventListener("click", () => {
    if (toggleButton.dataset.active === "true") {
      endConversation();
    } else {
      startConversation();
    }
  });
})();
