# Data

Data layout for the screener. Nothing private is committed.

## Folders

| Folder | Contents | Committed |
|---|---|---|
| `data/raw/` | Listing pastes, CSV exports, broker packages, and the `inbox/` drop folder | No (git-ignored) |
| `data/cache/` | FRED and Census API responses, Comptroller and TABC downloads | No (git-ignored) |
| `data/sample/` | Invented fixtures for tests and the worked example | Yes |
| `output/` | Markdown reports and rejects files | No (git-ignored) |
| `data/biz_screener.db` | SQLite history | No (git-ignored by the `data/*.db` rule) |

## Rules

- Real listing text, seller names, broker contacts and personal financials stay in `data/raw/`.
- Sample files use invented names, invented numbers and invented addresses.
- Cache files are safe to delete. The screen rebuilds them.
- Back up `data/biz_screener.db` by copying the file while no run is active.

## Sample Files (Planned)

- `sample/listing_gas_station_paste.txt`
- `sample/listings_mixed.csv`
- `sample/fred_dprime.json`
- `sample/fred_dgs10.json`
- `sample/census_cbp_447_48113.json`
- `sample/comptroller_sample.csv`
- `sample/tabc_sample.csv`
