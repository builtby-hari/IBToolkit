# Testing

Tests run locally with pytest. No CI, no GitHub Actions. Tests never hit the network: API responses and public files are stored as fixtures in `data/sample/`.

## Test Layers

| Layer | What It Covers |
|---|---|
| Unit | One function at a time, with hand-checked inputs and outputs |
| Golden | The worked example in METHODOLOGY.md, numbers checked to within $1 |
| Fixture integration | Paste and CSV inputs through the full pipeline, with expected ranked output |
| Contract | Shape of FRED and Census responses, using saved sample payloads |
| Property | Monotonicity checks (higher price means lower DSCR, higher discount rate means lower DCF) |

## Unit Tests per Module

| Test File | Module | Key Cases |
|---|---|---|
| `test_config.py` | `config.py` | Missing file, bad percent, weights not summing to 100, blank key allowed |
| `test_models.py` | `models.py` | Required fields, negative price rejected, unknown category rejected |
| `test_ingest.py` | `ingest.py` | Paste with $ and commas, CSV with BOM, quoted commas, missing header, duplicate listing ref |
| `test_normalize.py` | `normalize.py` | SDE from golden example, add-back cap, negative pre-tax income, zero income divide guard |
| `test_multiples.py` | `multiples.py` | Midpoint vs low end, unknown category error, zero earnings guard |
| `test_dcf.py` | `dcf.py` | Golden DCF value, r equal to g raises, zero growth, tax on negative EBIT floors at zero |
| `test_sba.py` | `sba.py` | Equity injection rule, over-$5M loans rejected with the equity needed, spread bands at the SOP boundaries ($50k, $250k, $350k), PMT golden value, DSCR both views |
| `test_fred.py` | `fred.py` | Parse DPRIME observation, missing value ".", maintenance page and stale observation raise, fresh data returns rate and date |
| `test_census_cbp.py` | `census_cbp.py` | Suppressed cell handled as missing, county FIPS format, year range |
| `test_tx_context.py` | `tx_context.py` | Comptroller file columns, TABC county count, encoding |
| `test_red_flags.py` | `red_flags.py` | Each rule on and off, evidence text present, severity values |
| `test_scoring.py` | `scoring.py` | Weights sum, component mapping endpoints, penalty cap, tie break on price |
| `test_storage.py` | `storage.py` | Upsert keeps first_seen, snapshot added on price change, foreign keys |
| `test_report.py` | `report.py` | Markdown sections present, Telegram text under length limit |
| `test_alerts.py` | `alerts.py` | Dedupe, retry count, no full statements in message |
| `test_cli.py` | `cli.py` | Help text, exit codes on hard failure, dry-run writes nothing |

## Fixture Data

- `data/sample/listing_gas_station_paste.txt`: one invented paste, matches the worked example
- `data/sample/listings_mixed.csv`: 12 invented listings across four categories, including one with missing financials and one with a price drop
- `data/sample/fred_dprime.json`: saved DPRIME payload with one "." missing value
- `data/sample/fred_dgs10.json`: saved DGS10 payload
- `data/sample/census_cbp_447_48113.json`: saved CBP response, one suppressed cell
- `data/sample/comptroller_sample.csv`: small invented sales tax extract
- `data/sample/tabc_sample.csv`: small invented permit extract

All fixture names and numbers are invented. Do not copy real listing text, seller names or broker contacts into fixtures.

## Edge Cases List

- Listing with pre-tax income of zero or negative (SDE still computed, DSCR marked not meaningful)
- Add-backs larger than pre-tax income (ratio above 1.0, flag fires)
- Asking price missing (listing rejected with reason)
- Revenue given but no cash flow (SDE and EBITDA marked missing, data quality reduced)
- Two years of financials only (CAGR not computed, trend component scores 0 and the report notes it)
- Prime rate change between two runs (sba debt run stores the rate used)
- Discount rate equal to terminal growth (DCF refuses to run)
- DSCR exactly 1.25 (passes lender test, boundary check)
- Loan exactly $350,000 (spread band boundary)
- County with no CBP data (market context component dropped, weights rescaled, report notes it was not scored)
- Category not in config (rejected, not guessed)
- Currency strings with $, commas and parentheses for negatives
- Listing text with Unicode dashes or non-breaking spaces

## Running Tests

```text
python -m pytest tests -q
```

Each test file must pass with no network and no `.env` file present.
