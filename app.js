const DATA_URL = "data/signals.json";
const WATCH_KEY = "companySignal.watchlist.v1";
const state = { companies: [], meta: {}, rankings: {}, briefing: {}, sectors: [], themes: [], watchlist: new Set() };
const $ = id => document.getElementById(id);

function esc(v="") { return String(v).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"})[c]); }
function fmtDate(v) { if(!v) return "—"; const d=new Date(v); return Number.isNaN(d.valueOf())?v:d.toLocaleString([], {dateStyle:"medium", timeStyle:"short"}); }
function fmtNum(v, digits=1) { return (v===null||v===undefined||Number.isNaN(Number(v)))?"—":Number(v).toLocaleString([], {maximumFractionDigits:digits}); }
function fmtMoney(v) { if(!v) return "—"; const n=Number(v); if(n>=1e12) return `$${(n/1e12).toFixed(2)}T`; if(n>=1e9) return `$${(n/1e9).toFixed(2)}B`; if(n>=1e6) return `$${(n/1e6).toFixed(1)}M`; return `$${n.toLocaleString()}`; }
function pct(v) { return (v===null||v===undefined)?"—":`${Number(v).toFixed(1)}%`; }
function sentimentClass(s="") { s=s.toLowerCase(); return s.includes("positive")?"positive":s.includes("negative")?"negative":"neutral"; }
function companyByTicker(t) { return state.companies.find(c=>c.ticker===t); }
function loadWatch() { try { state.watchlist=new Set(JSON.parse(localStorage.getItem(WATCH_KEY)||"[]")); } catch { state.watchlist=new Set(); } }
function saveWatch() { localStorage.setItem(WATCH_KEY, JSON.stringify([...state.watchlist])); }
function toggleWatch(ticker) { state.watchlist.has(ticker)?state.watchlist.delete(ticker):state.watchlist.add(ticker); saveWatch(); renderAll(); }

const scoreDefs = {
  signal: [
    [25,"Primary evidence","SEC or regulatory filing supports the signal. Primary-source evidence receives the highest confidence weighting."],
    [20,"Coverage acceleration","Current credible coverage compared with the company’s recent baseline."],
    [20,"Catalyst strength","Estimated significance of the underlying event: contracts, M&A, approvals, earnings, financing and similar developments."],
    [15,"Corroboration","Independent credible sources supporting the development. Duplicated/syndicated stories are clustered."],
    [10,"Source quality","Weight assigned to established financial journalism, primary filings and specialist reporting."],
    [10,"Sentiment signal","Strength of directional tone in coverage. This is descriptive, not a buy/sell recommendation."],
  ],
  discovery: [
    [35,"Attention lift","How far current coverage is above the company’s own normal level."],
    [20,"Novelty","Rewards companies that normally have a quiet information footprint."],
    [15,"Source breadth","Number of independent credible sources covering the company."],
    [15,"Catalyst strength","How consequential the underlying development appears."],
    [10,"Primary evidence","Whether SEC/regulatory evidence supports the story."],
    [5,"Sentiment","Strength of positive or negative directional tone."],
  ]
};

function infoBubble(text) { return `<button class="info-button" type="button" aria-label="More information">i<span class="info-tooltip">${esc(text)}</span></button>`; }
function renderMethodology() {
  $("signalMethod").innerHTML = scoreDefs.signal.map(([n,name,desc])=>`<div class="method-item"><strong>${n}</strong><span>${esc(name)} ${infoBubble(desc)}</span></div>`).join("");
  $("discoveryMethod").innerHTML = scoreDefs.discovery.map(([n,name,desc])=>`<div class="method-item"><strong>${n}</strong><span>${esc(name)} ${infoBubble(desc)}</span></div>`).join("");
}

function scoreRing(score, type="signal") { return `<div><div class="score-ring ${type==='discovery'?'discovery-ring':''}">${Math.round(score||0)}</div><div class="score-label">${type==='discovery'?'DISCOVERY':'SIGNAL'}</div></div>`; }
function deltaBadge(delta, label="") { if(delta===null||delta===undefined) return ""; const cls=delta>0?"positive":delta<0?"negative":"neutral"; return `<span class="badge ${cls}">${label}${delta>0?'+':''}${fmtNum(delta,1)}</span>`; }
function companyCard(c, type="signal") {
  const discovery=type==="discovery";
  const score=discovery?c.discovery_score:c.signal_score;
  const ratio=c.discovery_metrics?.coverage_ratio_vs_baseline;
  const watched=state.watchlist.has(c.ticker);
  return `<article class="company-card ${discovery?'emerging-card':''}" data-ticker="${esc(c.ticker)}" tabindex="0">
    <div class="card-top"><div><div class="ticker-line"><span class="ticker">${esc(c.ticker)}</span><button class="watch-button ${watched?'active':''}" data-watch="${esc(c.ticker)}" aria-label="${watched?'Remove from':'Add to'} watchlist">★</button></div>${c.company_name?`<div class="company-name">${esc(c.company_name)}</div>`:""}</div>${scoreRing(score, discovery?'discovery':'signal')}</div>
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
    <div class="card-footer"><span>${c.article_count_24h||0} items / 24h</span><span>${c.days_on_radar||1} day${c.days_on_radar===1?'':'s'} on radar</span>${deltaBadge(discovery?c.change?.discovery_delta:c.change?.signal_delta,"Δ ")}</div>
  </article>`;
}

function getFiltered(kind) {
  const key=kind==='discovery'?'emerging_signals':'market_leaders';
  const list=(state.rankings[key]||[]).map(companyByTicker).filter(Boolean);
  const q=$("searchInput").value.trim().toLowerCase(); const min=Number($("minScore").value);
  const sector=$("sectorFilter").value; const cat=$("catalystFilter").value;
  return list.filter(c=>{
    const score=kind==='discovery'?c.discovery_score:c.signal_score;
    const hay=`${c.ticker} ${c.company_name||''}`.toLowerCase();
    return score>=min && hay.includes(q) && (!sector||(c.fundamentals?.industry||"")===sector) && (!cat||c.catalyst_category===cat);
  });
}

function attachCards() {
  document.querySelectorAll(".company-card").forEach(card=>{
    card.addEventListener("click", e=>{ if(e.target.closest("[data-watch]")) return; openCompany(card.dataset.ticker); });
    card.addEventListener("keydown", e=>{ if((e.key==="Enter"||e.key===" ")&&!e.target.closest("[data-watch]")){e.preventDefault();openCompany(card.dataset.ticker);} });
  });
  document.querySelectorAll("[data-watch]").forEach(btn=>btn.addEventListener("click", e=>{e.stopPropagation();toggleWatch(btn.dataset.watch);}));
}

function renderRankings() {
  const leaders=getFiltered("signal"), emerging=getFiltered("discovery");
  $("leaderGrid").innerHTML=leaders.map(c=>companyCard(c,"signal")).join("");
  $("emergingGrid").innerHTML=emerging.map(c=>companyCard(c,"discovery")).join("");
  $("leaderEmpty").hidden=leaders.length>0; $("emergingEmpty").hidden=emerging.length>0;
  $("leaderCount").textContent=`${leaders.length} shown`; $("emergingCount").textContent=`${emerging.length} shown`; attachCards();
}

function renderWatchlist() {
  const rows=[...state.watchlist].map(companyByTicker).filter(Boolean).sort((a,b)=>Math.max(b.signal_score,b.discovery_score)-Math.max(a.signal_score,a.discovery_score));
  $("watchGrid").innerHTML=rows.map(c=>companyCard(c, c.discovery_score>c.signal_score?"discovery":"signal")).join("");
  $("watchEmpty").hidden=rows.length>0; $("watchCount").textContent=rows.length?`${rows.length} watched`:""; attachCards();
}

function briefingItem(title, items, cls="") {
  const content=items.length?items.map(x=>typeof x==="string"?`<button class="ticker-link" data-open="${esc(x)}">${esc(x)}</button>`:`<button class="ticker-link" data-open="${esc(x.ticker)}">${esc(x.ticker)}</button>${x.delta!==undefined?` <span class="brief-delta ${x.delta>=0?'up':'down'}">${x.delta>0?'+':''}${fmtNum(x.delta)}</span>`:""}${x.category?` <span class="brief-category">${esc(x.category)}</span>`:""}`).join(""):"<span class=\"muted\">None this period</span>";
  return `<article class="brief-card ${cls}"><h3>${esc(title)}</h3><div class="brief-content">${content}</div></article>`;
}
function renderBriefing() {
  const b=state.briefing||{};
  $("briefingGrid").innerHTML=[
    briefingItem("New emerging", b.new_emerging||[], "good"),
    briefingItem("Accelerating", b.accelerating||[], "good"),
    briefingItem("Major catalysts", b.major_catalysts||[], "accent"),
    briefingItem("Cooling", b.cooling||[], "warn"),
    briefingItem("Left emerging top 20", b.left_emerging_top20||[], "quiet"),
  ].join("");
  document.querySelectorAll("[data-open]").forEach(b=>b.addEventListener("click",()=>openCompany(b.dataset.open)));
}

function renderLandscape() {
  const maxSector=Math.max(1,...state.sectors.map(s=>s.discovery_intensity||0));
  $("sectorMap").innerHTML=state.sectors.length?state.sectors.map(s=>`<div class="heat-row"><div class="heat-label"><strong>${esc(s.sector)}</strong><span>${s.company_count} companies · ${s.tickers.map(esc).join(" · ")}</span></div><div class="heat-track"><span style="width:${Math.max(5,(s.discovery_intensity/maxSector)*100)}%"></span></div><b>${Math.round(s.discovery_intensity)}</b></div>`).join(""):`<p class="muted">Sector data will fill in as fundamentals are cached.</p>`;
  $("themeMap").innerHTML=state.themes.length?state.themes.map(t=>`<button class="theme-chip" data-theme-tickers="${esc(t.tickers.join(','))}"><strong>${esc(t.theme)}</strong><span>${t.company_count} companies · intensity ${Math.round(t.intensity)}</span><small>${t.tickers.map(esc).join(" · ")}</small></button>`).join(""):`<p class="muted">No multi-company themes detected yet.</p>`;
  document.querySelectorAll("[data-theme-tickers]").forEach(btn=>btn.addEventListener("click",()=>{const first=btn.dataset.themeTickers.split(',')[0]; if(first) openCompany(first);}));
}

function sparkline(points, key) {
  if(!points||points.length<2) return `<div class="chart-placeholder">History builds automatically with each daily run.</div>`;
  const vals=points.map(p=>Number(p[key]||0)); const w=520,h=120,pad=8; const min=Math.min(...vals,0), max=Math.max(...vals,100); const span=Math.max(1,max-min);
  const coords=vals.map((v,i)=>`${pad+(i/(vals.length-1))*(w-pad*2)},${h-pad-((v-min)/span)*(h-pad*2)}`).join(" ");
  return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(key)} history"><line x1="8" y1="112" x2="512" y2="112"></line><polyline points="${coords}"></polyline></svg>`;
}
function metricRow(label,value){return `<div class="fund-row"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;}

function openCompany(ticker) {
  const c=companyByTicker(ticker); if(!c) return;
  const f=c.fundamentals||{}, m=c.metrics||{}, d=c.discovery_metrics||{}, mat=c.materiality||{};
  const stories=(c.stories||[]).map(s=>`<article class="story"><div class="story-meta"><span>${esc(s.source||"Unknown")}</span><span>${fmtDate(s.published_at)}</span><span>${esc(s.evidence_type||"Reporting")}</span></div><h4>${esc(s.title||"")}</h4><p>${esc(s.summary||"")}</p>${s.url?`<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">Open original source ↗</a>`:""}</article>`).join("");
  const watched=state.watchlist.has(c.ticker);
  $("dialogContent").innerHTML=`
    <div class="detail-header"><div class="detail-title-row"><div><p class="eyebrow">${esc(c.ticker)}${c.company_name?` · ${esc(c.company_name)}`:""}</p><h2>${esc(c.primary_catalyst||"Credible company development")}</h2></div><button class="watch-button detail-watch ${watched?'active':''}" data-dialog-watch="${esc(c.ticker)}">★ ${watched?'Watching':'Watch'}</button></div>
      <div class="detail-tags"><span class="badge">${esc(c.catalyst_category||"Other")}</span><span class="badge">${esc(c.attention_status||"Normal")}</span><span class="badge confidence">Confidence ${Math.round(c.confidence_score||0)}</span>${c.new_to_radar?`<span class="badge new">NEW TO RADAR</span>`:""}</div>
      <p>${esc(c.why_it_matters||"")}</p>
      <div class="triple-score"><div><span>Signal</span><strong>${Math.round(c.signal_score||0)}</strong><small>absolute attention</small></div><div><span>Discovery</span><strong>${Math.round(c.discovery_score||0)}</strong><small>vs. baseline</small></div><div><span>Confidence</span><strong>${Math.round(c.confidence_score||0)}</strong><small>evidence quality</small></div></div>
    </div>

    <div class="detail-grid">
      <section class="detail-panel"><p class="eyebrow">FUNDAMENTALS</p><h3>Company context</h3>${metricRow("Industry",f.industry||"—")}${metricRow("Market cap",fmtMoney(f.market_cap))}${metricRow("P/E (TTM)",fmtNum(f.pe_ttm,2))}${metricRow("P/S (TTM)",fmtNum(f.ps_ttm,2))}${metricRow("Revenue growth",pct(f.revenue_growth_ttm_yoy))}${metricRow("EPS growth",pct(f.eps_growth_ttm_yoy))}${metricRow("Net margin",pct(f.net_margin_ttm))}${metricRow("Debt / equity",fmtNum(f.debt_equity,2))}</section>
      <section class="detail-panel"><p class="eyebrow">MATERIALITY</p><h3>${esc(mat.label||"Unquantified")}</h3>${metricRow("Estimated event value",fmtMoney(mat.estimated_event_value))}${metricRow("Event / market cap",mat.market_cap_ratio!==null&&mat.market_cap_ratio!==undefined?`${(mat.market_cap_ratio*100).toFixed(1)}%`:"—")}${metricRow("Materiality score",`${mat.score||0} / 20`)}<p class="caution">${esc(mat.caution||"")}</p></section>
    </div>

    <section class="detail-panel history-panel"><div class="history-heading"><div><p class="eyebrow">SIGNAL HISTORY</p><h3>30-day trajectory</h3></div><div class="legend"><span>Signal</span><span>Discovery</span></div></div><div class="chart-pair"><div>${sparkline(c.history,"signal_score")}<small>Signal Score</small></div><div>${sparkline(c.history,"discovery_score")}<small>Discovery Score</small></div></div></section>

    <div class="detail-grid score-detail"><section class="detail-panel"><p class="eyebrow">SIGNAL SCORE</p>${metricRow("Primary evidence",`${Math.round(m.primary_evidence||0)} / 25`)}${metricRow("Coverage acceleration",`${Math.round(m.coverage_acceleration||0)} / 20`)}${metricRow("Catalyst strength",`${Math.round(m.catalyst_strength||0)} / 20`)}${metricRow("Corroboration",`${Math.round(m.corroboration||0)} / 15`)}${metricRow("Source quality",`${Math.round(m.source_quality||0)} / 10`)}${metricRow("Sentiment",`${Math.round(m.sentiment_signal||0)} / 10`)}</section><section class="detail-panel"><p class="eyebrow">DISCOVERY SCORE</p>${metricRow("Attention lift",`${Math.round(d.attention_lift||0)} / 35`)}${metricRow("Novelty",`${Math.round(d.novelty||0)} / 20`)}${metricRow("Source breadth",`${Math.round(d.source_breadth||0)} / 15`)}${metricRow("Catalyst strength",`${Math.round(d.catalyst_strength||0)} / 15`)}${metricRow("Primary evidence",`${Math.round(d.primary_evidence||0)} / 10`)}${metricRow("Sentiment",`${Math.round(d.sentiment||0)} / 5`)}</section></div>

    ${c.themes?.length?`<section class="detail-panel"><p class="eyebrow">THEMES</p><div class="meta-row">${c.themes.map(t=>`<span class="badge theme-badge">${esc(t)}</span>`).join("")}</div></section>`:""}
    <section class="coverage-section"><p class="eyebrow">IMPORTANT COVERAGE</p>${stories||"<p>No detailed stories stored.</p>"}</section>`;
  $("companyDialog").showModal();
  document.querySelector("[data-dialog-watch]")?.addEventListener("click", e=>{toggleWatch(e.currentTarget.dataset.dialogWatch); $("companyDialog").close(); openCompany(ticker);});
}

function populateFilters() {
  const sectors=[...new Set(state.companies.map(c=>c.fundamentals?.industry).filter(Boolean))].sort();
  const cats=[...new Set(state.companies.map(c=>c.catalyst_category).filter(Boolean))].sort();
  $("sectorFilter").innerHTML=`<option value="">All industries</option>`+sectors.map(x=>`<option>${esc(x)}</option>`).join("");
  $("catalystFilter").innerHTML=`<option value="">All catalysts</option>`+cats.map(x=>`<option>${esc(x)}</option>`).join("");
}
function renderAll(){renderRankings();renderWatchlist();}

async function init() {
  loadWatch(); renderMethodology();
  try {
    const r=await fetch(`${DATA_URL}?v=${Date.now()}`,{cache:"no-store"}); if(!r.ok) throw new Error(`HTTP ${r.status}`);
    const data=await r.json(); state.companies=data.companies||[]; state.meta=data.meta||{}; state.rankings=data.rankings||{}; state.briefing=data.briefing||{}; state.sectors=data.sectors||[]; state.themes=data.themes||[];
    $("lastUpdated").textContent=fmtDate(state.meta.generated_at); $("companiesScanned").textContent=state.meta.companies_scanned??"—"; $("signalsFound").textContent=state.companies.length; $("highConfidence").textContent=state.companies.filter(c=>(c.confidence_score||0)>=75).length; $("primaryEvents").textContent=state.companies.filter(c=>(c.evidence?.primary_source_count||0)>0).length;
    const days=state.meta.baseline_days||0; $("baselineNote").textContent=days>=7?`Emerging baseline: ${days} days of stored history.`:`Emerging baseline is building (${days} prior day${days===1?'':'s'}). Discovery rankings become more reliable as history accumulates.`;
    populateFilters(); renderBriefing(); renderLandscape(); renderAll();
  } catch(err) { console.error(err); $("lastUpdated").textContent="Data unavailable"; $("leaderGrid").innerHTML=`<div class="empty-state">Could not load ${DATA_URL}. Run the updater once.</div>`; }
}

["searchInput","minScore","sectorFilter","catalystFilter"].forEach(id=>$(id).addEventListener("input",renderRankings));
$("closeDialog").addEventListener("click",()=>$("companyDialog").close());
$("companyDialog").addEventListener("click",e=>{if(e.target===$("companyDialog")) $("companyDialog").close();});
init();
