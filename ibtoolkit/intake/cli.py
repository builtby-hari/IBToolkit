"""The `intake` command: EDGAR to a draft case, and the review step."""
import json
import sys
import urllib.request
from pathlib import Path

from .. import edgar
from . import draft, pdf, review, xbrl


def add_parser(sub):
    """Register `intake` on the main CLI."""
    q = sub.add_parser("intake", help="Draft a case file from SEC filings (--ticker), or review one (--review)")
    q.add_argument("--ticker", help="Ticker to pull from SEC EDGAR (needs SEC_USER_AGENT), e.g. HD")
    q.add_argument("--pdf", metavar="FILE.pdf", help="Draft from a 10-K or 10-Q PDF instead of SEC XBRL (needs pdfplumber)")
    q.add_argument("--model", choices=["dcf"], default="dcf", help="Which case to draft (default dcf)")
    q.add_argument("--out", help="Draft file to write (default cases/draft_<ticker>_<model>.toml)")
    q.add_argument("--facts", metavar="FILE.json", help="Use a saved companyfacts JSON instead of calling the SEC")
    q.add_argument("--force", action="store_true", help="Overwrite --out if it exists")
    q.add_argument("--review", metavar="DRAFT.toml", help="Print the review table for a draft case")
    q.add_argument("--approve", action="store_true", help="With --review: set draft = false if clean")
    q.add_argument("--accept-flags", action="store_true", help="With --approve: accept unresolved flags")
    return q


def _err(msg):
    print(f"Error: {msg}", file=sys.stderr)
    return 1


def run(a, opener=urllib.request.urlopen):
    """Dispatch the intake command. The opener is injected so tests never touch the network."""
    if a.approve and not a.review:
        return _err("--approve needs --review <draft file>")
    try:
        if a.review:
            return _review(a)
        if a.ticker or a.facts or a.pdf:
            return _draft(a, opener)
    except (OSError, ValueError, edgar.EdgarError, xbrl.XbrlError, pdf.PdfIntakeError) as e:
        return _err(e)
    return _err("give --ticker, --facts or --pdf to draft a case, or --review <draft file>")


def _review(a):
    rep = review.review(a.review)
    print(review.format_report(rep))
    if a.approve:
        ok, msg = review.approve(a.review, a.accept_flags)
        print(("\n" if ok else "\n") + msg)
        return 0 if ok else 1
    return 0


def _draft(a, opener):
    if a.pdf:
        return _draft_pdf(a)
    if a.facts:
        facts = json.loads(Path(a.facts).read_text())
        cik = str(facts.get("cik", ""))
    else:
        cik = xbrl.cik_for_ticker(a.ticker, xbrl.load_tickers(opener))
        facts = edgar.fetch_companyfacts(cik, opener)
    ticker = (a.ticker or "").upper()
    values = xbrl.extract(facts)
    if not any(v.field == "revenue" for v in values):
        raise ValueError("no revenue found in these company facts; is this a 10-K filer?")
    return _write(a, values, facts.get("entityName", ticker), ticker, cik,
                  f"{facts.get('entityName')}, CIK {cik}", (ticker or 'cik' + cik).lower())


def _draft_pdf(a):
    path = Path(a.pdf)
    if not path.is_file():
        raise ValueError(f"PDF not found: {path}")
    values = pdf.extract(path)
    if not any(v.field == "revenue" for v in values):
        raise ValueError("no revenue found in this PDF; is it a 10-K or 10-Q with an income statement?")
    ticker = (a.ticker or "").upper()
    name = ticker or path.stem
    return _write(a, values, name, ticker, "", f"from {path.name}", name.lower())


def _write(a, values, entity, ticker, cik, label, stem):
    out = Path(a.out or f"cases/draft_{stem}_{a.model}.toml")
    if out.exists() and not a.force:
        raise ValueError(f"{out} already exists (it may hold hand edits); pass --force to overwrite")
    text = draft.build_draft(values, entity, ticker, cik)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    sel = draft.select(values)
    todos = review.todo_lines(text)
    print(f"Wrote {out} ({label})")
    print(f"{len(sel)} sourced values, {len(todos)} TODO items, {sum(v.status == 'flag' for v in sel.values())} flagged")
    print(f"Next: python -m ibtoolkit intake --review {out}")
    return 0
