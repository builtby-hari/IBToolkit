"""DCF engine: case loading, validation, and the Python model. Money is in $ millions.

Mid-year convention: unlevered free cash flow in year t is discounted t - 0.5 years. The Gordon
terminal value is also discounted at N - 0.5 (its cash flows arrive mid-year); the exit multiple
terminal value is a year-end sale, so it is discounted at N.
"""
import json
import tomllib
from pathlib import Path

from . import precedents
from .lbo import YEARS, CaseError, _check, axis

TARGET = [("net_debt", "num"), ("diluted_shares", "pos"), ("ltm_revenue", "pos"),
          ("ntm_revenue", "pos"), ("ltm_ebitda", "pos"), ("ntm_ebitda", "pos"),
          ("ltm_eps", "pos"), ("ntm_eps", "pos")]
PEER = [("price", "pos"), ("shares", "pos"), ("net_debt", "num"), ("revenue_ltm", "pos"),
        ("revenue_ntm", "pos"), ("ebitda_ltm", "pos"), ("ebitda_ntm", "pos"),
        ("eps_ltm", "pos"), ("eps_ntm", "pos")]
DCF = [("revenue_growth", "list"), ("ebitda_margin", "list"), ("da_pct_revenue", "pct"),
       ("capex_pct_revenue", "pct"), ("nwc_pct_revenue_change", "pct"), ("tax_rate", "pct"),
       ("risk_free", "pct"), ("equity_risk_premium", "pct"), ("beta", "pos"),
       ("pre_tax_cost_of_debt", "pct"), ("debt_to_capital", "pct"), ("terminal_growth", "pct"),
       ("exit_multiple", "pos")]
MIN_PEERS = 3


def _section(raw, name, fields, label=None):
    label = label or name
    sec = raw.get(name)
    if not isinstance(sec, dict):
        raise CaseError(f"Missing required input: {label}")
    out = {}
    for field, kind in fields:
        if field not in sec:
            raise CaseError(f"Missing required input: {label}.{field}")
        out[field] = _check(f"{label}.{field}", sec[field], kind)
    return out


def validate(raw):
    """Return a clean case dict, or raise CaseError naming the field."""
    if raw.get("meta", {}).get("draft") is True:
        raise CaseError("This case is a DRAFT ([meta] draft = true) built by filing intake and is not safe to run. "
                        "Fill in every TODO, then run `python -m ibtoolkit intake --review <file>` and `--approve`.")
    case = {"meta": dict(raw.get("meta", {})), "target": _section(raw, "target", TARGET)}
    case["dcf"] = _section(raw, "dcf", DCF)
    mid = raw["dcf"].get("mid_year", False)
    if not isinstance(mid, bool):
        raise CaseError(f"Invalid input dcf.mid_year: must be true or false (got {mid!r})")
    case["dcf"]["mid_year"] = mid
    peers = raw.get("peers")
    if not isinstance(peers, list) or len(peers) < MIN_PEERS:
        raise CaseError(f"Missing required input: peers (need at least {MIN_PEERS})")
    case["peers"] = []
    for i, p in enumerate(peers):
        row = _section({"p": p}, "p", PEER, f"peers[{i}]")
        if not isinstance(p.get("name"), str) or not p["name"].strip():
            raise CaseError(f"Missing required input: peers[{i}].name")
        case["peers"].append({"name": p["name"], **row})
    if "precedents" in raw:
        case["precedents"] = precedents.validate(raw["precedents"], "corporate")
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


def wacc_parts(d):
    ke = d["risk_free"] + d["beta"] * d["equity_risk_premium"]
    kd = d["pre_tax_cost_of_debt"] * (1 - d["tax_rate"])
    return dict(ke=ke, kd_at=kd, we=1 - d["debt_to_capital"],
                wacc=(1 - d["debt_to_capital"]) * ke + d["debt_to_capital"] * kd)


def run(case, wacc=None, g=None, exit_mult=None):
    """Five-year DCF. Optional overrides feed the sensitivity grids. Index 0 is the LTM base year."""
    d, t = case["dcf"], case["target"]
    wp = wacc_parts(d)
    w = wp["wacc"] if wacc is None else wacc
    g = d["terminal_growth"] if g is None else g
    xm = d["exit_multiple"] if exit_mult is None else exit_mult
    if w <= g:
        raise CaseError(f"WACC ({w:.2%}) must be greater than terminal growth ({g:.2%})")
    half = 0.5 if d["mid_year"] else 0.0
    keys = ["rev", "ebitda", "da", "ebit", "tax", "nopat", "capex", "dnwc", "ufcf", "period", "df", "pv"]
    y = {k: [None] * (YEARS + 1) for k in keys}
    y["rev"][0] = t["ltm_revenue"]
    for i in range(1, YEARS + 1):
        rev = y["rev"][i - 1] * (1 + d["revenue_growth"][i - 1])
        ebitda = rev * d["ebitda_margin"][i - 1]
        da = rev * d["da_pct_revenue"]
        ebit = ebitda - da
        tax = max(0, ebit) * d["tax_rate"]
        capex = rev * d["capex_pct_revenue"]
        dnwc = d["nwc_pct_revenue_change"] * (rev - y["rev"][i - 1])
        ufcf = ebit - tax + da - capex - dnwc
        period = i - half
        df = 1 / (1 + w) ** period
        for k, v in dict(rev=rev, ebitda=ebitda, da=da, ebit=ebit, tax=tax, nopat=ebit - tax,
                         capex=capex, dnwc=dnwc, ufcf=ufcf, period=period, df=df, pv=ufcf * df).items():
            y[k][i] = v
    sum_pv = sum(y["pv"][1:])
    f, e = y["ufcf"][YEARS], y["ebitda"][YEARS]

    tv_g = f * (1 + g) / (w - g)
    tv_x = xm * e
    tv_x_mid = tv_x / (1 + w) ** half  # exit TV restated to the mid-year basis Gordon uses
    val = {}
    for name, tv, per in (("gordon", tv_g, YEARS - half), ("exit", tv_x, YEARS)):
        pv_tv = tv / (1 + w) ** per
        ev = sum_pv + pv_tv
        eq = ev - t["net_debt"]
        val[name] = dict(tv=tv, pv_tv=pv_tv, ev=ev, equity=eq, price=eq / t["diluted_shares"],
                         tv_pct_ev=pv_tv / ev)
    val["gordon"]["implied_multiple"] = tv_g * (1 + w) ** half / e
    val["exit"]["implied_growth"] = (tv_x_mid * w - f) / (tv_x_mid + f)
    return {"years": y, "wacc": dict(wp, wacc=w), "sum_pv": sum_pv, "val": val}


STEPS = dict(wacc=0.005, g=0.0025, mult=1.0)  # sensitivity axis steps, written to Inputs


def sensitivities(case, wacc_step=STEPS["wacc"], g_step=STEPS["g"], mult_step=STEPS["mult"]):
    """Share price grids. Axes are the base case plus or minus steps; they are not market views."""
    d = case["dcf"]
    w0 = wacc_parts(d)["wacc"]
    waccs = axis(w0, wacc_step)
    gs = axis(d["terminal_growth"], g_step)
    xs = axis(d["exit_multiple"], mult_step)
    return {
        "wacc_axis": waccs, "g_axis": gs, "mult_axis": xs,
        "price_wacc_g": [[run(case, wacc=w, g=g)["val"]["gordon"]["price"] for g in gs] for w in waccs],
        "price_wacc_mult": [[run(case, wacc=w, exit_mult=x)["val"]["exit"]["price"] for x in xs]
                            for w in waccs],
    }
