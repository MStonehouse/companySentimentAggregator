const DATA_URL = "data/signals.json";

function storyMatchesCompany(story, company) {
  if (!story || !company) return false;
  if (story.evidence_type === "SEC filing") return story.ticker === company.ticker;
  if (story.display_relevant !== undefined) return Boolean(story.display_relevant);

  const relevance = Number(story.relevance || 0);
  const title = String(story.title || "");
  const summary = String(story.summary || "");
  const ticker = String(company.ticker || "");
  const name = String(company.company_name || "");

  const text = `${title} ${summary}`.toLowerCase();
  const companyWords = name.toLowerCase().match(/[a-z0-9]+/g) || [];
  const suffixes = new Set(["inc","incorporated","corp","corporation","co","company","companies","ltd","limited","plc","llc","group","holdings","holding","sa","ag","nv","lp","the"]);
  while (companyWords.length && suffixes.has(companyWords[companyWords.length - 1])) companyWords.pop();
  const core = companyWords.join(" ");
  const escRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const tickerHit = ticker.length > 1 && new RegExp(`(^|[^A-Z0-9])\\$?${escRe(ticker)}([^A-Z0-9]|$)`, "i").test(`${title} ${summary}`);
  const nameHit = core.length >= 3 && text.includes(core);

  if (relevance >= .68) return true;
  if (relevance >= .38 && (tickerHit || nameHit)) return true;
  return false;
}

const THEME_MATCHERS = {
  "AI infrastructure": ["ai", "artificial intelligence", "data center", "data centre", "gpu", "accelerator", "hyperscale"],
  "Semiconductors": ["semiconductor", "chip", "foundry", "wafer", "fab", "processor", "gpu"],
  "Power & grid": ["power grid", "grid", "electricity", "transmission", "substation", "utility", "power demand"],
  "Nuclear & uranium": ["nuclear", "uranium", "reactor", "small modular reactor", "smr"],
  "Cybersecurity": ["cybersecurity", "cyber security", "ransomware", "breach", "zero trust"],
  "Robotics & automation": ["robotics", "robot", "automation", "autonomous", "industrial automation"],
  "Defense & aerospace": ["defense", "defence", "aerospace", "missile", "drone", "military", "satellite"],
  "Biotech & therapeutics": ["biotech", "therapeutic", "clinical trial", "drug", "fda", "phase 1", "phase 2", "phase 3"],
  "Critical minerals": ["critical mineral", "lithium", "rare earth", "copper", "nickel", "graphite", "mining"],
  "Quantum computing": ["quantum computing", "quantum computer", "qubit"],
  "Cloud & software": ["cloud", "saas", "software platform", "enterprise software"],
  "Financial technology": ["fintech", "payments", "digital banking", "payment network"]
};

function storyMatchesTheme(story, theme) {
  const hay = `${story?.title || ""} ${story?.summary || ""}`.toLowerCase();
  const terms = THEME_MATCHERS[theme] || [String(theme || "").toLowerCase()];
  const matches = terms.filter(term => term && hay.includes(term.toLowerCase()));
  if (!matches.length) return false;

  const title = String(story?.title || "").toLowerCase();
  const titleMatches = terms.filter(term => term && title.includes(term.toLowerCase()));

  return matches.length >= 2 || titleMatches.length >= 1;
}
const state = { companies: [], meta: {}, rankings: {}, briefing: {}, sectors: [], themes: [], general_news: [] };
const $ = id => document.getElementById(id);

function esc(v="") { return String(v).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"})[c]); }
function fmtDate(v) { if(!v) return "—"; const d=new Date(v); return Number.isNaN(d.valueOf())?v:d.toLocaleString([], {dateStyle:"medium", timeStyle:"short"}); }
function fmtNum(v, digits=1) { return (v===null||v===undefined||Number.isNaN(Number(v)))?"—":Number(v).toLocaleString([], {maximumFractionDigits:digits}); }
function fmtMoney(v) { if(!v) return "—"; const n=Number(v); if(n>=1e12) return `$${(n/1e12).toFixed(2)}T`; if(n>=1e9) return `$${(n/1e9).toFixed(2)}B`; if(n>=1e6) return `$${(n/1e6).toFixed(1)}M`; return `$${n.toLocaleString()}`; }
function pct(v) { return (v===null||v===undefined)?"—":`${Number(v).toFixed(1)}%`; }
function sentimentClass(s="") { s=s.toLowerCase(); return s.includes("positive")?"positive":s.includes("negative")?"negative":"neutral"; }
function companyByTicker(t) { return state.companies.find(c=>c.ticker===t); }
function infoBubble(text) { return `<button class="info-button" type="button" aria-label="More information">i<span class="info-tooltip">${esc(text)}</span></button>`; }
function renderMethodology() {
  $("signalMethod").innerHTML = scoreDefs.signal.map(([n,name,desc])=>`<div class="method-item"><strong>${n}</strong><span>${esc(name)} ${infoBubble(desc)}</span></div>`).join("");
  $("discoveryMethod").innerHTML = scoreDefs.discovery.map(([n,name,desc])=>`<div class="method-item"><strong>${n}</strong><span>${esc(name)} ${infoBubble(desc)}</span></div>`).join("");
}

function scoreRing(score, type="signal") { return `<div><div class="score-ring ${type==='discovery'?'discovery-ring':''}">${Math.round(score||0)}</div><div class="score-label">${type==='discovery'?'DISCOVERY':'SIGNAL'}</div></div>`; }
function deltaBadge(delta, label="") { if(delta===null||delta===undefined) return ""; const cls=delta>0?"positive":delta<0?"negative":"neutral"; return `<span class="badge ${cls}">${label}${delta>0?'+':''}${fmtNum(delta,1)}</span>`; }
function companyCard(c, type="signal") {
  const discovery=type==="discovery";
  const attention=type==="attention";
  const score=discovery
    ? c.discovery_score
    : attention
      ? (c.market_attention_score ?? c.signal_score)
      : c.signal_score;
  const ratio=c.discovery_metrics?.coverage_ratio_vs_baseline;
  return `<article class="company-card ${discovery?'emerging-card':''}" data-ticker="${esc(c.ticker)}" tabindex="0">
    <div class="card-top"><div><div class="ticker-line"><span class="ticker">${esc(c.ticker)}</span></div>${c.company_name?`<div class="company-name">${esc(c.company_name)}</div>`:""}</div>${scoreRing(score, discovery?'discovery':'signal')}</div>
    <div class="catalyst-type">${esc(c.catalyst_category||"Company development")}</div>
    <div class="catalyst">${esc(c.primary_catalyst||"Credible company development")}</div>
    <div class="meta-row">
      ${c.new_to_radar?`<span class="badge new">NEW TO RADAR</span>`:""}
      <span class="badge">${esc(c.attention_status||"Normal")}</span>
      <span class="badge ${sentimentClass(c.sentiment_label)}">${esc(c.sentiment_label||"Mixed")}</span>
      <span class="badge confidence">Confidence ${Math.round(c.confidence_score||0)}</span>
      ${c.evidence?.primary_source_count?`<span class="badge primary">Primary filing</span>`:""}
      ${discovery&&ratio!==undefined?`<span class="badge discovery-badge">${c.baseline?.avg_items_24h>0?`${fmtNum(ratio,1)}× baseline`:"New baseline"}</span>`:""}
    </div>
    <div class="card-footer"><span>${c.article_count_24h||0} items / 24h</span><span>${c.days_on_radar||1} day${c.days_on_radar===1?'':'s'} on radar</span>${discovery ? deltaBadge(c.change?.discovery_delta,"Δ ") : ""}</div>
  </article>`;
}

function getFiltered(kind) {
  const key=kind==="discovery" ? "emerging_signals" : "market_leaders";
  const list=(state.rankings[key]||[])
    .slice(0,12)
    .map(companyByTicker)
    .filter(Boolean);

  const q=$("searchInput").value.trim().toLowerCase();
  const min=Number($("minScore").value);
  const sector=$("sectorFilter").value;
  const cat=$("catalystFilter").value;

  return list.filter(c=>{
    const score=kind==="discovery"
      ? (c.discovery_score||0)
      : (c.market_attention_score ?? c.signal_score ?? 0);
    const hay=`${c.ticker} ${c.company_name||""}`.toLowerCase();
    return score>=min &&
      hay.includes(q) &&
      (!sector||(c.fundamentals?.industry||"")===sector) &&
      (!cat||c.catalyst_category===cat);
  });
}

function attachCards() {
  document.querySelectorAll(".company-card").forEach(card => {
    card.addEventListener("click", () => openCompany(card.dataset.ticker));
    card.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openCompany(card.dataset.ticker);
      }
    });
  });
}

function renderGeneralNews() {
  const host = $("generalNewsGrid");
  if (!host) return;
  const rows = (state.general_news || []).slice(0, 8);
  if (!rows.length) {
    host.innerHTML = `<div class="empty-state">No general market news is available from the current update.</div>`;
    return;
  }
  host.innerHTML = rows.map(s => `
    <article class="general-news-card">
      <div class="story-meta">
        <span>${esc(s.source || "Unknown source")}</span>
        <span>${fmtDate(s.published_at)}</span>
      </div>
      <h3>${esc(s.title || "")}</h3>
      <p>${esc(s.summary || "")}</p>
      ${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">Open source ↗</a>` : ""}
    </article>
  `).join("");
}

async function init() {
  renderMethodology();
  try {
    const r=await fetch(`${DATA_URL}?v=${Date.now()}`,{cache:"no-store"}); if(!r.ok) throw new Error(`HTTP ${r.status}`);
    const data=await r.json(); state.companies=data.companies||[]; state.meta=data.meta||{}; state.rankings=data.rankings||{}; state.briefing=data.briefing||{}; state.sectors=data.sectors||[]; state.themes=data.themes||[]; state.general_news=data.general_news||[];
    $("lastUpdated").textContent=fmtDate(state.meta.generated_at); $("companiesScanned").textContent=state.meta.companies_scanned??"—"; $("signalsFound").textContent=state.companies.length; $("highConfidence").textContent=state.companies.filter(c=>(c.confidence_score||0)>=75).length; $("primaryEvents").textContent=state.companies.filter(c=>(c.evidence?.primary_source_count||0)>0).length;
    const days=state.meta.baseline_days||0; $("baselineNote").textContent=days>=7?`Emerging baseline: ${days} days of stored history.`:`Emerging baseline is building (${days} prior day${days===1?'':'s'}). Discovery rankings become more reliable as history accumulates.`;
    populateFilters(); renderBriefing(); renderLandscape(); renderGeneralNews(); renderAll();
  } catch(err) { console.error(err); $("lastUpdated").textContent="Data unavailable"; $("leaderGrid").innerHTML=`<div class="empty-state">Could not load ${DATA_URL}. Run the updater once.</div>`; }
}

["searchInput","minScore","sectorFilter","catalystFilter"].forEach(id=>$(id).addEventListener("input",renderRankings));
$("closeDialog").addEventListener("click",()=>$("companyDialog").close());
$("companyDialog").addEventListener("click",e=>{if(e.target===$("companyDialog")) $("companyDialog").close();});
init();
