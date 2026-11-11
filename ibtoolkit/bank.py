"""Bank valuation engine (FIG style): case loading, validation, and the Python model.

Money is in $ millions, shares in millions, per-share values in $. The Excel
workbook (bank_book.py) mirrors these formulas, so both produce the same numbers.

Methods: P/TBV against ROTE regression across peers, trailing peer P/E on normalized
LTM EPS, and a dividend discount model where excess capital above a target TCE / assets
ratio is paid out, capped at a maximum payout of net income.

Core (normalized) LTM net income is an optional input, defaulting to GAAP LTM. It drives
the target ROTE in the regression and the EPS in the P/E method, so both sit on the same
earnings basis as the DDM forecast.
"""
import json
import statistics
import tomllib
from pathlib import Path

from . import precedents
from .lbo import YEARS, CaseError, _check

# (section, field, kind). See lbo._check for kinds.
REQUIRED = [
    ("target", "net_income", "pos"),
    ("target", "tce", "pos"),
    ("target", "total_assets", "pos"),
    ("target", "shares", "pos"),
    ("target", "dividends", "nonneg"),
    ("target", "share_price", "pos"),
    ("forecast", "net_income_growth", "list"),
    ("forecast", "asset_growth", "list"),
    ("capital", "target_tce_ratio", "pct"),
    ("cost_of_equity", "risk_free", "pct"),
    ("cost_of_equity", "beta", "pos"),
    ("cost_of_equity", "erp", "pct"),
    ("terminal", "growth", "pct"),
    ("terminal", "ptbv", "pos"),
    ("valuation", "range_pct", "pct"),
]
# (section, field, kind, default). Optional inputs; None means "same as GAAP net income".
OPTIONAL = [
    ("target", "core_net_income", "pos", None),
    ("capital", "max_payout", "pos", 1.0),  # distributions / net income; 1.0 releases no capital beyond earnings
]
PEER_FIELDS = [("ptbv", "pos"), ("pe", "pos"), ("rote", "pct")]
MIN_PEERS = 3


def validate(raw):
    case = {"meta": dict(raw.get("meta", {}))}
    for sec, field, kind in REQUIRED:
        if sec not in raw or field not in raw[sec]:
            raise CaseError(f"Missing required input: {sec}.{field}")
        case.setdefault(sec, {})[field] = _check(f"{sec}.{field}", raw[sec][field], kind)
    for sec, field, kind, default in OPTIONAL:
        v = raw[sec].get(field, default)
        case[sec][field] = case["target"]["net_income"] if v is None else _check(f"{sec}.{field}", v, kind)
    peers = raw.get("peers")
    if not isinstance(peers, list) or len(peers) < MIN_PEERS:
        raise CaseError(f"Missing required input: peers (at least {MIN_PEERS} rows of name, ptbv, pe, rote)")
    case["peers"] = []
    for i, p in enumerate(peers):
        for field in ("name", "ptbv", "pe", "rote"):
            if field not in p:
                raise CaseError(f"Missing required input: peers[{i}].{field}")
        row = {"name": str(p["name"])}
        for field, kind in PEER_FIELDS:
            v = _check(f"peers[{i}].{field}", p[field], kind)
            row[field] = v
        case["peers"].append(row)
    if len({p["rote"] for p in case["peers"]}) < 2:
        raise CaseError("Invalid input peers.rote: peers need at least two different ROTE values for a regression")
    if len({p["ptbv"] for p in case["peers"]}) < 2:
        raise CaseError("Invalid input peers.ptbv: peers need at least two different P/TBV values for a regression")
    if ke(case) <= case["terminal"]["growth"]:
        raise CaseError("Invalid input terminal.growth: must be below the cost of equity")
    if "precedents" in raw:
        case["precedents"] = precedents.validate(raw["precedents"], "bank")
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


def ke(case):
    c = case["cost_of_equity"]
    return c["risk_free"] + c["beta"] * c["erp"]


def ols(xs, ys):
    """Slope, intercept and R squared, same as Excel SLOPE, INTERCEPT and RSQ."""
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    slope = sxy / sxx
    return slope, my - slope * mx, sxy * sxy / (sxx * syy)


def run(case, k=None, ptbv=None, g=None):
    """Full model. Optional k (cost of equity), ptbv (terminal P/TBV) and g (terminal growth) feed the sensitivity grids."""
    t, f, cap, tm, v = (case[x] for x in ("target", "forecast", "capital", "terminal", "valuation"))
    peers = case["peers"]
    k = ke(case) if k is None else k
    tm = {"growth": tm["growth"] if g is None else g, "ptbv": tm["ptbv"] if ptbv is None else ptbv}
    sh = t["shares"]

    keys = ["ni", "assets", "req_tce", "tce_pre", "div", "tce", "excess", "ratio", "rote", "payout", "df", "pv_div"]
    y = {x: [None] * (YEARS + 1) for x in keys}
    y["ni"][0], y["assets"][0], y["tce"][0] = t["net_income"], t["total_assets"], t["tce"]
    y["ratio"][0] = t["tce"] / t["total_assets"]
    y["payout"][0] = t["dividends"] / t["net_income"]  # LTM anchor for the projected payouts
    y["excess"][0] = t["tce"] - cap["target_tce_ratio"] * t["total_assets"]
    for i in range(1, YEARS + 1):
        y["ni"][i] = y["ni"][i - 1] * (1 + f["net_income_growth"][i - 1])
        y["assets"][i] = y["assets"][i - 1] * (1 + f["asset_growth"][i - 1])
        y["req_tce"][i] = cap["target_tce_ratio"] * y["assets"][i]
        y["tce_pre"][i] = y["tce"][i - 1] + y["ni"][i]
        y["div"][i] = max(0.0, min(cap["max_payout"] * y["ni"][i], y["tce_pre"][i] - y["req_tce"][i]))
        y["tce"][i] = y["tce_pre"][i] - y["div"][i]
        y["excess"][i] = y["tce"][i] - y["req_tce"][i]
        y["ratio"][i] = y["tce"][i] / y["assets"][i]
        y["rote"][i] = y["ni"][i] / y["tce"][i - 1]
        y["payout"][i] = y["div"][i] / y["ni"][i]
        y["df"][i] = 1 / (1 + k) ** i
        y["pv_div"][i] = y["div"][i] * y["df"][i]

    slope, icpt, rsq = ols([p["rote"] for p in peers], [p["ptbv"] for p in peers])
    tbvps = t["tce"] / sh
    rote = t["core_net_income"] / t["tce"]
    implied_ptbv = icpt + slope * rote
    ltm_eps = t["core_net_income"] / sh
    median_pe = statistics.median(p["pe"] for p in peers)

    pv_divs = sum(y["pv_div"][1:])
    tv_ptbv = tm["ptbv"] * y["tce"][YEARS]
    tv_div = y["ni"][YEARS] * (1 + tm["growth"]) - tm["growth"] * y["tce"][YEARS]
    tv_gordon = tv_div / (k - tm["growth"])
    pv = {m: y["df"][YEARS] * tv for m, tv in (("ptbv", tv_ptbv), ("gordon", tv_gordon))}
    ddm = {m: (pv_divs + pv[m]) / sh for m in pv}

    price_reg, price_pe = implied_ptbv * tbvps, ltm_eps * median_pe
    prec = precedents.run(case["precedents"], "bank", t) if "precedents" in case else {}
    r = v["range_pct"]
    field = [("P/TBV vs ROTE Regression", price_reg * (1 - r), price_reg * (1 + r)),
             ("P/E (LTM, normalized)", price_pe * (1 - r), price_pe * (1 + r)),
             ("Dividend Discount Model", min(ddm.values()), max(ddm.values()))]
    field += precedents.football(prec)
    return {
        "precedents": prec,
        "years": y, "ke": k,
        "stats": {n: dict(mean=statistics.mean(p[n] for p in peers), median=statistics.median(p[n] for p in peers),
                          high=max(p[n] for p in peers), low=min(p[n] for p in peers))
                  for n in ("ptbv", "pe", "rote")},
        "regression": dict(slope=slope, intercept=icpt, rsq=rsq, target_rote=rote, implied_ptbv=implied_ptbv,
                           tbvps=tbvps, price=price_reg),
        "pe": dict(ltm_eps=ltm_eps, median_pe=median_pe, price=price_pe),
        "market": dict(ptbv=t["share_price"] / tbvps, pe=t["share_price"] / ltm_eps, rote=rote),
        "ddm": dict(pv_divs=pv_divs, tv_ptbv=tv_ptbv, tv_gordon=tv_gordon, pv_tv_ptbv=pv["ptbv"],
                    pv_tv_gordon=pv["gordon"], price_ptbv=ddm["ptbv"], price_gordon=ddm["gordon"],
                    price_mid=sum(ddm.values()) / 2,
                    # cross-checks: the exit P/TBV should sit near both of these
                    reg_ptbv_y5=icpt + slope * y["rote"][YEARS], gordon_ptbv=tv_gordon / y["tce"][YEARS]),
        "football": field,
    }


STEPS = dict(ke=0.005, ptbv=0.1, g=0.0025)  # sensitivity axis steps, written to Inputs


def sensitivities(case, ke_step=STEPS["ke"], ptbv_step=STEPS["ptbv"], g_step=STEPS["g"]):
    """DDM value per share on 5 by 5 grids, base case in the centre: cost of equity by terminal P/TBV
    and cost of equity by Gordon growth. Axes are the base plus or minus fixed steps."""
    k0, tm = ke(case), case["terminal"]
    steps = (-2, -1, 0, 1, 2)
    ke_axis = [k0 + i * ke_step for i in steps]
    ptbv_axis = [tm["ptbv"] + i * ptbv_step for i in steps]
    g_axis = [tm["growth"] + i * g_step for i in steps]
    if min(ke_axis) <= max(g_axis):
        raise CaseError("Sensitivity axes invalid: lowest cost of equity must stay above highest terminal growth")
    return {"ke_axis": ke_axis, "ptbv_axis": ptbv_axis, "g_axis": g_axis,
            "price_ke_ptbv": [[run(case, k=k, ptbv=x)["ddm"]["price_ptbv"] for x in ptbv_axis] for k in ke_axis],
            "price_ke_g": [[run(case, k=k, g=x)["ddm"]["price_gordon"] for x in g_axis] for k in ke_axis]}
