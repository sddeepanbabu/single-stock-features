# Stock Behaviour Analyzer

Config-driven analysis of price behaviour (steady multi-month uptrends) for NSE and US stocks.

## Setup (Python 3.10+)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                      # must report >= 95% coverage
```

## Run
```bash
sba run --universe centum_test            # fetch + features for every stock in the universe
sba fetch --universe us_test              # phase 1 only
sba features --universe centum_test --symbol CENTUM
```
Outputs: `data/sba.db` (SQLite), `data/parquet/`, `data/exports/<MARKET>/<SYMBOL>_full.csv`,
JSON report on stdout, JSON-lines logs in `logs/sba.log`.
Exit codes: 0 ok, 1 some stocks failed, 2 config/domain error, 3 unexpected error.

## Log format (one JSON object per line)
`schema, ts, level, run_id, logger, message, function, event(enter|exit|error), inputs, output, duration_ms, error_type, error`
Secrets (keys containing key/token/secret/password/auth) are masked; DataFrames are logged as shape only.
