#!/usr/bin/env python3
"""Company Signal v3 updater.

Free-first architecture:
- SEC EDGAR current 8-K feed: primary evidence + canonical ticker/name map.
- Alpha Vantage NEWS_SENTIMENT: broad vetted-news discovery + sentiment.
- Finnhub Company News: enrichment for shortlisted names.
- Finnhub Company Profile 2 + Basic Financials: cached company/fundamental context.
- Local JSON history: baselines, score history, first-seen state and prior rankings.

The browser never receives API keys. GitHub Actions writes processed JSON only.
"""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import html
import json
import math
import os
import re
import statistics
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "signals.json"
HISTORY = DATA_DIR / "history.json"
FUND_CACHE = DATA_DIR / "fundamentals_cache.json"

SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "").strip()
ALPHA_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "").strip()
MAX_COMPANIES = int(os.getenv("MAX_COMPANIES", "30"))
FUNDAMENTAL_ENRICH_LIMIT = int(os.getenv("FUNDAMENTAL_ENRICH_LIMIT", "20"))

NOW = dt.datetime.now(dt.timezone.utc)
TODAY = NOW.date()

TRUSTED_MAJOR = {
    "Reuters": 10, "Associated Press": 10, "AP": 10, "Bloomberg": 10,
    "Financial Times": 10, "The Wall Street Journal": 10, "WSJ": 10,
    "CNBC": 8, "Barron's": 8, "MarketWatch": 7, "Forbes": 6,
    "Yahoo Finance": 6, "Business Insider": 6,
}
SPECIALIST_HINTS = (
    "semiconductor", "biotech", "pharma", "mining", "energy", "technology",
    "tech", "healthcare", "defense", "aerospace", "industry", "journal",
)
MATERIAL_8K_ITEMS = {
    "1.01", "1.02", "2.01", "2.02", "2.03", "2.04",
    "3.01", "3.02", "4.01", "5.02", "7.01", "8.01",
}

CATALYST_RULES = [
    ("M&A", 20, ("merger", "acquisition", "acquire", "takeover", "buyout")),
    ("Major contract", 18, ("contract", "supply agreement", "purchase agreement", "order", "award")),
    ("Regulatory / FDA", 18, ("fda", "approval", "approved", "clearance", "regulatory approval")),
    ("Clinical trial", 17, ("phase 3", "phase iii", "clinical trial", "trial results", "endpoint")),
    ("Earnings / guidance", 14, ("earnings", "guidance", "revenue", "profit", "eps", "quarterly results")),
    ("Government funding", 15, ("government funding", "grant", "department of defense", "department of energy", "dod", "doe", "subsidy")),
    ("Financing", 11, ("offering", "financing", "capital raise", "private placement", "convertible")),
    ("Partnership", 12, ("partnership", "joint venture", "collaboration", "strategic alliance")),
    ("Product / technology", 11, ("launch", "unveils", "new product", "platform", "breakthrough", "patent", "technology")),
    ("Capacity expansion", 12, ("capacity", "expansion", "new plant", "facility", "factory", "fab", "manufacturing")),
    ("Analyst action", 8, ("upgrade", "downgrade", "price target", "initiates coverage", "analyst")),
    ("Legal / investigation", 15, ("investigation", "lawsuit", "subpoena", "sec probe", "antitrust", "litigation")),
    ("Financial distress", 18, ("bankruptcy", "default", "restructuring", "going concern")),
    ("Capital return", 9, ("buyback", "repurchase", "dividend")),
    ("IPO / listing", 13, ("ipo", "initial public offering", "listing", "nasdaq debut", "nyse debut")),
]

THEME_RULES = {
    "AI infrastructure": ("artificial intelligence", " ai ", "data center", "data centre", "gpu", "accelerator", "hyperscale"),
    "Semiconductors": ("semiconductor", "chip", "wafer", "foundry", "fab", "memory", "dram", "hbm"),
    "Power & grid": ("power grid", "electricity", "transformer", "grid", "power generation", "data center power", "utility"),
    "Nuclear & uranium": ("nuclear", "uranium", "reactor", "smr", "small modular reactor"),
    "Cybersecurity": ("cybersecurity", "cyber security", "ransomware", "endpoint security", "zero trust"),
    "Robotics & automation": ("robot", "robotics", "automation", "autonomous system", "industrial automation"),
    "Defense & aerospace": ("defense", "defence", "missile", "drone", "aerospace", "military", "pentagon"),
    "Biotech & therapeutics": ("biotech", "therapeutic", "clinical trial", "drug candidate", "fda", "phase 3", "phase iii"),
    "Critical minerals": ("critical minerals", "rare earth", "lithium", "copper", "nickel", "cobalt", "graphite"),
    "Quantum computing": ("quantum computing", "quantum computer", "qubit"),
    "Cloud & software": ("cloud", "software", "saas", "platform", "subscription"),
    "Financial technology": ("fintech", "payments", "digital banking", "payment network"),
}

MONEY_RE = re.compile(r"(?:US\s*)?\$\s*([0-9]+(?:\.[0-9]+)?)\s*(billion|million|bn|b|m)\b", re.I)


def http_json(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_text(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_dt(value: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return NOW


def iso_from_epoch(value: int | float | None) -> str:
    if not value:
        return NOW.isoformat()
    return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).isoformat()


def parse_av_time(value: str) -> str:
    try:
        return dt.datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=dt.timezone.utc).isoformat()
    except Exception:
        return NOW.isoformat()


def normalize_source(source: str) -> str:
    source = html.unescape((source or "").strip())
    for canonical in TRUSTED_MAJOR:
        if canonical.lower() in source.lower():
            return canonical
    return source or "Unknown"


def source_quality(source: str) -> int:
    src = normalize_source(source)
    if src in TRUSTED_MAJOR:
        return TRUSTED_MAJOR[src]
    lower = src.lower()
    if any(h in lower for h in SPECIALIST_HINTS):
        return 7
    if src == "SEC EDGAR":
        return 10
    return 5


def safe_summary(text: str, max_len: int = 420) -> str:
    text = re.sub(r"\s+", " ", html.unescape(text or "")).strip()
    return text if len(text) <= max_len else text[:max_len - 1].rstrip() + "…"


def story_fingerprint(title: str) -> str:
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", (title or "").lower())
    stop = {"the", "a", "an", "and", "or", "to", "of", "for", "in", "on", "with", "as", "at", "by", "from"}
    words = sorted({w for w in cleaned.split() if len(w) > 2 and w not in stop})
    return hashlib.sha1(" ".join(words[:24]).encode()).hexdigest()[:12]


def classify_catalyst(text: str) -> dict[str, Any]:
    low = f" {text.lower()} "
    matches = []
    for category, strength, keywords in CATALYST_RULES:
        if any(k in low for k in keywords):
            matches.append((strength, category))
    if not matches:
        return {"category": "Other material development", "strength": 6}
    strength, category = max(matches)
    return {"category": category, "strength": strength}


def detect_themes(text: str) -> list[str]:
    low = f" {text.lower()} "
    themes = []
    for theme, keywords in THEME_RULES.items():
        if any(k in low for k in keywords):
            themes.append(theme)
    return themes[:4]


def extract_money_value(text: str) -> float | None:
    values = []
    for amount, unit in MONEY_RE.findall(text or ""):
        value = float(amount)
        unit = unit.lower()
        if unit in {"billion", "bn", "b"}:
            value *= 1_000_000_000
        else:
            value *= 1_000_000
        values.append(value)
    return max(values) if values else None


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except Exception:
        return default


def sec_ticker_map() -> tuple[dict[str, dict], dict[str, dict]]:
    if not SEC_USER_AGENT:
        return {}, {}
    data = http_json(
        "https://www.sec.gov/files/company_tickers.json",
        headers={"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"},
    )
    by_cik, by_ticker = {}, {}
    for row in data.values():
        cik = str(row["cik_str"]).zfill(10)
        info = {"ticker": row["ticker"].upper(), "company_name": row["title"], "cik": cik}
        by_cik[cik] = info
        by_ticker[info["ticker"]] = info
    return by_cik, by_ticker


def fetch_sec_8k(by_cik: dict[str, dict]) -> list[dict]:
    if not SEC_USER_AGENT or not by_cik:
        return []
    url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&owner=include&count=100&output=atom"
    root = ET.fromstring(http_text(url, headers={"User-Agent": SEC_USER_AGENT}))
    ns = {"a": "http://www.w3.org/2005/Atom"}
    stories = []
    for entry in root.findall("a:entry", ns):
        title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
        summary = (entry.findtext("a:summary", default="", namespaces=ns) or "").strip()
        updated = entry.findtext("a:updated", default=NOW.isoformat(), namespaces=ns)
        link_el = entry.find("a:link", ns)
        link = link_el.attrib.get("href", "") if link_el is not None else ""
        cik_match = re.search(r"\((\d{10})\)", title) or re.search(r"CIK=(\d+)", link)
        if not cik_match:
            continue
        info = by_cik.get(cik_match.group(1).zfill(10))
        if not info:
            continue
        item_match = re.search(r"Items?\s+([0-9.,\s]+)", re.sub("<[^>]+>", " ", summary), re.I)
        items = re.findall(r"\d+\.\d+", item_match.group(1)) if item_match else []
        if items and not any(i in MATERIAL_8K_ITEMS for i in items):
            continue
        cleaned_summary = safe_summary(re.sub("<[^>]+>", " ", summary))
        stories.append({
            "ticker": info["ticker"], "company_name": info["company_name"], "source": "SEC EDGAR",
            "title": re.sub(r"^8-K\s*-\s*", "", title).strip(), "summary": cleaned_summary,
            "url": link, "published_at": updated, "sentiment": 0.0, "evidence_type": "SEC filing",
            "fingerprint": story_fingerprint(title),
        })
    return stories



CORPORATE_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "companies",
    "ltd", "limited", "plc", "llc", "group", "holdings", "holding", "sa", "ag",
    "nv", "lp", "the"
}

def normalized_company_core(name: str) -> str:
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    while words and words[-1] in CORPORATE_SUFFIXES:
        words.pop()
    while words and words[0] == "the":
        words.pop(0)
    return " ".join(words).strip()

def title_mentions_ticker(title: str, ticker: str) -> bool:
    ticker = (ticker or "").upper().strip()
    if not ticker:
        return False
    # Single-letter tickers are too ambiguous unless explicitly formatted.
    if len(ticker) == 1:
        explicit = [
            rf"\${re.escape(ticker)}\b",
            rf"\({re.escape(ticker)}\)",
            rf"(?:NYSE|NASDAQ|AMEX)\s*:\s*{re.escape(ticker)}\b",
        ]
        return any(re.search(p, title or "", re.I) for p in explicit)
    return bool(re.search(rf"(?<![A-Z0-9])\$?{re.escape(ticker)}(?![A-Z0-9])", title or "", re.I))

def title_mentions_company(title: str, company_name: str) -> bool:
    core = normalized_company_core(company_name)
    if len(core) < 3:
        return False
    title_norm = " ".join(re.findall(r"[a-z0-9]+", (title or "").lower()))
    if core in title_norm:
        return True
    # For longer legal names, require the first two meaningful words together.
    words = [w for w in core.split() if len(w) > 1]
    if len(words) >= 2:
        short = " ".join(words[:2])
        if len(short) >= 5 and short in title_norm:
            return True
    return False

def is_strict_company_story(story: dict, ticker: str, company_name: str) -> bool:
    # SEC filing entries are inherently company-specific and are retained.
    if story.get("evidence_type") == "SEC filing":
        return True
    title = story.get("title", "")
    return title_mentions_company(title, company_name) or title_mentions_ticker(title, ticker)

def general_article_from_alpha(article: dict) -> dict:
    return {
        "source": normalize_source(article.get("source", "Unknown")),
        "title": article.get("title", ""),
        "summary": safe_summary(article.get("summary", "")),
        "url": article.get("url", ""),
        "published_at": parse_av_time(article.get("time_published", "")),
        "sentiment": float(article.get("overall_sentiment_score", 0) or 0),
        "sentiment_label": article.get("overall_sentiment_label", ""),
        "fingerprint": story_fingerprint(article.get("title", "")),
    }


def fetch_alpha_news(ticker_names: dict[str, str]) -> tuple[list[dict], list[dict]]:
    if not ALPHA_KEY:
        return [], []
    params = {
        "function": "NEWS_SENTIMENT",
        "topics": "technology,financial_markets,earnings,mergers_and_acquisitions,ipo",
        "sort": "LATEST", "limit": "1000", "apikey": ALPHA_KEY,
    }
    data = http_json("https://www.alphavantage.co/query?" + urllib.parse.urlencode(params))
    scoring_stories = []
    general_news = []
    for article in data.get("feed", []):
        general_news.append(general_article_from_alpha(article))
        source = normalize_source(article.get("source", "Unknown"))
        title, summary = article.get("title", ""), article.get("summary", "")
        published_at = parse_av_time(article.get("time_published", ""))
        for ts in article.get("ticker_sentiment", []):
            ticker = (ts.get("ticker") or "").upper().strip()
            if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,7}", ticker):
                continue
            company_name = ticker_names.get(ticker, "")
            try:
                relevance = float(ts.get("relevance_score", 0))
                sentiment = float(ts.get("ticker_sentiment_score", 0))
            except Exception:
                relevance, sentiment = 0.0, 0.0

            # Ranking can use strongly ticker-tagged API stories.
            # Display still requires headline-level identity.
            if relevance < 0.35:
                continue

            candidate = {
                "ticker": ticker, "company_name": company_name, "source": source, "title": title,
                "summary": safe_summary(summary), "url": article.get("url", ""),
                "published_at": published_at, "sentiment": sentiment,
                "evidence_type": "Professional reporting", "fingerprint": story_fingerprint(title),
                "relevance": relevance,
            }
            candidate["display_relevant"] = is_strict_company_story(candidate, ticker, company_name)
            scoring_stories.append(candidate)
    return scoring_stories, dedupe_general_news(general_news)

def fetch_finnhub_news(ticker: str, company_name: str) -> list[dict]:
    if not FINNHUB_KEY:
        return []
    url = "https://finnhub.io/api/v1/company-news?" + urllib.parse.urlencode({
        "symbol": ticker, "from": (TODAY - dt.timedelta(days=3)).isoformat(),
        "to": TODAY.isoformat(), "token": FINNHUB_KEY,
    })
    try:
        rows = http_json(url)
    except Exception:
        return []
    stories = []
    for row in rows[:30]:
        title = row.get("headline", "")
        candidate = {
            "ticker": ticker, "company_name": company_name, "source": normalize_source(row.get("source", "Finnhub")),
            "title": title, "summary": safe_summary(row.get("summary", "")), "url": row.get("url", ""),
            "published_at": iso_from_epoch(row.get("datetime")), "sentiment": 0.0,
            "evidence_type": "Professional reporting", "fingerprint": story_fingerprint(title),
        }
        candidate["display_relevant"] = is_strict_company_story(candidate, ticker, company_name)
        stories.append(candidate)
    return stories



def dedupe_general_news(stories: list[dict], limit: int = 40) -> list[dict]:
    best = {}
    for s in stories:
        fp = s.get("fingerprint") or story_fingerprint(s.get("title", ""))
        existing = best.get(fp)
        if not existing or source_quality(s.get("source", "")) > source_quality(existing.get("source", "")):
            best[fp] = s
    rows = sorted(best.values(), key=lambda s: s.get("published_at", ""), reverse=True)
    return rows[:limit]


def dedupe_stories(stories: list[dict]) -> list[dict]:
    best = {}
    for s in stories:
        key = (s["ticker"], s["fingerprint"])
        existing = best.get(key)
        rank = (1 if s.get("evidence_type") == "SEC filing" else 0, source_quality(s.get("source", "")))
        old_rank = (-1, -1) if not existing else (
            1 if existing.get("evidence_type") == "SEC filing" else 0,
            source_quality(existing.get("source", "")),
        )
        if not existing or rank > old_rank:
            best[key] = s
    return list(best.values())


def history_days(history: dict, ticker: str, days: int = 30) -> list[float]:
    vals = []
    for day, counts in history.get("days", {}).items():
        try:
            d = dt.date.fromisoformat(day)
        except Exception:
            continue
        if TODAY - dt.timedelta(days=days) <= d < TODAY:
            vals.append(float(counts.get(ticker, 0)))
    return vals


def baseline_for(history: dict, ticker: str) -> float:
    vals = history_days(history, ticker, 15)
    return statistics.mean(vals) if vals else 0.0


def history_day_count(history: dict) -> int:
    dates = []
    for day in history.get("days", {}):
        try:
            d = dt.date.fromisoformat(day)
            if TODAY - dt.timedelta(days=30) <= d < TODAY:
                dates.append(d)
        except Exception:
            pass
    return len(set(dates))


def previous_snapshot(history: dict, ticker: str) -> dict:
    prior = []
    for day, snapshot in history.get("scores", {}).items():
        try:
            d = dt.date.fromisoformat(day)
        except Exception:
            continue
        if d < TODAY and ticker in snapshot:
            prior.append((d, snapshot[ticker]))
    return max(prior, key=lambda x: x[0])[1] if prior else {}


def first_seen(history: dict, ticker: str) -> str:
    first = history.setdefault("first_seen", {}).get(ticker)
    if not first:
        first = TODAY.isoformat()
        history["first_seen"][ticker] = first
    return first


def cache_fundamentals() -> dict:
    return load_json(FUND_CACHE, {"updated": {}})


def cached_is_fresh(entry: dict, days: int = 7) -> bool:
    try:
        stamp = dt.datetime.fromisoformat(entry.get("cached_at", "").replace("Z", "+00:00"))
        return NOW - stamp < dt.timedelta(days=days)
    except Exception:
        return False


def finnhub_fundamentals(ticker: str) -> dict:
    if not FINNHUB_KEY:
        return {}
    profile_url = "https://finnhub.io/api/v1/stock/profile2?" + urllib.parse.urlencode({"symbol": ticker, "token": FINNHUB_KEY})
    metrics_url = "https://finnhub.io/api/v1/stock/metric?" + urllib.parse.urlencode({"symbol": ticker, "metric": "all", "token": FINNHUB_KEY})
    profile = http_json(profile_url)
    time.sleep(0.35)
    metrics_payload = http_json(metrics_url)
    metric = metrics_payload.get("metric", {}) if isinstance(metrics_payload, dict) else {}

    market_cap_m = profile.get("marketCapitalization")
    market_cap = float(market_cap_m) * 1_000_000 if isinstance(market_cap_m, (int, float)) else None

    def pick(*keys):
        for k in keys:
            v = metric.get(k)
            if isinstance(v, (int, float)):
                return v
        return None

    fundamentals = {
        "name": profile.get("name") or "",
        "industry": profile.get("finnhubIndustry") or "",
        "country": profile.get("country") or "",
        "exchange": profile.get("exchange") or "",
        "ipo_date": profile.get("ipo") or "",
        "weburl": profile.get("weburl") or "",
        "logo": profile.get("logo") or "",
        "market_cap": market_cap,
        "pe_ttm": pick("peTTM", "peNormalizedAnnual"),
        "ps_ttm": pick("psTTM", "priceSalesTTM"),
        "pb_annual": pick("pbAnnual"),
        "revenue_growth_ttm_yoy": pick("revenueGrowthTTMYoy", "revenueGrowth3Y"),
        "eps_growth_ttm_yoy": pick("epsGrowthTTMYoy", "epsGrowth3Y"),
        "gross_margin_ttm": pick("grossMarginTTM"),
        "net_margin_ttm": pick("netProfitMarginTTM", "netMargin"),
        "current_ratio": pick("currentRatioAnnual", "currentRatioQuarterly"),
        "debt_equity": pick("totalDebt/totalEquityAnnual", "totalDebt/totalEquityQuarterly"),
        "beta": pick("beta"),
    }
    return fundamentals


def enrich_fundamentals(tickers: list[str], cache: dict) -> dict[str, dict]:
    updated = cache.setdefault("updated", {})
    result = {}
    calls = 0
    for ticker in tickers:
        entry = updated.get(ticker, {})
        if cached_is_fresh(entry):
            result[ticker] = entry.get("data", {})
            continue
        if not FINNHUB_KEY or calls >= FUNDAMENTAL_ENRICH_LIMIT:
            result[ticker] = entry.get("data", {})
            continue
        try:
            data = finnhub_fundamentals(ticker)
            updated[ticker] = {"cached_at": NOW.isoformat(), "data": data}
            result[ticker] = data
            calls += 1
            time.sleep(0.55)
        except Exception as exc:
            print(f"Fundamentals warning for {ticker}: {exc}")
            result[ticker] = entry.get("data", {})
    FUND_CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))
    return result


def materiality(stories: list[dict], fundamentals: dict) -> dict:
    candidate = None
    candidate_story = None
    material_categories = {"M&A", "Major contract", "Government funding", "Financing", "Partnership", "Capacity expansion", "Regulatory / FDA"}
    for s in stories:
        text = f"{s.get('title','')} {s.get('summary','')}"
        if classify_catalyst(text)["category"] not in material_categories:
            continue
        value = extract_money_value(text)
        if value and (candidate is None or value > candidate):
            candidate, candidate_story = value, s
    market_cap = fundamentals.get("market_cap")
    ratio = candidate / market_cap if candidate and market_cap and market_cap > 0 else None
    if ratio is None:
        score, label = 5, "Unquantified"
    elif ratio >= 0.50:
        score, label = 20, "Potentially transformative"
    elif ratio >= 0.20:
        score, label = 17, "Very material"
    elif ratio >= 0.08:
        score, label = 14, "Material"
    elif ratio >= 0.02:
        score, label = 10, "Meaningful"
    else:
        score, label = 6, "Limited relative size"
    return {
        "estimated_event_value": candidate,
        "market_cap_ratio": round(ratio, 4) if ratio is not None else None,
        "score": score,
        "label": label,
        "basis": candidate_story.get("title", "") if candidate_story else "",
        "caution": "Automated estimate from amounts mentioned in coverage; verify context at the source." if candidate else "No reliably extractable event value found.",
    }


def score_company(ticker: str, stories: list[dict], baseline: float, baseline_days: int,
                  company_name: str, fundamentals: dict, history: dict) -> dict:
    stories = sorted(stories, key=lambda s: s.get("published_at", ""), reverse=True)
    display_stories = [s for s in stories if s.get("display_relevant") or s.get("evidence_type") == "SEC filing"]
    recent24 = [s for s in stories if parse_dt(s.get("published_at", "")) >= NOW - dt.timedelta(hours=24)]
    primary_count = sum(s.get("evidence_type") == "SEC filing" for s in stories)
    independent_sources = len({normalize_source(s.get("source", "")) for s in stories if s.get("source")})
    current_count = len(recent24)
    unique_clusters = len({s.get("fingerprint") for s in stories})

    if baseline <= 0:
        ratio = float(current_count) if current_count else 0.0
        coverage_accel = min(20.0, current_count * 5.0)
    else:
        ratio = current_count / max(0.5, baseline)
        coverage_accel = min(20.0, max(0.0, 8.0 * math.log2(max(1.0, ratio))))

    catalyst_details = [classify_catalyst(f"{s.get('title','')} {s.get('summary','')}") for s in stories]
    strongest_cat = max(catalyst_details, key=lambda x: x["strength"], default={"category": "Other material development", "strength": 6})
    primary_evidence = 25 if primary_count else 0
    corroboration = min(15.0, max(0.0, (independent_sources - 1) * 5.0))
    src_scores = sorted({source_quality(s.get("source", "")) for s in stories}, reverse=True)
    src_quality = round(sum(src_scores[:3]) / max(1, len(src_scores[:3])), 1) if src_scores else 0.0
    sentiments = [float(s.get("sentiment", 0)) for s in stories if abs(float(s.get("sentiment", 0))) > .001]
    avg_sent = statistics.mean(sentiments) if sentiments else 0.0
    sentiment_signal = min(10.0, 5.0 + abs(avg_sent) * 5.0)
    signal_score = min(100.0, round(primary_evidence + coverage_accel + strongest_cat["strength"] + corroboration + src_quality + sentiment_signal, 1))

    attention_lift = min(35.0, current_count * 8.0) if baseline <= 0 else min(35.0, max(0.0, 12.0 * math.log2(max(1.0, ratio))))
    novelty = max(0.0, 20.0 - min(20.0, baseline * 2.5))
    source_breadth = min(15.0, independent_sources * 3.0)
    catalyst15 = min(15.0, strongest_cat["strength"] / 20.0 * 15.0)
    primary10 = 10.0 if primary_count else 0.0
    sentiment5 = min(5.0, sentiment_signal / 10.0 * 5.0)
    discovery_score = min(100.0, round(attention_lift + novelty + source_breadth + catalyst15 + primary10 + sentiment5, 1))

    confidence = min(100.0, round(
        (25 if primary_count else 0) +
        min(30, independent_sources * 8) +
        min(25, src_quality * 2.5) +
        min(20, unique_clusters * 4), 1
    ))

    if avg_sent > .15:
        sentiment_label = "Positive"
    elif avg_sent < -.15:
        sentiment_label = "Negative"
    else:
        sentiment_label = "Mixed / neutral"

    if discovery_score >= 80 and signal_score >= 75:
        status = "Accelerating leader"
    elif discovery_score >= 75:
        status = "Breaking out"
    elif discovery_score >= 60:
        status = "Emerging"
    elif signal_score >= 80:
        status = "Established leader"
    elif ratio > 1.2:
        status = "Above baseline"
    else:
        status = "Normal"

    first = first_seen(history, ticker)
    days_on_radar = max(1, (TODAY - dt.date.fromisoformat(first)).days + 1)
    prior = previous_snapshot(history, ticker)
    signal_delta = round(signal_score - float(prior.get("signal_score", signal_score)), 1) if prior else None
    discovery_delta = round(discovery_score - float(prior.get("discovery_score", discovery_score)), 1) if prior else None

    text_blob = " ".join(f"{s.get('title','')} {s.get('summary','')}" for s in stories)
    themes = detect_themes(text_blob)
    mat = materiality(stories, fundamentals)

    top_stories = sorted(stories, key=lambda s: (
        1 if s.get("evidence_type") == "SEC filing" else 0,
        source_quality(s.get("source", "")), s.get("published_at", "")), reverse=True)[:7]
    primary_catalyst = top_stories[0].get("title", "") if top_stories else "Credible company development"

    return {
        "ticker": ticker,
        "company_name": company_name or fundamentals.get("name", "") or next((s.get("company_name") for s in stories if s.get("company_name")), ""),
        "signal_score": signal_score,
        "discovery_score": discovery_score,
        "confidence_score": confidence,
        "primary_catalyst": primary_catalyst,
        "catalyst_category": strongest_cat["category"],
        "why_it_matters": (
            f"{unique_clusters} unique credible information item{'s' if unique_clusters != 1 else ''} from "
            f"{independent_sources} independent source{'s' if independent_sources != 1 else ''}. "
            f"Coverage is {ratio:.1f}× the stored baseline." if baseline > 0 else
            f"{unique_clusters} unique credible information item{'s' if unique_clusters != 1 else ''} from "
            f"{independent_sources} independent source{'s' if independent_sources != 1 else ''}. This company is new to the stored baseline."
        ),
        "sentiment_label": sentiment_label,
        "attention_status": status,
        "article_count_24h": current_count,
        "latest_event_at": stories[0].get("published_at", NOW.isoformat()) if stories else NOW.isoformat(),
        "new_to_radar": days_on_radar <= 2,
        "days_on_radar": days_on_radar,
        "change": {"signal_delta": signal_delta, "discovery_delta": discovery_delta},
        "evidence": {
            "primary_source_count": primary_count,
            "independent_sources": independent_sources,
            "unique_story_clusters": unique_clusters,
        },
        "metrics": {
            "primary_evidence": primary_evidence, "coverage_acceleration": round(coverage_accel, 1),
            "catalyst_strength": strongest_cat["strength"], "corroboration": round(corroboration, 1),
            "source_quality": src_quality, "sentiment_signal": round(sentiment_signal, 1),
            "coverage_ratio_vs_baseline": round(ratio, 2),
        },
        "discovery_metrics": {
            "attention_lift": round(attention_lift, 1), "novelty": round(novelty, 1),
            "source_breadth": round(source_breadth, 1), "catalyst_strength": round(catalyst15, 1),
            "primary_evidence": round(primary10, 1), "sentiment": round(sentiment5, 1),
            "coverage_ratio_vs_baseline": round(ratio, 2),
        },
        "baseline": {
            "avg_items_24h": round(float(baseline), 2), "days_available": baseline_days,
            "maturity": "established" if baseline_days >= 7 else "building",
        },
        "materiality": mat,
        "fundamentals": fundamentals,
        "themes": themes,
        "stories": [s for s in top_stories if s.get("display_relevant") or s.get("evidence_type") == "SEC filing"][:6],
    }


def build_sector_summary(companies: list[dict]) -> list[dict]:
    groups = collections.defaultdict(list)
    for c in companies:
        sector = c.get("fundamentals", {}).get("industry") or "Unclassified"
        groups[sector].append(c)
    rows = []
    for sector, members in groups.items():
        if sector == "Unclassified" and len(members) < 2:
            continue
        avg_discovery = statistics.mean(c.get("discovery_score", 0) for c in members)
        avg_signal = statistics.mean(c.get("signal_score", 0) for c in members)
        rows.append({
            "sector": sector, "company_count": len(members),
            "discovery_intensity": round(avg_discovery, 1), "signal_intensity": round(avg_signal, 1),
            "tickers": [c["ticker"] for c in sorted(members, key=lambda x: x.get("discovery_score", 0), reverse=True)[:6]],
        })
    return sorted(rows, key=lambda x: (x["discovery_intensity"], x["company_count"]), reverse=True)[:12]


def build_theme_summary(companies: list[dict]) -> list[dict]:
    groups = collections.defaultdict(list)
    for c in companies:
        for theme in c.get("themes", []):
            groups[theme].append(c)
    rows = []
    for theme, members in groups.items():
        rows.append({
            "theme": theme, "company_count": len(members),
            "intensity": round(statistics.mean(c.get("discovery_score", 0) for c in members), 1),
            "tickers": [c["ticker"] for c in sorted(members, key=lambda x: x.get("discovery_score", 0), reverse=True)[:8]],
        })
    return sorted(rows, key=lambda x: (x["company_count"], x["intensity"]), reverse=True)[:10]


def build_briefing(companies: list[dict], history: dict, emerging: list[dict]) -> dict:
    prior_rankings = history.get("rankings", {})
    prior_days = []
    for day in prior_rankings:
        try:
            d = dt.date.fromisoformat(day)
            if d < TODAY:
                prior_days.append(d)
        except Exception:
            pass
    prior_emerging = set()
    if prior_days:
        last = max(prior_days).isoformat()
        prior_emerging = set(prior_rankings.get(last, {}).get("emerging_signals", []))
    current_emerging = {c["ticker"] for c in emerging[:20]}

    new_emerging = [c["ticker"] for c in emerging[:20] if c["ticker"] not in prior_emerging][:8]
    accelerating = sorted(
        [c for c in companies if (c.get("change", {}).get("discovery_delta") or 0) >= 10],
        key=lambda x: x["change"]["discovery_delta"], reverse=True)[:8]
    cooling = sorted(
        [c for c in companies if (c.get("change", {}).get("discovery_delta") or 0) <= -10],
        key=lambda x: x["change"]["discovery_delta"] or 0)[:8]
    major_catalysts = sorted(
        [c for c in companies if c.get("metrics", {}).get("catalyst_strength", 0) >= 15],
        key=lambda x: (x.get("confidence_score", 0), x.get("signal_score", 0)), reverse=True)[:8]
    return {
        "new_emerging": new_emerging,
        "accelerating": [{"ticker": c["ticker"], "delta": c["change"]["discovery_delta"]} for c in accelerating],
        "cooling": [{"ticker": c["ticker"], "delta": c["change"]["discovery_delta"]} for c in cooling],
        "major_catalysts": [{"ticker": c["ticker"], "category": c.get("catalyst_category"), "headline": c.get("primary_catalyst")} for c in major_catalysts],
        "left_emerging_top20": sorted(prior_emerging - current_emerging)[:8],
    }


def score_history_for(history: dict, ticker: str, current: dict) -> list[dict]:
    points = []
    for day, snap in history.get("scores", {}).items():
        if ticker in snap:
            points.append({"date": day, **snap[ticker]})
    points.append({"date": TODAY.isoformat(), "signal_score": current["signal_score"], "discovery_score": current["discovery_score"]})
    points.sort(key=lambda x: x["date"])
    return points[-30:]


def save_history(history: dict, counts: dict[str, int], companies: list[dict], leaders: list[dict], emerging: list[dict]) -> None:
    history.setdefault("days", {})[TODAY.isoformat()] = counts
    history.setdefault("scores", {})[TODAY.isoformat()] = {
        c["ticker"]: {"signal_score": c["signal_score"], "discovery_score": c["discovery_score"]}
        for c in companies
    }
    history.setdefault("rankings", {})[TODAY.isoformat()] = {
        "market_leaders": [c["ticker"] for c in leaders[:20]],
        "emerging_signals": [c["ticker"] for c in emerging[:20]],
    }
    cutoff = TODAY - dt.timedelta(days=60)
    for key in ("days", "scores", "rankings"):
        for day in list(history.get(key, {})):
            try:
                if dt.date.fromisoformat(day) < cutoff:
                    del history[key][day]
            except Exception:
                del history[key][day]
    HISTORY.write_text(json.dumps(history, indent=2, ensure_ascii=False, sort_keys=True))


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    history = load_json(HISTORY, {"days": {}, "scores": {}, "rankings": {}, "first_seen": {}})
    history.setdefault("days", {})
    history.setdefault("scores", {})
    history.setdefault("rankings", {})
    history.setdefault("first_seen", {})
    fund_cache = cache_fundamentals()

    all_stories = []
    general_news = []
    ticker_names: dict[str, str] = {}
    by_ticker: dict[str, dict] = {}

    if SEC_USER_AGENT:
        try:
            by_cik, by_ticker = sec_ticker_map()
            ticker_names = {t: info["company_name"] for t, info in by_ticker.items()}
            all_stories.extend(fetch_sec_8k(by_cik))
        except Exception as exc:
            print(f"SEC collection warning: {exc}")
    else:
        print("SEC_USER_AGENT not set; SEC source skipped.")

    if ALPHA_KEY:
        try:
            alpha_company_stories, general_news = fetch_alpha_news(ticker_names)
            all_stories.extend(alpha_company_stories)
        except Exception as exc:
            print(f"Alpha Vantage collection warning: {exc}")
    else:
        print("ALPHA_VANTAGE_API_KEY not set; Alpha Vantage source skipped.")

    grouped = collections.defaultdict(list)
    for s in dedupe_stories(all_stories):
        grouped[s["ticker"]].append(s)

    baseline_days = history_day_count(history)
    prelim = []
    for ticker, stories in grouped.items():
        company = score_company(ticker, stories, baseline_for(history, ticker), baseline_days,
                                ticker_names.get(ticker, ""), {}, history)
        prelim.append(company)
    leader_pre = sorted(prelim, key=lambda x: x["signal_score"], reverse=True)[:MAX_COMPANIES]
    emerging_pre = sorted(prelim, key=lambda x: x["discovery_score"], reverse=True)[:MAX_COMPANIES]
    candidates = list(dict.fromkeys([c["ticker"] for c in leader_pre + emerging_pre]))[:MAX_COMPANIES * 2]

    if FINNHUB_KEY:
        for ticker in candidates:
            try:
                all_stories.extend(fetch_finnhub_news(ticker, ticker_names.get(ticker, '')))
                time.sleep(0.7)
            except Exception as exc:
                print(f"Finnhub news warning for {ticker}: {exc}")

    # Ranking uses vetted ticker-tagged stories. Visible company news is filtered
    # later to headline-specific stories only.
    for s in all_stories:
        ticker = s.get("ticker", "")
        company_name = ticker_names.get(ticker, s.get("company_name", ""))
        s["company_name"] = company_name or s.get("company_name", "")
        if s.get("evidence_type") == "SEC filing":
            s["display_relevant"] = True
        elif "display_relevant" not in s:
            s["display_relevant"] = is_strict_company_story(s, ticker, company_name)

    grouped = collections.defaultdict(list)
    for s in dedupe_stories(all_stories):
        grouped[s["ticker"]].append(s)

    # Enrich fundamentals only for the most useful union, with a 7-day cache.
    prelim2 = []
    for ticker, stories in grouped.items():
        prelim2.append(score_company(ticker, stories, baseline_for(history, ticker), baseline_days,
                                     ticker_names.get(ticker, ""), {}, history))
    leader2 = sorted(prelim2, key=lambda x: x["signal_score"], reverse=True)[:MAX_COMPANIES]
    emerging2 = sorted(prelim2, key=lambda x: x["discovery_score"], reverse=True)[:MAX_COMPANIES]
    enrichment_tickers = list(dict.fromkeys([c["ticker"] for c in leader2[:15] + emerging2[:15]]))
    fundamentals_map = enrich_fundamentals(enrichment_tickers, fund_cache)

    companies = []
    today_counts = {}
    for ticker, stories in grouped.items():
        count24 = sum(parse_dt(s.get("published_at", "")) >= NOW - dt.timedelta(hours=24) for s in stories)
        today_counts[ticker] = int(count24)
        c = score_company(ticker, stories, baseline_for(history, ticker), baseline_days,
                          ticker_names.get(ticker, ""), fundamentals_map.get(ticker, {}), history)
        companies.append(c)

    leaders = sorted(companies, key=lambda x: x["signal_score"], reverse=True)[:MAX_COMPANIES]
    emerging = sorted(companies, key=lambda x: x["discovery_score"], reverse=True)[:MAX_COMPANIES]
    selected = {c["ticker"] for c in leaders + emerging}
    companies = [c for c in companies if c["ticker"] in selected]

    # Re-run materiality for selected names if cached fundamentals exist outside enrichment set.
    cached_data = fund_cache.get("updated", {})
    for c in companies:
        if not c.get("fundamentals") and c["ticker"] in cached_data:
            c["fundamentals"] = cached_data[c["ticker"]].get("data", {})
            c["materiality"] = materiality(c.get("stories", []), c["fundamentals"])
        c["history"] = score_history_for(history, c["ticker"], c)

    leaders = sorted(companies, key=lambda x: x["signal_score"], reverse=True)[:MAX_COMPANIES]
    emerging = sorted(companies, key=lambda x: x["discovery_score"], reverse=True)[:MAX_COMPANIES]
    companies.sort(key=lambda x: max(x["signal_score"], x["discovery_score"]), reverse=True)

    output = {
        "meta": {
            "generated_at": NOW.isoformat(), "companies_scanned": len(grouped),
            "sources_enabled": {"sec_edgar": bool(SEC_USER_AGENT), "alpha_vantage": bool(ALPHA_KEY), "finnhub": bool(FINNHUB_KEY)},
            "model_version": "4.1-strict-display", "baseline_days": baseline_days,
            "baseline_maturity": "established" if baseline_days >= 7 else "building",
            "fundamentals_cache_days": 7,
        },
        "rankings": {
            "market_leaders": [c["ticker"] for c in leaders],
            "emerging_signals": [c["ticker"] for c in emerging],
        },
        "briefing": build_briefing(companies, history, emerging),
        "sectors": build_sector_summary(companies),
        "themes": build_theme_summary(companies),
        "general_news": dedupe_general_news(general_news, 30),
        "companies": companies,
    }
    OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    save_history(history, today_counts, companies, leaders, emerging)
    print(f"Wrote {OUT} with {len(leaders)} leaders, {len(emerging)} emerging signals, {len(output['themes'])} themes.")


if __name__ == "__main__":
    main()
