# Stock Behaviour Analyzer: Project Context

Last updated: 16 Nov 2026

## 0. Goal
Find stocks whose price has risen steadily for about 5 months, using price behaviour only. Explain why each was picked. Later: notify a configured group by WhatsApp text and voice, run by agents locally or in the cloud. Markets: NSE now, US next (keep everything market-agnostic).

## 1. Scope decision (current)
- **In scope:** price-based screening only (OHLCV history, derived trend features).
- **Parked, not lost:** DII-buying impact model, promoter-integrity model, shareholding/pledge data, bulk/block deals, insider trades, announcements/events (see section 9).
- Fundamentals (market cap, PE, sector) are optional context tags and never used for selection.

## 2. Naming and stack
- Repo: `stock-behaviour-analyzer`, Python package: `sba` (src layout), CLI command: `sba`.
- Python 3.10+, pandas, numpy, pyarrow, pydantic, pyyaml, yfinance (free, no login). pytest + pytest-cov (>= 95% coverage enforced).
- No scraping of screener.in. Data comes from yfinance (symbol + market suffix, `.NS` for NSE, none for US).

## 3. Engineering rules (agreed)
- Everything configurable via YAML (`config/`): app, sources, markets, screen thresholds, universe files. Secrets only in `.env`, never committed.
- Every class and method has a docstring.
- Every method is wrapped by the `@logged` decorator: logs enter/exit with summarised inputs/outputs and duration, logs and re-raises errors. Not applied to logging infrastructure itself (avoids recursion).
- Logs are JSON lines (schema v1) for future agent analysis: schema, ts, level, run_id, logger, message, function, event (enter|exit|error), inputs, output, duration_ms, error_type, error. Secrets masked, DataFrames logged as shape only.
- Tests: 95% coverage gate, no network in tests (providers mocked).
- Errors: typed hierarchy under `SBAError` (ConfigError, DataFetchError, StorageError, FeatureError).

## 4. Architecture
```
config/ (app, sources, markets, screen, universe/*.yaml)
src/sba/
  cli.py          sba fetch | features | run  --universe X [--symbol S] [--config path]
  service.py      AnalysisService: fetch(), compute(), run_universe()
  providers/      PriceProvider interface + yfinance adapter (normalised schema)
  storage/        StorageBackend interface; SQLite (primary), Parquet (mirror), Composite
  features.py     compute_features(): derived columns, rolling trend metrics, passes_screen
  exports.py      CSV export of the full per-stock dataset
  config.py       pydantic models + loaders
  logging_utils.py  JSON logging + @logged
tests/            pytest suite
```
- Storage is behind an interface. Postgres can be added later as another backend (one new file + one line in `build_storage`).
- Re-running a phase overwrites that stock's prices, features and CSV (idempotent). Fundamentals are overwritten too (history of snapshots is a parked item).
- Exit codes: 0 ok, 1 some stocks failed, 2 config/domain error, 3 unexpected error. JSON report on stdout, logs on stderr and in file.

## 5. Where data lands (relative to the folder you run from; run from project root)
| What | Location |
|---|---|
| SQLite DB (primary) | `data/sba.db` (tables: `prices`, `fundamentals`, and `features_<market>_<symbol>` after `sba features`) |
| Parquet mirror | `data/parquet/<MARKET>/<SYMBOL>_prices.parquet`, `_features.parquet`, `_fundamentals.json` |
| Full CSV per stock | `data/exports/<MARKET>/<SYMBOL>_full.csv` |
| Logs | `logs/sba.log` |
`data/` and `logs/` are git-ignored.

Viewing data: `sqlite3 -header -column data/sba.db "..."`, DB Browser for SQLite (installed), pandas for Parquet.

## 6. Screening rules ("increasing for five months")
Computed per day over a rolling window (`config/screen.yaml`):
- **Total return** over 105 trading days >= 50%.
- **Trend smoothness:** R-squared of a straight-line fit to log(price) >= 0.85. Log scale because steady growth is a constant percentage gain, which is a straight line on a log chart. R-squared is the share of price movement explained by that line (1 = smooth climb, 0 = choppy/sideways). The slope is the average compound daily growth rate.
- **Consistency:** at least 4 of 5 monthly (21-day) closes higher than the prior month.
- **Max drawdown** inside the window <= 20%.
- **Trend health:** close above 50-day average and 50-day above 100-day.
- **Liquidity:** median traded value (close x volume, 63 days) >= 1 crore INR (needs a per-market override for US).
- Not yet built: ASM/GSM surveillance exclusion, ranking score (slope x R-squared).

## 7. Progress
| Step | Deliverable | Status |
|---|---|---|
| 1 | Config-driven skeleton, single-stock history to SQLite + Parquet, features, CSV | Done and checked in. Fetch verified on CENTUM. |
| 2 | Multi-stock `sba screen`: ranked output, per-rule pass/fail reasons, `--as-of` date, forward returns | Next |
| 3 | Backtest and threshold tuning (go/no-go gate) | Planned |
| 4 | Daily D-1 incremental job, `runs` table | Planned |
| 5 | Agent/LLM layer | Planned |
| 6 | WhatsApp text and voice | Last |

## 8. Findings so far
- **Test date correction:** the Centum example (about Rs 550 in March 2022 to Rs 1622) was initially checked against Sept 2022. In Sept 2022 Centum closed around Rs 450-550, with 105-day return -8% to +14%, R-squared near 0 and drawdown 15-24%. The screen correctly rejected it. The Rs 1622 level must come from a later date (likely 2025). Next check: find the real rally period with these queries and see whether `passes_screen` fired and which rule limited it:
```bash
sqlite3 -header -column data/sba.db "select date, round(close,1) close from features_nse_centum order by close desc limit 1;"
sqlite3 -header -column data/sba.db "select substr(date,1,7) month, round(max(close),0) high, round(avg(rolling_r2),2) avg_r2 from features_nse_centum group by month order by month;"
sqlite3 -header -column data/sba.db "select count(*) days_passed, min(date) first_pass, max(date) last_pass from features_nse_centum where passes_screen=1;"
```
- Window-based screens lag: with a 105-day window the signal fires only after about 5 months of climb exist.
- yfinance fundamentals are a current snapshot only (no history; ROCE, face value, promoter holding not available). Some fields may be null for small Indian stocks.

## 9. Parked ideas (revisit after the price screen is validated)
- **DII-buying impact:** needs quarterly shareholding (DII/FII/MF/promoter %), bulk/block deals, delivery %. Stock-level DII data is quarterly and late; daily DII data is market-wide only. Must control for prior momentum (DII often buys after a rise).
- **Promoter integrity:** proxies are pledge %, promoter/insider trades, auditor exits, delayed results, SEBI orders, ASM/GSM, related-party items, profit vs cash-flow divergence. Needs a labelled event list; start with a transparent risk-flag score before any ML.
- **Point-in-time rule for any non-price data:** store `period_end` and `announced_on`, append snapshots, never overwrite, so models never use data before it was public.
- Proposed future tables: fundamentals_quarterly, shareholding_quarterly, deals, insider_trades, corporate_actions, events, snapshots_fundamental, labels.
- Known bias: free sources exclude delisted stocks, so backtests are optimistic.
- US equivalents: SEC EDGAR (13F holdings, Form 4 insiders, XBRL financials).

## 10. Where LLM and ML fit
Principle: deterministic code computes and selects, the LLM interprets.
- No LLM: data fetching, features, screening, backtesting.
- LLM: explain a pick in plain English from its feature row, write the WhatsApp message and voice script, monitor logs for anomalies (agent-readable log format), later summarise news/results and tag events.
- ML (phase 2, optional): gradient boosting on logged picks and outcomes (continue vs reverse) once enough history exists.
- Guardrails: the LLM never invents numbers (only quotes fields it is given), every message carries a not-investment-advice line, agents may propose config changes but a human approves them.

## 11. How to run
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
sba run --universe centum_test           # fetch + features
sba fetch --universe centum_test         # phase 1 only
sba features --universe centum_test      # phase 2 only
```

## 12. Open questions
- Universe for Step 2: 15-20 NSE symbols including known past winners and flat/falling controls (user list or drafted list).
- Per-market liquidity threshold (INR vs USD).
- Backtest horizon (5 years assumed).
- WhatsApp provider (Meta Cloud API vs Twilio), only needed at the last step.
- Add a switch to disable fundamentals fetching, since selection is price-only?
