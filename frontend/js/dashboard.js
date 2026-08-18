/**
 * Phase 6: learning dashboard rendering -- stats, a small hand-rolled SVG
 * line chart (no charting library, keeping the frontend dependency-free
 * per this project's "keep the frontend lightweight" principle), frequent
 * mistakes, conversation history, and vocabulary review with delete.
 */
const Dashboard = (() => {
  const SERIES = [
    { key: "grammar_score", className: "legend-grammar" },
    { key: "fluency_score", className: "legend-fluency" },
    { key: "confidence_score", className: "legend-confidence" },
    { key: "vocabulary_score", className: "legend-vocabulary" },
  ];

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }

  function formatSpeakingTime(totalSeconds) {
    const minutes = Math.round((totalSeconds || 0) / 60);
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    const rem = minutes % 60;
    return `${hours}h ${rem}m`;
  }

  function renderStats(dashboard) {
    const values = {
      total_conversations: dashboard.total_conversations,
      total_speaking_time: formatSpeakingTime(dashboard.total_speaking_seconds),
      current_streak_days: dashboard.current_streak_days,
      vocabulary_learned_count: dashboard.vocabulary_learned_count,
      avg_fluency: Math.round(dashboard.avg_fluency || 0),
      avg_confidence: Math.round(dashboard.avg_confidence || 0),
      avg_grammar: Math.round(dashboard.avg_grammar || 0),
      avg_vocabulary: Math.round(dashboard.avg_vocabulary || 0),
    };
    for (const [key, value] of Object.entries(values)) {
      const el = document.querySelector(`[data-stat="${key}"]`);
      if (el) el.textContent = String(value);
    }
  }

  function renderMistakes(mistakes) {
    const list = document.querySelector(".mistake-list");
    if (!mistakes || !mistakes.length) {
      list.innerHTML =
        '<li class="list-empty">No patterns yet — they\'ll show up after a few conversations.</li>';
      return;
    }
    list.innerHTML = mistakes
      .map(
        (m) => `
        <li class="mistake-item">
          <span class="mistake-category">${escapeHtml(m.category)} <span class="mistake-count">×${m.count}</span></span>
          <span class="mistake-tip">${escapeHtml(m.tip)}</span>
        </li>`
      )
      .join("");
  }

  function renderHistory(conversations) {
    const list = document.querySelector(".history-list");
    if (!conversations || !conversations.length) {
      list.innerHTML = '<li class="list-empty">No conversations yet.</li>';
      return;
    }
    list.innerHTML = conversations
      .map((c) => {
        const date = new Date(c.started_at).toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
        });
        const scoreText = c.overall_score != null ? `${c.overall_score}/100` : "not analyzed";
        return `
        <li class="history-item">
          <span class="history-topic">${escapeHtml(c.topic)}</span>
          <span class="history-meta">${date} · ${escapeHtml(c.status)} · ${scoreText}</span>
        </li>`;
      })
      .join("");
  }

  function renderVocabulary(words) {
    const list = document.querySelector(".vocabulary-list");
    if (!words || !words.length) {
      list.innerHTML =
        '<li class="list-empty">New words you learn in conversations will appear here.</li>';
      return;
    }

    list.innerHTML = words
      .map((w) => {
        const isTamil = /[\u0B80-\u0BFF]/.test(w.translation || "");
        return `
        <li class="vocabulary-item" data-word-id="${escapeHtml(w.id)}">
          <div class="vocabulary-main">
            <span class="vocabulary-word">${escapeHtml(w.word)}</span>
            <span class="vocabulary-difficulty">${escapeHtml(w.difficulty)}</span>
          </div>
          <p class="vocabulary-meaning">${escapeHtml(w.meaning)}</p>
          ${w.translation ? `<p class="vocabulary-translation${isTamil ? " lang-ta" : ""}">${escapeHtml(w.translation)}</p>` : ""}
          <button type="button" class="vocabulary-delete" data-word-id="${escapeHtml(w.id)}" aria-label="Delete ${escapeHtml(w.word)}">✕</button>
        </li>`;
      })
      .join("");

    list.querySelectorAll(".vocabulary-delete").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await Api.deleteVocabularyWord(btn.dataset.wordId);
          const item = list.querySelector(`.vocabulary-item[data-word-id="${btn.dataset.wordId}"]`);
          if (item) item.remove();
          if (!list.querySelector(".vocabulary-item")) {
            list.innerHTML =
              '<li class="list-empty">New words you learn in conversations will appear here.</li>';
          }
        } catch (err) {
          btn.disabled = false;
          console.error("Could not delete word:", err.message);
        }
      });
    });
  }

  function renderChart(points) {
    const wrap = document.querySelector(".progress-chart-wrap");
    if (!points || !points.length) {
      wrap.innerHTML =
        '<p class="chart-empty">Complete and analyze a conversation to see your progress here.</p>';
      return;
    }

    const width = 640;
    const height = 220;
    const padding = 28;
    const n = points.length;

    const xFor = (i) => (n === 1 ? width / 2 : padding + (i / (n - 1)) * (width - padding * 2));
    const yFor = (score) => height - padding - (score / 100) * (height - padding * 2);

    let svg = `<svg viewBox="0 0 ${width} ${height}" class="progress-chart" role="img" aria-label="Score progress over conversations" preserveAspectRatio="xMidYMid meet">`;

    [0, 50, 100].forEach((tick) => {
      const y = yFor(tick);
      svg += `<line x1="${padding}" y1="${y}" x2="${width - padding}" y2="${y}" class="chart-gridline" />`;
      svg += `<text x="${padding - 6}" y="${y + 4}" class="chart-axis-label" text-anchor="end">${tick}</text>`;
    });

    SERIES.forEach((series) => {
      const path = points
        .map((p, i) => `${i === 0 ? "M" : "L"}${xFor(i).toFixed(1)},${yFor(p[series.key] || 0).toFixed(1)}`)
        .join(" ");
      svg += `<path d="${path}" class="chart-line ${series.className}" fill="none" />`;
      points.forEach((p, i) => {
        svg += `<circle cx="${xFor(i).toFixed(1)}" cy="${yFor(p[series.key] || 0).toFixed(1)}" r="3" class="chart-dot ${series.className}" />`;
      });
    });

    svg += "</svg>";
    wrap.innerHTML = svg;
  }

  async function load() {
    try {
      const [dashboard, progress, vocabulary] = await Promise.all([
        Api.getDashboard(),
        Api.getProgress(),
        Api.getVocabulary(),
      ]);
      renderStats(dashboard);
      renderMistakes(dashboard.frequent_mistakes);
      renderHistory(dashboard.recent_conversations);
      renderChart(progress.points);
      renderVocabulary(vocabulary);
    } catch (err) {
      console.error("Could not load dashboard:", err.message);
    }
  }

  return { load };
})();
