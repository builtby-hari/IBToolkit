import argparse
import json
import sys
import tomllib

from . import (bank, bank_book, comps, csv_export, dcf, dcf_book, debtcap, debtcap_book, excel, fdic, lbo,
               lbo_book, merger, merger_book, pitch, precedents)
from .intake import cli as intake_cli


def _merger(a):
    try:
        case = merger.load_case(a.case)
        res = merger.run(case)
    except lbo.CaseError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    out = merger_book.build(case, a.out)
    y1, y2 = res["years"]
    print(f"Wrote {out}")
    print(f"Price ${res['price']:,.0f}K | P/TBV {res['p_tbv']:.2f}x | P/E {res['p_e']:.1f}x | Goodwill ${res['goodwill']:,.0f}K")
    print(f"EPS accretion Year 1 {y1['acc_pct']:.1%} | Year 2 {y2['acc_pct']:.1%}")
    eb = "not within 10 years" if res["earnback"] < 0 else f"{res['earnback']:.1f} years"
    print(f"TBV per share at close {res['tbv_dil_pct']:.1%} | Earnback {eb} | Pro forma TCE {res['pf_tce']:.2%}")
    ct, be = merger.contribution(case), merger.breakeven(case)
    saves = (f"none needed, accretive without synergies (breakeven -${-be['be_saves']:,.0f}K pre-tax)" if be["be_saves"] < 0
             else f"${be['be_saves']:,.0f}K pre-tax")
    print(f"Contribution implied exchange ratio {ct['ratio_lo']:.3f}x to {ct['ratio_hi']:.3f}x vs announced "
          f"{ct['exch_ratio']:.3f}x | Breakeven Year 1 cost saves {saves}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m ibtoolkit")
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("lbo", help="Build an LBO workbook from a case file (.toml or .json)")
    q.add_argument("case")
    q.add_argument("--out", default="output/lbo.xlsx")
    q.add_argument("--csv", metavar="DIR", help="also write every sheet as CSV values into DIR")
    q.add_argument("--pitch", metavar="FILE.html", help="also write a printable pitch book (HTML) from the evaluated workbook")
    q = sub.add_parser("merger", help="Build a bank merger workbook from a case file (.toml or .json)")
    q.add_argument("case")
    q.add_argument("--out", default="output/merger.xlsx")
    q.add_argument("--csv", metavar="DIR", help="also write every sheet as CSV values into DIR")
    q.add_argument("--pitch", metavar="FILE.html", help="also write a printable pitch book (HTML) from the evaluated workbook")
    q = sub.add_parser("dcf", help="Build a trading comps and DCF workbook from a case file (.toml or .json)")
    q.add_argument("case")
    q.add_argument("--out", default="output/dcf.xlsx")
    q.add_argument("--csv", metavar="DIR", help="also write every sheet as CSV values into DIR")
    q.add_argument("--pitch", metavar="FILE.html", help="also write a printable pitch book (HTML) from the evaluated workbook")
    q = sub.add_parser("bank", help="Build a bank valuation workbook from a case file (.toml or .json)")
    q.add_argument("case")
    q.add_argument("--out", default="output/bank.xlsx")
    q.add_argument("--csv", metavar="DIR", help="also write every sheet as CSV values into DIR")
    q.add_argument("--pitch", metavar="FILE.html", help="also write a printable pitch book (HTML) from the evaluated workbook")
    q = sub.add_parser("debtcap", help="Build a debt capacity workbook from a case file (.toml or .json)")
    q.add_argument("case")
    q.add_argument("--out", default="output/debtcap.xlsx")
    q.add_argument("--csv", metavar="DIR", help="also write every sheet as CSV values into DIR")
    q.add_argument("--pitch", metavar="FILE.html", help="also write a printable pitch book (HTML) from the evaluated workbook")
    q = sub.add_parser("fdic", help="Print a [target] case snippet from FDIC BankFind (public API)")
    q.add_argument("cert", type=int)
    q.add_argument("repdte", help="Report date, for example 20241231")
    intake_cli.add_parser(sub)
    a = p.parse_args(argv)
    if a.cmd == "fdic":
        return _fdic(a)
    if a.cmd == "intake":
        return intake_cli.run(a)
    try:
        rc = {"merger": _merger, "dcf": _dcf, "bank": _bank, "lbo": _lbo, "debtcap": _debtcap}[a.cmd](a)
        if rc == 0 and a.csv:
            paths = csv_export.export(a.out, a.csv)
            print(f"Wrote {len(paths)} CSV files to {a.csv}")
        if rc == 0 and a.pitch:
            print(f"Wrote {pitch.build(a.cmd, a.out, a.pitch)}")
    except (OSError, tomllib.TOMLDecodeError, json.JSONDecodeError) as e:  # unwritable output or a malformed case file
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return rc


def _lbo(a):
    try:
        case = lbo.load_case(a.case)
        res = lbo.run(case)
    except lbo.CaseError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    out = lbo_book.build(case, a.out)
    r, su = res["returns"], res["su"]
    print(f"Wrote {out}")
    print(f"Sponsor equity ${su['equity']:,.0f}K | Exit equity ${r['exit_equity']:,.0f}K")
    print(f"Sponsor MOIC {r['moic']:.2f}x | Sponsor IRR {r['irr']:.1%}")
    if r["peak_revolver"] > 0:
        print(f"Revolver peak draw ${r['peak_revolver']:,.0f}K")
    if r["min_cash"] < case["revolver"]["min_cash"] - 1e-6:
        print("Warning: cash falls below the minimum balance in at least one year (revolver exhausted)")
    if r["cov_fails"]:
        print(f"Warning: {r['cov_fails']} covenant test(s) failed")
    return 0


def _dcf(a):
    try:
        case = dcf.load_case(a.case)
        res = dcf.run(case)
        dcf.sensitivities(case)
    except dcf.CaseError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    out = dcf_book.build(case, a.out)
    v = res["val"]
    med = comps.run(case)["metrics"]["ev_ebitda_ntm"]
    print(f"Wrote {out}")
    print(f"WACC {res['wacc']['wacc']:.2%} | Mid-year {'on' if case['dcf']['mid_year'] else 'off'}")
    print(f"DCF share price: Gordon ${v['gordon']['price']:,.2f} | Exit multiple ${v['exit']['price']:,.2f}")
    print(f"Comps median NTM EV/EBITDA {med['stats']['median']:.1f}x -> ${med['implied']['median'][2]:,.2f} per share")
    if "precedents" in case:
        _precedents(case, precedents.run(case["precedents"], "corporate", case["target"]))
    return 0


def _bank(a):
    try:
        case = bank.load_case(a.case)
        res = bank.run(case)
    except lbo.CaseError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    out = bank_book.build(case, a.out)
    print(f"Wrote {out}")
    print(f"Current price ${case['target']['share_price']:.2f} | Cost of equity {res['ke']:.1%}")
    for label, lo, hi in res["football"]:
        print(f"{label}: ${lo:.2f} to ${hi:.2f}")
    if "precedents" in case:
        _precedents(case, res["precedents"])
    return 0


def _debtcap(a):
    try:
        case = debtcap.load_case(a.case)
        res = debtcap.run(case)
        debtcap.sensitivities(case)
    except debtcap.CaseError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    out = debtcap_book.build(case, a.out)
    sz, y = res["sizing"], res["years"]
    print(f"Wrote {out}")
    print(f"Maximum debt ${sz['max_debt']:,.0f}K | Binding constraint {sz['binding']} | Proposed debt ${sz['proposed']:,.0f}K")
    br, rp = res["bridge"], res["reported"]
    print(f"Reported EBITDA ${br['reported']:,.0f}K | Covenant EBITDA ${br['covenant']:,.0f}K "
          f"(add-backs ${br['addbacks']:,.0f}K, ${br['allowed']:,.0f}K allowed under the cap) | "
          f"Max debt on reported ${rp['max_debt']:,.0f}K, change from add-backs ${rp['change']:,.0f}K")
    print(f"At close {y['lev_tot'][0]:.2f}x total, {y['lev_sen'][0]:.2f}x senior secured, "
          f"{y['cov'][0]:.2f}x coverage | Indicative rating {res['ratings'][0]['rating']}")
    print(f"Year 5 {y['lev_tot'][5]:.2f}x total | Debt repaid {y['pct_paid'][5]:.1%} | Year 5 rating {res['ratings'][5]['rating']}")
    if res["limit_fails"]:
        print(f"Warning: {res['limit_fails']} limit test(s) fail in years 1 to 5")
    return 0


PCT_KEYS = {k for spec in precedents.KINDS.values() for k, _, _, fmt in spec if fmt == excel.PCT}


def _precedents(case, res):
    for key, r in res.items():
        m = r["stats"]["median"]
        med = f"{m:.2%}" if key in PCT_KEYS else f"{m:.4g}"
        print(f"Precedents {r['label']}: median {med} of {r['n']} deals -> ${r['implied']['median'][-1]:,.2f} per share")
    for note in case["precedents"]["skipped"]:
        print(f"Precedents skipped, {note}")


def _fdic(a):
    try:
        print(fdic.as_toml(fdic.fetch_target(a.cert, a.repdte), a.cert, a.repdte), end="")
    except (lbo.CaseError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
