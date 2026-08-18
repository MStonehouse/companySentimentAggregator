#!/usr/bin/env python3
"""
Company Signal updater.

Free-first pipeline:
1) SEC EDGAR current 8-K feed -> primary evidence.
2) Alpha Vantage NEWS_SENTIMENT -> broad discovery and sentiment.
3) Finnhub company-news -> optional enrichment for discovered tickers.
4) Local history -> coverage acceleration baseline.
5) Transparent rule-based Signal Score -> data/signals.json.

Environment variables:
  SEC_USER_AGENT       REQUIRED for respectful SEC automated access.
                       Example: "CompanySignal mike@example.com"
  ALPHA_VANTAGE_API_KEY optional but strongly recommended
  FINNHUB_API_KEY       optional
  MAX_COMPANIES         optional, default 30
"""

from __future__ import annotations

import collections
import datetime as dt
import email.utils
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

SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "").strip()
ALPHA_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "").strip()
MAX_COMPANIES = int(os.getenv("MAX_COMPANIES", "30"))

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
    "tech", "healthcare", "defense", "aerospace", "industry", "journal"
)

CATALYST_KEYWORDS = {
    "merger": 20, "acquisition": 20, "acquire": 18, "takeover": 20,
    "contract": 18, "agreement": 13, "award": 15, "order": 12,
    "fda": 18, "approval": 18, "approved": 18, "phase 3": 17, "trial": 12,
    "earnings": 12, "revenue": 10, "guidance": 12, "profit": 9,
    "partnership": 12, "joint venture": 13, "launch": 10, "unveils": 9,
    "patent": 9, "breakthrough": 12, "discovery": 10,
    "bankruptcy": 18, "default": 18, "investigation": 14, "subpoena": 14,
    "offering": 10, "financing": 9, "buyback": 9, "dividend": 7,
}

MATERIAL_8K_ITEMS = {
    "1.01", "1.02", "2.01", "2.02", "2.03", "2.04",
    "3.01", "3.02", "4.01", "5.02", "7.01", "8.01"
}

def http_json(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def http_text(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

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
    if any(hint in lower for hint in SPECIALIST_HINTS):
        return 7
    return 5

def safe_summary(text: str, max_len: int = 360) -> str:
    text = re.sub(r"\s+", " ", html.unescape(text or "")).strip()
    return text if len(text) <= max_len else text[:max_len-1].rstrip() + "…"

def story_fingerprint(title: str) -> str:
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", (title or "").lower())
    stop = {"the","a","an","and","or","to","of","for","in","on","with","as","at","by","from"}
    words = sorted({w for w in cleaned.split() if len(w) > 2 and w not in stop})
    return hashlib.sha1(" ".join(words[:24]).encode()).hexdigest()[:12]

def catalyst_score(text: str) -> int:
    low = (text or "").lower()
    return min(20, max([v for k,v in CATALYST_KEYWORDS.items() if k in low] or [5]))

def choose_catalyst(stories: list[dict]) -> str:
    if not stories:
        return "Unusual increase in credible company information"
    ranked = sorted(
        stories,
        key=lambda s: (
            1 if s.get("evidence_type") == "SEC filing" else 0,
            catalyst_score((s.get("title","") + " " + s.get("summary",""))),
            source_quality(s.get("source",""))
        ),
        reverse=True
    )
    return ranked[0].get("title") or "Credible information acceleration"

def load_history() -> dict:
    if not HISTORY.exists():
        return {"days": {}}
    try:
        return json.loads(HISTORY.read_text())
    except Exception:
        return {"days": {}}

def save_history(history: dict, counts: dict[str, int]) -> None:
    days = history.setdefault("days", {})
    days[TODAY.isoformat()] = counts
    cutoff = TODAY - dt.timedelta(days=45)
    for d in list(days):
        try:
            if dt.date.fromisoformat(d) < cutoff:
                del days[d]
        except Exception:
            del days[d]
    HISTORY.write_text(json.dumps(history, indent=2, sort_keys=True))

def baseline_for(history: dict, ticker: str) -> float:
    vals = []
    for day, counts in history.get("days", {}).items():
        try:
            d = dt.date.fromisoformat(day)
        except Exception:
            continue
        if TODAY - dt.timedelta(days=15) <= d < TODAY:
            vals.append(float(counts.get(ticker, 0)))
    return statistics.mean(vals) if vals else 0.0

def sec_ticker_map() -> dict[str, dict]:
    if not SEC_USER_AGENT:
        return {}
    data = http_json(
        "https://www.sec.gov/files/company_tickers.json",
        headers={"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    )
    out = {}
    for row in data.values():
        cik = str(row["cik_str"]).zfill(10)
        out[cik] = {"ticker": row["ticker"].upper(), "company_name": row["title"]}
    return out

def fetch_sec_8k(ticker_map: dict[str, dict]) -> list[dict]:
    if not SEC_USER_AGENT or not ticker_map:
        return []
    url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&owner=include&count=100&output=atom"
    text = http_text(url, headers={"User-Agent": SEC_USER_AGENT})
    root = ET.fromstring(text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    stories = []

    for entry in root.findall("a:entry", ns):
        title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
        summary = (entry.findtext("a:summary", default="", namespaces=ns) or "").strip()
        updated = entry.findtext("a:updated", default=NOW.isoformat(), namespaces=ns)
        link_el = entry.find("a:link", ns)
        url = link_el.attrib.get("href", "") if link_el is not None else ""

        cik_match = re.search(r"\((\d{10})\)", title)
        if not cik_match:
            cik_match = re.search(r"CIK=(\d+)", url)
        if not cik_match:
            continue
        cik = cik_match.group(1).zfill(10)
        info = ticker_map.get(cik)
        if not info:
            continue

        item_match = re.search(r"Items?\s+([0-9.,\s]+)", re.sub("<[^>]+>", " ", summary), re.I)
        items = []
        if item_match:
            items = re.findall(r"\d+\.\d+", item_match.group(1))
        material = not items or any(i in MATERIAL_8K_ITEMS for i in items)
        if not material:
            continue

        stories.append({
            "ticker": info["ticker"],
            "company_name": info["company_name"],
            "source": "SEC EDGAR",
            "title": re.sub(r"^8-K\s*-\s*", "", title).strip(),
            "summary": safe_summary(re.sub("<[^>]+>", " ", summary)),
            "url": url,
            "published_at": updated,
            "sentiment": 0.0,
            "evidence_type": "SEC filing",
            "fingerprint": story_fingerprint(title),
        })
    return stories

def fetch_alpha_news() -> list[dict]:
    if not ALPHA_KEY:
        return []
    params = {
        "function": "NEWS_SENTIMENT",
        "topics": "technology,financial_markets,earnings,mergers_and_acquisitions,ipo",
        "sort": "LATEST",
        "limit": "1000",
        "apikey": ALPHA_KEY,
    }
    url = "https://www.alphavantage.co/query?" + urllib.parse.urlencode(params)
    data = http_json(url)
    feed = data.get("feed", [])
    stories = []

    for article in feed:
        source = normalize_source(article.get("source", "Unknown"))
        title = article.get("title", "")
        summary = article.get("summary", "")
        published_at = parse_av_time(article.get("time_published", ""))
        for ts in article.get("ticker_sentiment", []):
            ticker = (ts.get("ticker") or "").upper().strip()
            if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,7}", ticker):
                continue
            try:
                relevance = float(ts.get("relevance_score", 0))
                sentiment = float(ts.get("ticker_sentiment_score", 0))
            except Exception:
                relevance, sentiment = 0, 0
            if relevance < 0.15:
                continue
            stories.append({
                "ticker": ticker,
                "company_name": "",
                "source": source,
                "title": title,
                "summary": safe_summary(summary),
                "url": article.get("url", ""),
                "published_at": published_at,
                "sentiment": sentiment,
                "evidence_type": "Professional reporting",
                "fingerprint": story_fingerprint(title),
                "relevance": relevance,
            })
    return stories

def fetch_finnhub_news(ticker: str) -> list[dict]:
    if not FINNHUB_KEY:
        return []
    from_day = (TODAY - dt.timedelta(days=3)).isoformat()
    url = "https://finnhub.io/api/v1/company-news?" + urllib.parse.urlencode({
        "symbol": ticker, "from": from_day, "to": TODAY.isoformat(), "token": FINNHUB_KEY
    })
    try:
        rows = http_json(url)
    except Exception:
        return []
    stories = []
    for row in rows[:30]:
        title = row.get("headline", "")
        stories.append({
            "ticker": ticker,
            "company_name": "",
            "source": normalize_source(row.get("source", "Finnhub")),
            "title": title,
            "summary": safe_summary(row.get("summary", "")),
            "url": row.get("url", ""),
            "published_at": iso_from_epoch(row.get("datetime")),
            "sentiment": 0.0,
            "evidence_type": "Professional reporting",
            "fingerprint": story_fingerprint(title),
        })
    return stories

def dedupe_stories(stories: list[dict]) -> list[dict]:
    best = {}
    for s in stories:
        key = (s["ticker"], s["fingerprint"])
        existing = best.get(key)
        if not existing:
            best[key] = s
            continue
        # SEC primary evidence wins; otherwise higher-quality source wins.
        rank = (1 if s["evidence_type"] == "SEC filing" else 0, source_quality(s["source"]))
        old_rank = (1 if existing["evidence_type"] == "SEC filing" else 0, source_quality(existing["source"]))
        if rank > old_rank:
            best[key] = s
    return list(best.values())

def score_company(ticker: str, stories: list[dict], baseline: float, company_name: str = "") -> dict:
    stories = sorted(stories, key=lambda s: s.get("published_at",""), reverse=True)
    now_minus_24 = NOW - dt.timedelta(hours=24)
    recent24 = []
    for s in stories:
        try:
            published = dt.datetime.fromisoformat(s["published_at"].replace("Z","+00:00"))
        except Exception:
            published = NOW
        if published >= now_minus_24:
            recent24.append(s)

    primary_count = sum(s["evidence_type"] == "SEC filing" for s in stories)
    independent_sources = len({normalize_source(s["source"]) for s in stories if s["source"]})
    unique_clusters = len({s["fingerprint"] for s in stories})
    current_count = len(recent24)

    # 25: primary evidence
    primary_evidence = 25 if primary_count else 0

    # 20: unusual coverage relative to 15-day history.
    # A new ticker with >=3 credible items still gets substantial discovery credit.
    if baseline <= 0:
        accel_ratio = float(current_count) if current_count else 0
        coverage_accel = min(20, current_count * 5)
    else:
        accel_ratio = current_count / max(0.5, baseline)
        coverage_accel = min(20, max(0, 8 * math.log2(max(1, accel_ratio))))

    # 20: strongest material catalyst among unique stories.
    catalyst_strength = max([catalyst_score(s["title"] + " " + s.get("summary","")) for s in stories] or [0])

    # 15: independent corroboration, capped.
    corroboration = min(15, max(0, (independent_sources - 1) * 5))

    # 10: best sources + breadth.
    source_scores = sorted({source_quality(s["source"]) for s in stories}, reverse=True)
    source_quality_score = min(10, round((sum(source_scores[:3]) / max(1, len(source_scores[:3]))), 1)) if source_scores else 0

    # 10: direction strength only; neutral remains 5, not 0.
    sentiments = [float(s.get("sentiment",0)) for s in stories if abs(float(s.get("sentiment",0))) > .001]
    avg_sent = statistics.mean(sentiments) if sentiments else 0
    sentiment_signal = min(10, 5 + abs(avg_sent) * 5)

    raw = primary_evidence + coverage_accel + catalyst_strength + corroboration + source_quality_score + sentiment_signal
    score = min(100, round(raw, 1))

    if avg_sent > .15:
        sentiment_label = "Positive"
    elif avg_sent < -.15:
        sentiment_label = "Negative"
    else:
        sentiment_label = "Mixed / neutral"

    if baseline <= 0 and current_count:
        acceleration_label = "New signal"
    elif accel_ratio >= 4:
        acceleration_label = "Surging"
    elif accel_ratio >= 2:
        acceleration_label = "Rising quickly"
    elif accel_ratio > 1:
        acceleration_label = "Above baseline"
    else:
        acceleration_label = "Normal"

    top_stories = sorted(
        stories,
        key=lambda s: (
            1 if s["evidence_type"] == "SEC filing" else 0,
            source_quality(s["source"]),
            s["published_at"],
        ),
        reverse=True,
    )[:6]

    name = company_name or next((s.get("company_name") for s in stories if s.get("company_name")), "")
    catalyst = choose_catalyst(stories)
    why = (
        f"{unique_clusters} unique credible information item{'s' if unique_clusters != 1 else ''} "
        f"from {independent_sources} source{'s' if independent_sources != 1 else ''}. "
        f"{'A recent SEC filing provides primary evidence. ' if primary_count else ''}"
        f"Coverage is {acceleration_label.lower()} relative to the stored baseline."
    )

    return {
        "ticker": ticker,
        "company_name": name,
        "signal_score": score,
        "primary_catalyst": catalyst,
        "why_it_matters": why,
        "sentiment_label": sentiment_label,
        "coverage_acceleration_label": acceleration_label,
        "article_count_24h": current_count,
        "latest_event_at": stories[0]["published_at"] if stories else NOW.isoformat(),
        "evidence": {
            "primary_source_count": primary_count,
            "independent_sources": independent_sources,
            "unique_story_clusters": unique_clusters,
        },
        "metrics": {
            "primary_evidence": primary_evidence,
            "coverage_acceleration": round(coverage_accel,1),
            "catalyst_strength": catalyst_strength,
            "corroboration": corroboration,
            "source_quality": source_quality_score,
            "sentiment_signal": round(sentiment_signal,1),
            "coverage_ratio_vs_baseline": round(accel_ratio,2),
        },
        "stories": top_stories,
    }

def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    history = load_history()

    all_stories = []
    ticker_names: dict[str,str] = {}

    # SEC is intentionally first: primary evidence.
    if SEC_USER_AGENT:
        try:
            secmap = sec_ticker_map()
            secstories = fetch_sec_8k(secmap)
            all_stories.extend(secstories)
            for s in secstories:
                if s.get("company_name"):
                    ticker_names[s["ticker"]] = s["company_name"]
        except Exception as exc:
            print(f"SEC collection warning: {exc}")
    else:
        print("SEC_USER_AGENT not set; SEC source skipped.")

    if ALPHA_KEY:
        try:
            all_stories.extend(fetch_alpha_news())
        except Exception as exc:
            print(f"Alpha Vantage collection warning: {exc}")
    else:
        print("ALPHA_VANTAGE_API_KEY not set; Alpha Vantage source skipped.")

    # First pass ranks discovery candidates. Finnhub only enriches those candidates
    # so the free API is not wasted on thousands of symbols.
    grouped = collections.defaultdict(list)
    for s in dedupe_stories(all_stories):
        grouped[s["ticker"]].append(s)

    preliminary = []
    for ticker, stories in grouped.items():
        preliminary.append(score_company(ticker, stories, baseline_for(history, ticker), ticker_names.get(ticker,"")))
    preliminary.sort(key=lambda x: x["signal_score"], reverse=True)

    candidates = [x["ticker"] for x in preliminary[:MAX_COMPANIES]]
    if FINNHUB_KEY:
        for idx, ticker in enumerate(candidates):
            try:
                all_stories.extend(fetch_finnhub_news(ticker))
                # Gentle pacing; remove/adjust only if your account limits permit it.
                time.sleep(1.05)
            except Exception as exc:
                print(f"Finnhub warning for {ticker}: {exc}")

    grouped = collections.defaultdict(list)
    for s in dedupe_stories(all_stories):
        grouped[s["ticker"]].append(s)

    companies = []
    today_counts = {}
    for ticker, stories in grouped.items():
        count24 = 0
        for s in stories:
            try:
                p = dt.datetime.fromisoformat(s["published_at"].replace("Z","+00:00"))
                if p >= NOW - dt.timedelta(hours=24):
                    count24 += 1
            except Exception:
                pass
        today_counts[ticker] = count24
        companies.append(score_company(ticker, stories, baseline_for(history, ticker), ticker_names.get(ticker,"")))

    companies.sort(key=lambda x: x["signal_score"], reverse=True)
    companies = companies[:MAX_COMPANIES]

    output = {
        "meta": {
            "generated_at": NOW.isoformat(),
            "companies_scanned": len(grouped),
            "sources_enabled": {
                "sec_edgar": bool(SEC_USER_AGENT),
                "alpha_vantage": bool(ALPHA_KEY),
                "finnhub": bool(FINNHUB_KEY),
            },
            "model_version": "1.0",
        },
        "companies": companies,
    }
    OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    save_history(history, today_counts)
    print(f"Wrote {OUT} with {len(companies)} ranked companies.")

if __name__ == "__main__":
    main()
