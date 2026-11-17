# Contributing

Thanks for taking a look. Bug reports, fixes and ideas are all welcome.

## Quick start

Python 3.11 or newer.

```bash
git clone https://github.com/builtby-hari/IBToolkit.git
cd IBToolkit
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt -r requirements-intake.txt && ./.venv/bin/python -m pytest -q
```

Tests run on every push and pull request, on Python 3.11 and 3.13. They need to pass before a pull request is merged.

## Ground rules

- Every input in a case file has a source or is marked as an assumption. Don't guess numbers.
- Workbooks keep live formulas. The Checks sheet and the built-in evaluator must agree with the Python engine.
- SEC requests use the `SEC_USER_AGENT` environment variable. Don't hard-code contact details.
- Add or update a test for any change to a calculation.
- Keep the README honest. If a change moves a number shown there, rerun it and update the number.

## Reporting a bug

Open an issue with the bug template. The most useful thing you can include is the exact command and a small input that shows the problem.

## Questions

Not sure if it's a bug? Ask in [Discussions](https://github.com/builtby-hari/IBToolkit/discussions).
