# Scripts

Planned CLI commands and scheduled jobs. Nothing here runs yet.

## Built

- `make_figures.py`: prints the README worked example (with self-checks) and writes the PNG charts to `docs/figures/`. Run `python3 scripts/make_figures.py` from the repo root; needs matplotlib.

## Planned CLI Commands

| Command | Purpose | Key Options |
|---|---|---|
| `biz-screener import <file>` | Parse a pasted listing file or CSV into the database | `--mapping`, `--dry-run` |
| `biz-screener paste` | Read a listing from standard input, one block per listing | `--category`, `--county` |
| `biz-screener screen` | Normalize, value, check debt, run red flags and score all new or changed listings | `--since`, `--category` |
| `biz-screener rank` | Print the ranked table from the last screen | `--top`, `--min-score` |
| `biz-screener show <listing-id>` | Full breakdown for one listing: add-backs, multiples, DCF, DSCR, flags | `--json` |
| `biz-screener sensitivity <listing-id>` | Print the sensitivity grids from METHODOLOGY.md | `--grid` |
| `biz-screener context` | Refresh Census CBP and Comptroller context for configured counties | `--years`, `--offline` |
| `biz-screener report` | Write the Markdown report for the last run to the output folder | `--run-id` |
| `biz-screener alert` | Send Telegram alerts for unalerted listings above threshold | `--dry-run` |
| `biz-screener note <listing-id>` | Attach a go or no-go note and a reason to a listing | `--decision` |

## Planned Scheduled Jobs

| Job | Schedule | What It Does |
|---|---|---|
| Weekly screen | Monday 7:00 am local time (launchd) | Imports new files from `data/raw/inbox/`, runs `screen`, then `alert` |
| Weekly context refresh | Monday 6:30 am local time | Runs `context` for configured counties |
| Monthly rate check | First of the month | Runs a sensitivity check when DPRIME changes by 25 basis points or more |

## Notes

- Scheduled jobs read `.env` and write a row to the `runs` table.
- Every command supports `--dry-run` or `--offline` where it touches the network.
- Output files go to `output/`, which is git-ignored.
