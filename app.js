const DATA_URL = "data/signals.json";

const state = { companies: [], meta: {} };
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

function cardHtml(c) {
  const primary = c.evidence?.primary_source_count > 0;
  return `
    <article class="company-card" tabindex="0" data-ticker="${escapeHtml(c.ticker)}">
      <div class="card-top">
        <div>
          <div class="ticker">${escapeHtml(c.ticker)}</div>
          <div class="company-name">${escapeHtml(c.company_name || "Unknown company")}</div>
        </div>
        <div>
          <div class="score-ring">${Math.round(c.signal_score || 0)}</div>
          <div class="score-label">SIGNAL</div>
        </div>
      </div>
      <div class="catalyst">${escapeHtml(c.primary_catalyst || "Unusual increase in credible coverage")}</div>
      <div class="meta-row">
        ${primary ? `<span class="badge primary">Primary filing</span>` : ""}
        <span class="badge ${sentimentClass(c.sentiment_label)}">${escapeHtml(c.sentiment_label || "Mixed")}</span>
        <span class="badge">${escapeHtml(c.coverage_acceleration_label || "Baseline")}</span>
        <span class="badge">${c.evidence?.independent_sources || 0} independent sources</span>
      </div>
      <div class="card-footer">
        <span>${c.article_count_24h || 0} items / 24h</span>
        <span>${formatDate(c.latest_event_at)}</span>
      </div>
    </article>`;
}

function render() {
  const query = $("searchInput").value.trim().toLowerCase();
  const minScore = Number($("minScore").value);
  const sortBy = $("sortBy").value;

  let rows = state.companies.filter(c => {
    const haystack = `${c.ticker} ${c.company_name}`.toLowerCase();
    return (c.signal_score || 0) >= minScore && haystack.includes(query);
  });

  rows.sort((a,b) => {
    if (sortBy === "acceleration") return (b.metrics?.coverage_acceleration || 0) - (a.metrics?.coverage_acceleration || 0);
    if (sortBy === "evidence") return (b.metrics?.evidence_quality || 0) - (a.metrics?.evidence_quality || 0);
    if (sortBy === "recent") return new Date(b.latest_event_at || 0) - new Date(a.latest_event_at || 0);
    return (b.signal_score || 0) - (a.signal_score || 0);
  });

  $("companyGrid").innerHTML = rows.map(cardHtml).join("");
  $("emptyState").hidden = rows.length !== 0;
  $("resultCount").textContent = `${rows.length} shown`;

  document.querySelectorAll(".company-card").forEach(card => {
    const open = () => openCompany(card.dataset.ticker);
    card.addEventListener("click", open);
    card.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
    });
  });
}

function openCompany(ticker) {
  const c = state.companies.find(x => x.ticker === ticker);
  if (!c) return;

  const m = c.metrics || {};
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
      <p class="eyebrow">${escapeHtml(c.ticker)} · ${escapeHtml(c.company_name || "")}</p>
      <h2>${escapeHtml(c.primary_catalyst || "Credible information acceleration")}</h2>
      <p>${escapeHtml(c.why_it_matters || "Several credible sources are reporting company-specific developments.")}</p>
      <div class="detail-score">${Math.round(c.signal_score || 0)} / 100</div>
    </div>

    <div class="breakdown">
      <div><span>Primary evidence</span><strong>${Math.round(m.primary_evidence || 0)} / 25</strong></div>
      <div><span>Coverage acceleration</span><strong>${Math.round(m.coverage_acceleration || 0)} / 20</strong></div>
      <div><span>Catalyst strength</span><strong>${Math.round(m.catalyst_strength || 0)} / 20</strong></div>
      <div><span>Corroboration</span><strong>${Math.round(m.corroboration || 0)} / 15</strong></div>
      <div><span>Source quality</span><strong>${Math.round(m.source_quality || 0)} / 10</strong></div>
      <div><span>Sentiment signal</span><strong>${Math.round(m.sentiment_signal || 0)} / 10</strong></div>
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

    $("lastUpdated").textContent = formatDate(state.meta.generated_at);
    $("companiesScanned").textContent = state.meta.companies_scanned ?? "—";
    $("signalsFound").textContent = state.companies.length;
    $("highConfidence").textContent = state.companies.filter(c => (c.signal_score || 0) >= 75).length;
    $("primaryEvents").textContent = state.companies.filter(c => (c.evidence?.primary_source_count || 0) > 0).length;

    render();
  } catch (err) {
    console.error(err);
    $("lastUpdated").textContent = "Data unavailable";
    $("companyGrid").innerHTML = `<div class="empty-state">Could not load ${DATA_URL}. Run the updater or use the included sample data.</div>`;
  }
}

["searchInput","minScore","sortBy"].forEach(id => $(id).addEventListener("input", render));
$("closeDialog").addEventListener("click", () => $("companyDialog").close());
$("companyDialog").addEventListener("click", e => {
  if (e.target === $("companyDialog")) $("companyDialog").close();
});

init();
