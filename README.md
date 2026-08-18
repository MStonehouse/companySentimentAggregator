# Company Signal

A free-first GitHub Pages dashboard for discovering publicly traded companies that are experiencing an unusual increase in **credible, company-specific information**.

This project deliberately excludes social-media popularity from its score.

## What it uses

- **SEC EDGAR** — primary evidence from recent 8-K filings.
- **Alpha Vantage NEWS_SENTIMENT** — broad financial-news discovery, ticker relevance and sentiment.
- **Finnhub Company News** — optional enrichment for the highest-ranked discovered tickers.
- **Local history** — stores recent daily article counts to estimate coverage acceleration.

The site is static. API keys never enter the browser. GitHub Actions reads them from repository secrets, writes `data/signals.json`, and GitHub Pages serves only the finished JSON.

## Signal Score (0–100)

| Component | Max |
|---|---:|
| Primary evidence | 25 |
| Coverage acceleration | 20 |
| Catalyst strength | 20 |
| Independent corroboration | 15 |
| Source quality | 10 |
| Sentiment signal | 10 |

This is intentionally transparent and easy to change in `scripts/update_signals.py`.

## Setup

### 1. Create a new GitHub repository

Upload the entire contents of this folder **without adding another enclosing folder**. Your repository root should contain:

```text
index.html
styles.css
app.js
README.md
data/
scripts/
.github/
```

### 2. Add GitHub repository secrets

Go to:

**Settings → Secrets and variables → Actions → New repository secret**

Add:

#### `SEC_USER_AGENT`

The SEC requests that automated clients identify themselves. Use an app name and an email address you control, for example:

```text
CompanySignal your-email@example.com
```

This is not an SEC API key.

#### `ALPHA_VANTAGE_API_KEY`

Create a free Alpha Vantage key and paste only the key value.

#### `FINNHUB_API_KEY`

Create a free Finnhub key and paste only the key value.

You can omit Alpha Vantage or Finnhub and the updater will still run with whatever sources are enabled. For meaningful discovery, Alpha Vantage is strongly recommended.

### 3. Run the workflow manually once

Open:

**Actions → Update company signals → Run workflow**

When it succeeds, `data/signals.json` and `data/history.json` will be updated.

### 4. Enable GitHub Pages

Open:

**Settings → Pages**

Under **Build and deployment**:

- Source: **Deploy from a branch**
- Branch: **main**
- Folder: **/(root)**

Save.

### 5. Scheduled updates

The included GitHub Action runs four times per day. You can change the cron schedule in:

```text
.github/workflows/update-signals.yml
```

GitHub Actions cron uses UTC.

## Important design choices

### No direct scraping of major news websites

The updater does not scrape Reuters, Bloomberg, WSJ, etc. directly. Professional reporting can enter through data providers such as Alpha Vantage and Finnhub. This avoids building the project around brittle HTML scraping or bypassing publisher access controls.

### Duplicate-story clustering

The updater fingerprints similar headlines and keeps the strongest representative source. This is intentionally conservative: 20 websites repeating one story should not count as 20 independent confirmations.

### SEC first

A recent material 8-K can contribute up to 25 points because it is primary evidence. Company press releases are not automatically treated as independent corroboration.

### Free tier discipline

Finnhub is used only on the top candidates found in the first pass. That makes much better use of limited free requests than querying every listed stock.

## Local test

You can preview the website without installing anything:

```bash
python -m http.server 8000
```

Then visit:

```text
http://localhost:8000
```

To run the updater locally on Linux/macOS:

```bash
export SEC_USER_AGENT="CompanySignal your-email@example.com"
export ALPHA_VANTAGE_API_KEY="your_key"
export FINNHUB_API_KEY="your_key"
python scripts/update_signals.py
```

## Files

```text
company_signal/
├── index.html
├── styles.css
├── app.js
├── README.md
├── data/
│   ├── signals.json
│   └── history.json
├── scripts/
│   └── update_signals.py
└── .github/
    └── workflows/
        └── update-signals.yml
```

## Caveats

- A high Signal Score is **not** a buy recommendation.
- A company can rank highly because of significant negative news.
- News APIs may change free-tier quotas or licensing.
- Source names reported by aggregators are not always perfectly normalized.
- The current catalyst classifier is deliberately simple and explainable; it can later be replaced with a stronger model while preserving the same data structure.

## Version 2: Market Leaders + Emerging Signals

The dashboard now maintains two rankings from the same vetted evidence:

- **Market Leaders** use `signal_score` (0–100) to rank the absolute strength of credible company-specific attention.
- **Emerging Signals** use `discovery_score` (0–100) to rank attention that is unusual relative to each company's own stored baseline.

### Discovery Score

| Component | Max |
|---|---:|
| Attention lift vs. baseline | 35 |
| Novelty / normally quiet coverage | 20 |
| Independent source breadth | 15 |
| Catalyst strength | 15 |
| Primary evidence | 10 |
| Sentiment strength | 5 |

`data/history.json` builds the baseline over time. Discovery Scores are marked as provisional until at least 7 prior days of history are available. The updater also uses the SEC ticker map to fill in company names for tickers discovered through the news APIs whenever possible.
