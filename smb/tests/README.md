# Tests

Tests run locally with `python3 -m unittest discover -t . -s tests` or `python -m pytest tests -q`. Built so far: `test_finance.py` (normalize, multiples, DCF, SBA), `test_screening.py` (config, scoring, red flags, ingest, pipeline, CLI), `test_storage.py`, `test_report.py`, `test_fred.py` and `test_alerts.py`; the table below is the longer plan. No network or `.env` file is needed. Fixtures live in `data/sample/`.

| Planned File | Covers |
|---|---|
| `test_config.py` | Settings loading, range checks, weight sums |
| `test_models.py` | Dataclass validation for listings, periods and add-backs |
| `test_ingest.py` | Paste and CSV parsing, rejects report |
| `test_normalize.py` | SDE, EBITDA, add-back cap and ratio |
| `test_multiples.py` | Industry multiple valuation |
| `test_dcf.py` | DCF projection, terminal value, discount rate guard |
| `test_sba.py` | Equity injection, spread bands, PMT, DSCR |
| `test_fred.py` | DPRIME and DGS10 parsing, fresh data, and failure on maintenance pages or stale data |
| `test_census_cbp.py` | CBP parsing, suppressed cells, county codes |
| `test_tx_context.py` | Comptroller and TABC file readers |
| `test_red_flags.py` | Each red-flag rule on and off |
| `test_scoring.py` | Component mapping, weights, penalties, ranking |
| `test_storage.py` | SQLite upserts, snapshots, history |
| `test_report.py` | Markdown and Telegram text output |
| `test_alerts.py` | Alert dedupe and retry behavior |
| `test_cli.py` | Command dispatch, exit codes, dry run |

Full cases are in `docs/TESTING.md`.
