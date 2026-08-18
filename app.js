const DATA_URL = "data/signals.json";

const state = { companies: [], meta: {}, rankings: {} };
const $ = (id) => document.getElementById(id);

function escapeHtml(value = "") {
  return String(value).replace(/[&<>"']/g, ch => ({
    "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;"
  })[ch]);
}

function formatDate(value) {
  if (!value) return "Unknown";
  const d = new Date(value);
  if (Number.isNaN(d.valueOf())) return value;
  return d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function sentimentClass(label = "") {
  label = label.toLowerCase();
  if (label.includes("bull") || label.includes("positive")) return "positive";
  if (label.includes("bear") || label.includes("negative")) return "negative";
  return "neutral";
}

function companyByTicker(ticker) {
  return state.companies.find(c => c.ticker === ticker);
}

function rankedCompanies(kind) {
  const key = kind === "emerging" ? "emerging_signals" : "market_leaders";
  const tickers = state.rankings?.[key];
  if (Array.isArray(tickers) && tickers.length) {
    return tickers.map(companyByTicker).filter(Boolean);
  }
  return [...state.companies].sort((a,b) => kind === "emerging"
    ? (b.discovery_score || 0) - (a.discovery_score || 0)
    : (b.signal_score || 0) - (a.signal_score || 0));
}

function scoreBlock(c, kind) {
  const emerging = kind === "emerging";
  const score = emerging ? (c.discovery_score ?? c.signal_score ?? 0) : (c.signal_score || 0);
  const label = emerging ? "DISCOVERY" : "SIGNAL";
  return `<div>
    <div class="score-ring ${emerging ? "discovery-ring" : ""}">${Math.round(score)}</div>
    <div class="score-label">${label}</div>
  </div>`;
}

function cardHtml(c, kind) {
  const primary = c.evidence?.primary_source_count > 0;
  const ratio = c.discovery_metrics?.coverage_ratio_vs_baseline ?? c.metrics?.coverage_ratio_vs_baseline ?? 0;
  const baseline = c.baseline?.avg_items_24h ?? 0;
  const baselineBuilding = c.baseline?.maturity === "building";
  const emerging = kind === "emerging";

  return `
    <article class="company-card ${emerging ? "emerging-card" : ""}" tabindex="0" data-ticker="${escapeHtml(c.ticker)}">
      <div class="card-top">
        <div>
          <div class="ticker">${escapeHtml(c.ticker)}</div>
          ${c.company_name ? `<div class="company-name">${escapeHtml(c.company_name)}</div>` : ""}
        </div>
        ${scoreBlock(c, kind)}
      </div>
      <div class="catalyst">${escapeHtml(c.primary_catalyst || "Unusual increase in credible coverage")}</div>
      <div class="meta-row">
        ${primary ? `<span class="badge primary">Primary filing</span>` : ""}
        <span class="badge ${sentimentClass(c.sentiment_label)}">${escapeHtml(c.sentiment_label || "Mixed")}</span>
        <span class="badge">${escapeHtml(c.attention_status || c.coverage_acceleration_label || "Normal")}</span>
        <span class="badge">${c.evidence?.independent_sources || 0} independent sources</span>
        ${emerging ? `<span class="badge discovery-badge">${baseline > 0 ? `${ratio.toFixed(1)}× baseline` : "New to baseline"}</span>` : ""}
      </div>
      <div class="card-footer">
        <span>${c.article_count_24h || 0} items / 24h</span>
        <span>${emerging && baselineBuilding ? "Baseline building" : formatDate(c.latest_event_at)}</span>
      </div>
    </article>`;
}

function filterForView(rows, kind) {
  const query = $("searchInput").value.trim().toLowerCase();
  const minScore = Number($("minScore").value);
  const scoreKey = kind === "emerging" ? "discovery_score" : "signal_score";

  return rows.filter(c => {
    const haystack = `${c.ticker} ${c.company_name || ""}`.toLowerCase();
    return (c[scoreKey] || 0) >= minScore && haystack.includes(query);
  });
}

function attachCardHandlers() {
  document.querySelectorAll(".company-card").forEach(card => {
    const open = () => openCompany(card.dataset.ticker);
    card.addEventListener("click", open);
    card.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
    });
  });
}

function render() {
  const leaders = filterForView(rankedCompanies("leaders"), "leaders");
  const emerging = filterForView(rankedCompanies("emerging"), "emerging");

  $("leaderGrid").innerHTML = leaders.map(c => cardHtml(c, "leaders")).join("");
  $("emergingGrid").innerHTML = emerging.map(c => cardHtml(c, "emerging")).join("");
  $("leaderEmpty").hidden = leaders.length !== 0;
  $("emergingEmpty").hidden = emerging.length !== 0;
  $("leaderCount").textContent = `${leaders.length} shown`;
  $("emergingCount").textContent = `${emerging.length} shown`;

  attachCardHandlers();
}

function openCompany(ticker) {
  const c = companyByTicker(ticker);
  if (!c) return;

  const m = c.metrics || {};
  const d = c.discovery_metrics || {};
  const stories = (c.stories || []).map(s => `
    <article class="story">
      <div class="story-meta">
        <span>${escapeHtml(s.source || "Unknown source")}</span>
        <span>${formatDate(s.published_at)}</span>
        <span>${escapeHtml(s.evidence_type || "Reporting")}</span>
      </div>
      <h4>${escapeHtml(s.title)}</h4>
      <p>${escapeHtml(s.summary || "")}</p>
      ${s.url ? `<a href="${escapeHtml(s.url)}" target="_blank" rel="noopener noreferrer">Open original source ↗</a>` : ""}
    </article>`).join("");

  $("dialogContent").innerHTML = `
    <div class="detail-header">
      <p class="eyebrow">${escapeHtml(c.ticker)}${c.company_name ? ` · ${escapeHtml(c.company_name)}` : ""}</p>
      <h2>${escapeHtml(c.primary_catalyst || "Credible information acceleration")}</h2>
      <p>${escapeHtml(c.why_it_matters || "Several credible sources are reporting company-specific developments.")}</p>
      <div class="dual-score">
        <div><span>Signal Score</span><strong>${Math.round(c.signal_score || 0)}</strong><small>Absolute market attention</small></div>
        <div><span>Discovery Score</span><strong>${Math.round(c.discovery_score ?? c.signal_score ?? 0)}</strong><small>Attention vs. company baseline</small></div>
      </div>
      <p class="status-line">Attention status: <strong>${escapeHtml(c.attention_status || "Normal")}</strong>${c.baseline?.maturity === "building" ? " · discovery baseline still building" : ""}</p>
    </div>

    <p class="eyebrow">SIGNAL SCORE BREAKDOWN</p>
    <div class="breakdown">
      <div><span>Primary evidence</span><strong>${Math.round(m.primary_evidence || 0)} / 25</strong></div>
      <div><span>Coverage acceleration</span><strong>${Math.round(m.coverage_acceleration || 0)} / 20</strong></div>
      <div><span>Catalyst strength</span><strong>${Math.round(m.catalyst_strength || 0)} / 20</strong></div>
      <div><span>Corroboration</span><strong>${Math.round(m.corroboration || 0)} / 15</strong></div>
      <div><span>Source quality</span><strong>${Math.round(m.source_quality || 0)} / 10</strong></div>
      <div><span>Sentiment signal</span><strong>${Math.round(m.sentiment_signal || 0)} / 10</strong></div>
    </div>

    <p class="eyebrow">DISCOVERY SCORE BREAKDOWN</p>
    <div class="breakdown discovery-breakdown">
      <div><span>Attention lift</span><strong>${Math.round(d.attention_lift || 0)} / 35</strong></div>
      <div><span>Novelty</span><strong>${Math.round(d.novelty || 0)} / 20</strong></div>
      <div><span>Source breadth</span><strong>${Math.round(d.source_breadth || 0)} / 15</strong></div>
      <div><span>Catalyst strength</span><strong>${Math.round(d.catalyst_strength || 0)} / 15</strong></div>
      <div><span>Primary evidence</span><strong>${Math.round(d.primary_evidence || 0)} / 10</strong></div>
      <div><span>Sentiment</span><strong>${Math.round(d.sentiment || 0)} / 5</strong></div>
    </div>

    <p class="eyebrow">IMPORTANT COVERAGE</p>
    ${stories || "<p>No detailed stories are currently stored.</p>"}
  `;
  $("companyDialog").showModal();
}

async function init() {
  try {
    const response = await fetch(`${DATA_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    state.companies = data.companies || [];
    state.meta = data.meta || {};
    state.rankings = data.rankings || {};

    $("lastUpdated").textContent = formatDate(state.meta.generated_at);
    $("companiesScanned").textContent = state.meta.companies_scanned ?? "—";
    $("signalsFound").textContent = state.companies.length;
    $("highConfidence").textContent = state.companies.filter(c => (c.signal_score || 0) >= 75).length;
    $("primaryEvents").textContent = state.companies.filter(c => (c.evidence?.primary_source_count || 0) > 0).length;

    const days = state.meta.baseline_days ?? 0;
    $("baselineNote").textContent = days >= 7
      ? `Emerging baseline: ${days} days of history.`
      : `Emerging baseline is building (${days} prior day${days === 1 ? "" : "s"}); Discovery Scores are provisional until at least 7 days.`;

    render();
  } catch (err) {
    console.error(err);
    $("lastUpdated").textContent = "Data unavailable";
    $("leaderGrid").innerHTML = `<div class="empty-state">Could not load ${DATA_URL}. Run the updater or use the included sample data.</div>`;
    $("emergingGrid").innerHTML = "";
  }
}

["searchInput","minScore"].forEach(id => $(id).addEventListener("input", render));
$("closeDialog").addEventListener("click", () => $("companyDialog").close());
$("companyDialog").addEventListener("click", e => {
  if (e.target === $("companyDialog")) $("companyDialog").close();
});

init();
