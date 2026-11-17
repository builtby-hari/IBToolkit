# Changelog

## 1.0.0 (2026-11-17)

First tagged release.

- Models: DCF, trading comps, precedent deals, LBO, debt capacity, bank valuation and bank merger, each writing an Excel workbook with live formulas.
- Real-deal check: the Eastern Bankshares / HarborOne merger rebuilt from public filings.
- Filing intake: draft case files from SEC XBRL data or a 10-K PDF, every number sourced, gaps left as TODO.
- Fix: the pitch page code now runs on Python 3.11, as the README says. It used f-string syntax that needed 3.12.
- Tests run on GitHub Actions for every push and pull request.
- Contributing guide and issue templates.
