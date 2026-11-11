# Data Sources

Only legal, free or public sources go in the core plan. Anything that forbids scraping is listed with the compliant method used instead.

| Source | What It Gives | Access Method | Cost | Rate Limits | Terms Notes |
|---|---|---|---|---|---|
| BizBuySell (listing site) | Asking price, revenue, cash flow, category, county, listing text | Manual paste of the listing text or a CSV the user fills in. The tool never fetches pages. | Free to view | Not applicable | Terms of use forbid scraping and automated collection. The compliant route is manual copy or the site's own email alerts forwarded by the user. Verify terms at the time of use. |
| BizQuest and similar broker sites | Same type of listing fields | Manual paste or CSV, same rules as above | Free to view | Not applicable | Same no-scraping rule applies. Treat as paste only. |
| Broker-provided packages (CIM or teaser PDFs) | Full financial summaries, add-back schedules, lease terms | Manual file drop into `data/raw/inbox/`, text extracted by hand or by the user | Free if received | Not applicable | Confidential. Keep local, never commit, follow any NDA. |
| FRED (St. Louis Fed) | DPRIME (Bank Prime Loan Rate), DGS10 (10-Year Treasury) | Public CSV endpoint (fredgraph.csv), no key | Free | Be polite: one fetch per series per run. A maintenance HTML page is treated as an error. | Data is public. Attribute the series in reports. |
| Census County Business Patterns (CBP) | Establishments, employees and annual payroll by county and NAICS | Public API, optional free key | Free | Published daily limit without key, lower than with key. Verify at build time. | Public domain U.S. government data. Suppressed cells are returned as flags. Treat them as missing. |
| Census American Community Survey (ACS) | County population and median household income | Public API, optional free key | Free | Same as CBP | Public domain. Planned for v0.3 context. |
| Texas Comptroller | Local sales tax allocation and tax-by-location context | Public downloads (CSV) from the Comptroller open data pages | Free | None, file downloads | Public record. Confirm the exact file names at build time. Monthly or quarterly lag. |
| TABC (Texas Alcoholic Beverage Commission) | Permit and license counts by county and type, including liquor store permits | Public records download and permit search export, saved locally | Free | None | Public record. Use for county counts and transfer context only. Verify the transfer process with TABC or an attorney. |
| data.texas.gov (Socrata) | Optional mirrored state datasets | Public API with optional app token | Free | Higher with app token | Same public terms as state data. |
| Texas Secretary of State business search | Entity name, status, formation date, registered agent | Public search, manual lookup per deal | Free | Manual lookup only | Public record. Used for a manual check of entity status, not bulk scraping. |

## Rules for Adding a Source

1. Must be free or public-record, or have a stated free tier that fits the plan.
2. Must allow the access method in the table. If the terms forbid automated collection, use a manual route.
3. Must record the retrieval date and source name in `context_snapshots` or `financial_periods`.
4. Must have a fixture file in `data/sample/` so tests run without network access.

## Sources Explicitly Excluded

- Any scraper for BizBuySell, BizQuest, LoopNet or similar sites
- Paid comp databases (for example, deal databases with per-seat fees), unless the owner decides to buy one
- Private seller contact data or broker contact lists beyond what the listing itself shows
