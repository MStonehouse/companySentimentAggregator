# Company Signal v3

Company Signal is a free-first, evidence-focused GitHub Pages dashboard for answering four questions:

1. **Who are the established market leaders receiving the strongest credible attention?**
2. **Which companies are receiving unusually more attention than is normal for them?**
3. **What materially changed since the previous period?**
4. **Which sectors and themes are beginning to cluster across multiple companies?**

The project deliberately excludes social-media popularity from its scoring model.

## What v3 adds

- Market Leaders and Emerging Signals as separate rankings.
- Catalyst classification (contracts, earnings, M&A, FDA, financing, product/technology, etc.).
- Confidence Score separate from Signal/Discovery scores.
- Cached company fundamentals and industry context.
- Automated materiality estimate when a monetary event value can be extracted.
- 30-day Signal and Discovery history.
- New-to-radar, accelerating and cooling states.
- Sector activity map.
- Cross-company theme detection.
- Daily intelligence briefing: new emerging, accelerating, cooling, major catalysts and names leaving the emerging top 20.
- Browser-local watchlist with no account/database.
- Filters by industry and catalyst category.

## Data sources

### SEC EDGAR
Primary evidence from recent 8-K filings plus a canonical ticker/company-name map.

### Alpha Vantage
`NEWS_SENTIMENT` is the broad discovery layer for company-related financial reporting, ticker relevance and article sentiment.

### Finnhub
Company News enriches shortlisted names. Company Profile 2 and Basic Financials provide cached company context such as industry, market capitalization and selected financial ratios/metrics.

The browser never receives any API key. GitHub Actions reads secrets, processes the information and commits only JSON output.

## Scoring

### Signal Score — 0 to 100

| Component | Max |
|---|---:|
| Primary evidence | 25 |
| Coverage acceleration | 20 |
| Catalyst strength | 20 |
| Corroboration | 15 |
| Source quality | 10 |
| Sentiment signal | 10 |

Signal Score answers: **How strong and well-supported is the current company information signal?**

### Discovery Score — 0 to 100

| Component | Max |
|---|---:|
| Attention lift | 35 |
| Novelty | 20 |
| Source breadth | 15 |
| Catalyst strength | 15 |
| Primary evidence | 10 |
| Sentiment | 5 |

Discovery Score answers: **How unusual is the current attention for this particular company?**

### Confidence Score — 0 to 100

Confidence is deliberately separate. It rewards primary evidence, independent corroboration, source quality and unique story clusters. A negative development can have very high confidence.

### Materiality

When an article about a contract, acquisition, financing, government award or similar event contains an extractable dollar value, Company Signal compares that amount with cached market capitalization.

This is an **automated context estimate, not a verified financial calculation**. The UI labels it accordingly and tells the user to verify the original source.

## Repository structure

```text
company_signal/
├── index.html
├── styles.css
├── app.js
├── README.md
├── data/
│   ├── signals.json
│   ├── history.json
│   └── fundamentals_cache.json
├── scripts/
│   └── update_signals.py
└── .github/
    └── workflows/
        └── update-signals.yml
```

## GitHub Secrets

Go to **Settings → Secrets and variables → Actions** and add:

```text
SEC_USER_AGENT
ALPHA_VANTAGE_API_KEY
FINNHUB_API_KEY
```

`SEC_USER_AGENT` is an identifier, not an API key. Use an application name plus an email address you control, for example:

```text
CompanySignal your-email@example.com
```

## Scheduled updater

The included workflow runs four times per day and can also be run manually:

**Actions → Update company signals → Run workflow**

The workflow commits:

```text
data/signals.json
data/history.json
data/fundamentals_cache.json
```

The fundamentals cache matters: it prevents the app from repeatedly querying the same company profile/financial metrics on every scheduled run. Cached fundamentals are refreshed after seven days when the company is shortlisted again.

## History and baseline behavior

`history.json` stores:

- Daily 24-hour article counts.
- Daily Signal/Discovery score snapshots.
- Daily top rankings.
- First-seen dates.

The Emerging model works immediately, but it labels the baseline as **building** until at least seven prior days are available. The 30-day history charts populate automatically over time.

## Watchlist

The watchlist uses browser `localStorage`. Nothing is transmitted anywhere and no account is required. Because it is browser-local, a watchlist on one phone/computer will not automatically appear on another device.

## Updating from your local Git repo

Because GitHub Actions commits data back to `main`, pull before pushing code changes:

```bash
git pull --rebase origin main
```

Then:

```bash
git add .
git commit -m "Describe your change"
git push origin main
```

Avoid force-pushing merely because the Action has added newer data commits.

## Local preview

```bash
python -m http.server 8000
```

Then open:

```text
http://localhost:8000
```

To run the updater locally:

```bash
export SEC_USER_AGENT="CompanySignal your-email@example.com"
export ALPHA_VANTAGE_API_KEY="your_key"
export FINNHUB_API_KEY="your_key"
python scripts/update_signals.py
```

## Important caveats

- A high score is not a buy recommendation.
- High-confidence news can be strongly negative.
- Automated catalyst/theme classification is deliberately transparent and rule-based, so occasional misclassification is possible.
- Monetary materiality extraction can misinterpret context; verify the original article/filing.
- Free API quotas and endpoint availability can change over time.
- Fundamentals are cached and therefore will not necessarily reflect changes made within the cache window.
