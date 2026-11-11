"""LBO engine: case loading, validation, and the Python model.

All money is in $ thousands. The Excel workbook (lbo_book.py) mirrors these
formulas line by line, so both produce the same numbers.
"""
import copy
import json
import tomllib
from pathlib import Path

YEARS = 5


class CaseError(ValueError):
    """Raised when a case file is missing a required input or has a bad value."""


# (section, field, kind). kind: pos = greater than 0, nonneg = 0 or more,
# pct = between 0 and 1, list = five percentages between 0 and 1, plist = five numbers above 0,
# nlist = five numbers of 0 or more.
REQUIRED = [
    ("transaction", "ltm_revenue", "pos"),
    ("transaction", "ltm_ebitda", "pos"),
    ("transaction", "entry_multiple", "pos"),
    ("transaction", "exit_multiple", "pos"),
    ("transaction", "advisory_fee_pct", "pct"),
    ("transaction", "financing_fee_pct", "pct"),
    ("operating", "revenue_growth", "list"),
    ("operating", "ebitda_margin", "list"),
    ("operating", "da_pct_revenue", "pct"),
    ("operating", "capex_pct_revenue", "pct"),
    ("operating", "nwc_pct_revenue_change", "pct"),
    ("operating", "tax_rate", "pct"),
    ("senior", "leverage", "nonneg"),
    ("senior", "rate", "pct"),
    ("senior", "amort_pct", "pct"),
    ("senior", "sweep_pct", "pct"),
]
MEZZ = [("leverage", "nonneg"), ("cash_rate", "pct"), ("pik_rate", "pct")]
REVOLVER = [("commitment", "nonneg"), ("rate", "pct"), ("undrawn_fee", "pct"), ("min_cash", "nonneg")]
COVENANTS = [("max_total_leverage", "plist"), ("min_interest_coverage", "nlist")]
# Covenant defaults when the section is absent: effectively untested.
NO_COVENANT = {"max_total_leverage": [99.0] * YEARS, "min_interest_coverage": [0.0] * YEARS}


def _check(path, v, kind):
    def bad(msg):
        raise CaseError(f"Invalid input {path}: {msg} (got {v!r})")

    def num(x):
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            bad("must be a number")
        return float(x)

    if kind in ("list", "plist", "nlist"):
        if not isinstance(v, list) or len(v) != YEARS:
            bad(f"must be a list of {YEARS} numbers")
        if kind == "list" and not all(-1 <= num(x) <= 1 for x in v):
            bad("each value must be between -1 and 1 as a decimal")
        if kind == "plist" and not all(num(x) > 0 for x in v):
            bad("each value must be greater than 0")
        if kind == "nlist" and not all(num(x) >= 0 for x in v):
            bad("each value must be 0 or more")
        return [float(x) for x in v]
    x = num(v)
    if kind == "pos" and x <= 0:
        bad("must be greater than 0")
    if kind == "nonneg" and x < 0:
        bad("must be 0 or more")
    if kind == "pct" and not 0 <= x <= 1:
        bad("must be a decimal between 0 and 1")
    return x


def validate(raw):
    """Return a clean case dict, or raise CaseError naming the field."""
    case = {"meta": dict(raw.get("meta", {}))}
    for sec, field, kind in REQUIRED:
        if sec not in raw or field not in raw[sec]:
            raise CaseError(f"Missing required input: {sec}.{field}")
        case.setdefault(sec, {})[field] = _check(f"{sec}.{field}", raw[sec][field], kind)
    t = raw["transaction"]
    case["transaction"]["cash_at_close"] = _check(
        "transaction.cash_at_close", t.get("cash_at_close", 0), "nonneg")
    case["transaction"]["financing_fee_years"] = _check(
        "transaction.financing_fee_years", t.get("financing_fee_years", YEARS), "pos")
    for f in ("mgmt_rollover_pct", "option_pool_pct"):  # optional, 0 = none
        case["transaction"][f] = _check(f"transaction.{f}", t.get(f, 0), "pct")
    for sec, fields, default in (("revolver", REVOLVER, {f: 0.0 for f, _ in REVOLVER}),
                                 ("covenants", COVENANTS, NO_COVENANT)):
        raw_sec = raw.get(sec)
        if raw_sec is None:
            case[sec] = dict(default)
        else:
            for field, _ in fields:
                if field not in raw_sec:
                    raise CaseError(f"Missing required input: {sec}.{field}")
            case[sec] = {f: _check(f"{sec}.{f}", raw_sec[f], k) for f, k in fields}
    case["sensitivity"] = {"multiple_step": _check(
        "sensitivity.multiple_step", raw.get("sensitivity", {}).get("multiple_step", 0.5), "pos")}
    mz = raw.get("mezz")
    if mz is None:
        case["mezz"] = {"leverage": 0.0, "cash_rate": 0.0, "pik_rate": 0.0}
    else:
        for field, kind in MEZZ:
            if field not in mz:
                raise CaseError(f"Missing required input: mezz.{field}")
        case["mezz"] = {f: _check(f"mezz.{f}", mz[f], k) for f, k in MEZZ}
    return case


def load_case(path):
    path = Path(path)
    if not path.exists():
        raise CaseError(f"Case file not found: {path}")
    if path.suffix == ".toml":
        raw = tomllib.loads(path.read_text())
    elif path.suffix == ".json":
        raw = json.loads(path.read_text())
    else:
        raise CaseError(f"Unsupported case file type {path.suffix!r}; use .toml or .json")
    return validate(raw)


def run(case):
    """Run the model. Returns per-year rows (index 0 is close, 1..5 are years),
    sources and uses, and exit returns.

    Interest is on beginning balances, so there is no circularity. Each year: mandatory
    amortization, then the revolver draws if cash would fall below the minimum or repays
    first from cash above the minimum, then the sweep takes its share of what is left."""
    t, o, s, m = case["transaction"], case["operating"], case["senior"], case["mezz"]
    rv, cv = case["revolver"], case["covenants"]
    e0 = t["ltm_ebitda"]
    ev = e0 * t["entry_multiple"]
    sen0, mez0 = s["leverage"] * e0, m["leverage"] * e0
    advisory = t["advisory_fee_pct"] * ev
    financing = t["financing_fee_pct"] * (sen0 + mez0 + rv["commitment"])
    total_uses = ev + advisory + financing + t["cash_at_close"]
    equity = total_uses - sen0 - mez0
    if equity <= 0:
        raise CaseError("Sponsor equity is zero or negative: debt plus cash exceeds total uses")

    keys = ["rev", "ebitda", "margin", "da", "ebit", "capex", "dnwc", "ebt", "tax", "ni", "fcf",
            "cash_end", "s_beg", "s_int", "s_mand", "s_sweep", "s_end", "r_beg", "r_int", "r_fee",
            "cash_pre", "r_draw", "r_repay", "r_end", "m_beg", "m_cash", "m_pik", "m_end",
            "fee_beg", "fee_amort", "fee_end", "debt_tot", "lev_tot", "lev_sen", "cov", "fccr",
            "lev_max", "lev_head", "lev_ok", "cov_min", "cov_head", "cov_ok"]
    y = {k: [None] * (YEARS + 1) for k in keys}
    y["rev"][0], y["ebitda"][0] = t["ltm_revenue"], e0
    y["s_end"][0], y["m_end"][0], y["cash_end"][0] = sen0, mez0, t["cash_at_close"]
    y["r_end"][0], y["fee_end"][0] = 0.0, financing
    for i in range(1, YEARS + 1):
        rev = y["rev"][i - 1] * (1 + o["revenue_growth"][i - 1])
        ebitda = rev * o["ebitda_margin"][i - 1]
        da = rev * o["da_pct_revenue"]
        capex = rev * o["capex_pct_revenue"]
        dnwc = o["nwc_pct_revenue_change"] * (rev - y["rev"][i - 1])
        s_beg, m_beg, r_beg = y["s_end"][i - 1], y["m_end"][i - 1], y["r_end"][i - 1]
        fee_beg = y["fee_end"][i - 1]
        fee_amort = min(fee_beg, financing / t["financing_fee_years"])
        s_int, m_cash, m_pik = s_beg * s["rate"], m_beg * m["cash_rate"], m_beg * m["pik_rate"]
        r_int, r_fee = r_beg * rv["rate"], (rv["commitment"] - r_beg) * rv["undrawn_fee"]
        ebt = ebitda - da - fee_amort - s_int - m_cash - m_pik - r_int - r_fee
        tax = max(0, ebt) * o["tax_rate"]
        fcf = ebitda - s_int - m_cash - r_int - r_fee - tax - capex - dnwc
        s_mand = min(s_beg, s["amort_pct"] * sen0)
        cash_pre = y["cash_end"][i - 1] + fcf - s_mand
        r_draw = min(rv["commitment"] - r_beg, max(0, rv["min_cash"] - cash_pre))
        r_repay = min(r_beg, max(0, cash_pre - rv["min_cash"]))
        s_sweep = min(s_beg - s_mand, s["sweep_pct"] * max(0, fcf - s_mand - r_repay),
                      max(0, cash_pre - r_repay - rv["min_cash"]))
        row = dict(rev=rev, ebitda=ebitda, margin=ebitda / rev, da=da, ebit=ebitda - da,
                   capex=capex, dnwc=dnwc, ebt=ebt, tax=tax, ni=ebt - tax, fcf=fcf,
                   cash_end=cash_pre - s_sweep + r_draw - r_repay,
                   s_beg=s_beg, s_int=s_int, s_mand=s_mand, s_sweep=s_sweep,
                   s_end=s_beg - s_mand - s_sweep, r_beg=r_beg, r_int=r_int, r_fee=r_fee,
                   cash_pre=cash_pre, r_draw=r_draw, r_repay=r_repay, r_end=r_beg + r_draw - r_repay,
                   m_beg=m_beg, m_cash=m_cash, m_pik=m_pik, m_end=m_beg + m_pik,
                   fee_beg=fee_beg, fee_amort=fee_amort, fee_end=fee_beg - fee_amort)
        for k, v in row.items():
            y[k][i] = v
    y["margin"][0] = e0 / t["ltm_revenue"]
    for i in range(YEARS + 1):
        y["debt_tot"][i] = y["s_end"][i] + y["m_end"][i] + y["r_end"][i]
        y["lev_tot"][i] = y["debt_tot"][i] / y["ebitda"][i]
        y["lev_sen"][i] = (y["s_end"][i] + y["r_end"][i]) / y["ebitda"][i]
        if i:
            ci = y["s_int"][i] + y["m_cash"][i] + y["r_int"][i] + y["r_fee"][i]
            fixed = ci + y["s_mand"][i]
            y["cov"][i] = y["ebitda"][i] / ci if ci > 0 else 0.0
            y["fccr"][i] = (y["ebitda"][i] - y["capex"][i] - y["tax"][i]) / fixed if fixed > 0 else 0.0
            y["lev_max"][i] = cv["max_total_leverage"][i - 1]
            y["lev_head"][i] = 1 - y["lev_tot"][i] / y["lev_max"][i]
            # Negative EBITDA makes leverage negative, which would pass the test; it fails here instead.
            y["lev_ok"][i] = 1 if y["ebitda"][i] > 0 and y["lev_head"][i] >= 0 else 0
            y["cov_min"][i] = cv["min_interest_coverage"][i - 1]
            y["cov_head"][i] = (1 - y["cov_min"][i] / y["cov"][i] if y["cov"][i] > 0
                                else -1 if ci > 0 else 1)
            y["cov_ok"][i] = 1 if y["cov_head"][i] >= 0 else 0

    exit_ev = t["exit_multiple"] * y["ebitda"][YEARS]
    exit_equity = (exit_ev - y["s_end"][YEARS] - y["m_end"][YEARS] - y["r_end"][YEARS]
                   + y["cash_end"][YEARS])
    # Management rolls equity pro rata with the sponsor; the option pool takes its share of exit equity first.
    sponsor_share = 1 - t["mgmt_rollover_pct"]
    sponsor_equity = equity * sponsor_share
    proceeds = exit_equity * (1 - t["option_pool_pct"]) * sponsor_share
    moic = proceeds / sponsor_equity
    # Value creation bridge, total equity before the option pool. The four parts sum to exit less entry equity.
    bridge = dict(ebitda_growth=(y["ebitda"][YEARS] - e0) * t["entry_multiple"],
                  multiple=(t["exit_multiple"] - t["entry_multiple"]) * y["ebitda"][YEARS],
                  deleveraging=(sen0 + mez0 - t["cash_at_close"]) - (exit_ev - exit_equity),
                  fees=-(advisory + financing))
    irr = moic ** (1 / YEARS) - 1 if moic > 0 else -1.0
    return {
        "years": y,
        "su": dict(purchase_price=ev, advisory=advisory, financing=financing,
                   cash_to_bs=t["cash_at_close"], total_uses=total_uses, senior=sen0,
                   mezz=mez0, equity=equity, sponsor_equity=sponsor_equity,
                   total_sources=sen0 + mez0 + equity),
        "returns": dict(exit_ebitda=y["ebitda"][YEARS], exit_ev=exit_ev,
                        exit_equity=exit_equity, sponsor_proceeds=proceeds, moic=moic, irr=irr,
                        bridge=bridge,
                        min_cash=min(y["cash_end"][1:]), peak_revolver=max(y["r_end"]),
                        cov_fails=sum(2 - y["lev_ok"][i] - y["cov_ok"][i] for i in range(1, YEARS + 1))),
    }


def _irr_with(case, section, field, value, section2=None, field2=None, value2=None):
    c = copy.deepcopy(case)
    c[section][field] = value
    if section2:
        c[section2][field2] = value2
    return run(c)["returns"]["irr"]


def axis(base, step, floor=0.0, n=5):
    half = n // 2
    return [max(floor, base + (i - half) * step) for i in range(n)]


def sensitivities(case, mult_step=None, lev_step=0.5):
    """IRR grids. Axes are the base case plus or minus steps; they are not market views."""
    mult_step = mult_step or case["sensitivity"]["multiple_step"]
    t = case["transaction"]
    exits = axis(t["exit_multiple"], mult_step)
    entries = axis(t["entry_multiple"], mult_step)
    levs = axis(case["senior"]["leverage"], lev_step)
    return {
        "exit_axis": exits,
        "entry_axis": entries,
        "leverage_axis": levs,
        "irr_entry_exit": [[_irr_with(case, "transaction", "entry_multiple", en,
                                      "transaction", "exit_multiple", ex) for ex in exits]
                           for en in entries],
        "irr_leverage_exit": [[_irr_with(case, "senior", "leverage", lv,
                                         "transaction", "exit_multiple", ex) for ex in exits]
                              for lv in levs],
    }
