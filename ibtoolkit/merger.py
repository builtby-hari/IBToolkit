"""Bank merger engine: case loading, validation, and the Python model.

All money is in $ thousands, shares in thousands, share prices in dollars.
The Excel workbook (merger_book.py) mirrors these formulas line by line.
"""
import copy
import json
import tomllib
from pathlib import Path

from .lbo import CaseError

YEARS = 2
HORIZON = 10  # years of TBV per share paths for the earnback crossover

# (section, field, kind). kind: pos, nonneg, pct, signed (between -1 and 1),
# list2 (two non-negative numbers), pct2 (two percentages).
REQUIRED = [
    ("acquirer", "net_income", "list2"), ("acquirer", "shares", "pos"),
    ("acquirer", "share_price", "pos"), ("acquirer", "tbv", "pos"),
    ("acquirer", "tangible_assets", "pos"),
    ("target", "net_income", "list2"), ("target", "shares", "pos"),
    ("target", "share_price", "pos"), ("target", "tbv", "pos"),
    ("target", "tangible_assets", "pos"), ("target", "noninterest_expense", "pos"),
    ("target", "core_deposits", "nonneg"), ("target", "loans", "nonneg"),
    ("target", "securities", "nonneg"),
    ("deal", "stock_pct", "pct"), ("deal", "cost_of_cash", "pct"),
    ("deal", "cost_saves_pct", "pct"), ("deal", "phase_in", "pct2"),
    ("deal", "merger_charges", "nonneg"), ("deal", "cdi_pct", "pct"),
    ("deal", "cdi_years", "pos"), ("deal", "tax_rate", "pct"),
    ("marks", "loan_duration", "nonneg"), ("marks", "loan_rate_change", "signed"),
    ("marks", "loan_life", "pos"), ("marks", "securities_duration", "nonneg"),
    ("marks", "securities_rate_change", "signed"), ("marks", "securities_life", "pos"),
]


# Optional inputs (section, field, kind, default). Every default leaves the case unchanged.
OPTIONAL = [
    ("deal", "day2_reserve", "nonneg", 0), ("deal", "exchange_ratio", "nonneg", 0), ("deal", "revenue_dissynergies", "nonneg", 0),
    ("restructuring", "securities_sold", "nonneg", 0), ("restructuring", "securities_yield", "pct", 0),
    ("restructuring", "borrowing_rate", "pct", 0),
    ("credit_mark", "total", "nonneg", 0), ("credit_mark", "pcd_share", "pct", 0),
    ("credit_mark", "life", "pos", 1),
    ("marks", "deposit_mark", "signed_k", 0), ("marks", "deposit_life", "pos", 1),
    ("marks", "borrowings_mark", "signed_k", 0), ("marks", "borrowings_life", "pos", 1),
    # Contribution analysis only; 0 = not entered, and that metric is left out of the range.
    ("acquirer", "ltm_net_income", "nonneg", 0), ("acquirer", "total_assets", "nonneg", 0),
    ("acquirer", "deposits", "nonneg", 0), ("acquirer", "loans", "nonneg", 0),
    ("target", "ltm_net_income", "nonneg", 0), ("target", "total_assets", "nonneg", 0),
    ("target", "deposits", "nonneg", 0),
]


def _check(path, v, kind):
    def bad(msg):
        raise CaseError(f"Invalid input {path}: {msg} (got {v!r})")

    def num(x):
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            bad("must be a number")
        return float(x)

    if kind in ("list2", "pct2"):
        if not isinstance(v, list) or len(v) != YEARS:
            bad(f"must be a list of {YEARS} numbers")
        xs = [num(x) for x in v]
        if kind == "list2" and any(x <= 0 for x in xs):
            bad("each value must be greater than 0")
        if kind == "pct2" and not all(0 <= x <= 1 for x in xs):
            bad("each value must be a decimal between 0 and 1")
        return xs
    x = num(v)
    if kind == "signed_k":  # any sign, in $ thousands
        return x
    if kind == "pos" and x <= 0:
        bad("must be greater than 0")
    if kind == "nonneg" and x < 0:
        bad("must be 0 or more")
    if kind == "pct" and not 0 <= x <= 1:
        bad("must be a decimal between 0 and 1")
    if kind == "signed" and not -1 <= x <= 1:
        bad("must be a decimal between -1 and 1")
    return x


def validate(raw):
    """Return a clean case dict, or raise CaseError naming the field."""
    case = {"meta": dict(raw.get("meta", {}))}
    for sec, field, kind in REQUIRED:
        if sec not in raw or field not in raw[sec]:
            raise CaseError(f"Missing required input: {sec}.{field}")
        case.setdefault(sec, {})[field] = _check(f"{sec}.{field}", raw[sec][field], kind)
    d = raw["deal"]
    if ("price_per_share" in d) == ("p_tbv" in d):
        raise CaseError("Give exactly one of deal.price_per_share or deal.p_tbv")
    key = "price_per_share" if "price_per_share" in d else "p_tbv"
    case["deal"][key] = _check(f"deal.{key}", d[key], "pos")
    # Optional inputs; the defaults leave a case without them unchanged.
    for sec, field, kind, default in OPTIONAL:
        case.setdefault(sec, {})[field] = _check(f"{sec}.{field}", raw.get(sec, {}).get(field, default), kind)
    if case["restructuring"]["securities_sold"] > case["target"]["securities"]:
        raise CaseError("Invalid input restructuring.securities_sold: cannot exceed target.securities")
    treat = d.get("cdi_tax_treatment", "net")
    if treat not in ("net", "gross"):
        raise CaseError(f"Invalid input deal.cdi_tax_treatment: use 'net' or 'gross' (got {treat!r})")
    case["deal"]["cdi_tax_treatment"] = treat
    method = d.get("cdi_method", "straight_line")
    if method not in ("straight_line", "syd"):
        raise CaseError(f"Invalid input deal.cdi_method: use 'straight_line' or 'syd' (got {method!r})")
    case["deal"]["cdi_method"] = method
    # ASU 2025-08: "gross_up" books the day 1 allowance on non-PCD (purchased seasoned) loans
    # against amortized cost instead of expensing a day 2 reserve. Default "day2" is pre-ASU CECL.
    npm = raw.get("credit_mark", {}).get("non_pcd_method", "day2")
    if npm not in ("day2", "gross_up"):
        raise CaseError(f"Invalid input credit_mark.non_pcd_method: use 'day2' or 'gross_up' (got {npm!r})")
    case["credit_mark"]["non_pcd_method"] = npm
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
    a, t, d, m = case["acquirer"], case["target"], case["deal"], case["marks"]
    tax = d["tax_rate"]
    pps = d["price_per_share"] if "price_per_share" in d else d["p_tbv"] * t["tbv"] / t["shares"]
    price = pps * t["shares"]
    stock = d["stock_pct"] * price
    cash = price - stock
    new_shares = stock / a["share_price"]

    # Rate mark simplification: mark = -duration x rate change x balance. Negative = write-down.
    loan_mark = -m["loan_duration"] * m["loan_rate_change"] * t["loans"]
    sec_mark = -m["securities_duration"] * m["securities_rate_change"] * t["securities"]
    # Deposit and borrowings marks: positive = liability written down, which adds to equity.
    dep_mark, borr_mark = m["deposit_mark"], m["borrowings_mark"]
    # Credit mark split: the PCD part grosses up the allowance (no income, no TBV effect). The non-PCD
    # part is a fair value discount on loans at close (in net marks, so goodwill and TBV) that then accretes.
    cm = case["credit_mark"]
    pcd_mark, nonpcd_mark = cm["total"] * cm["pcd_share"], cm["total"] * (1 - cm["pcd_share"])
    net_marks = loan_mark + sec_mark + dep_mark + borr_mark - nonpcd_mark
    rs = case["restructuring"]
    restr = rs["securities_sold"] * (rs["borrowing_rate"] - rs["securities_yield"])
    # Gross CDI treatment deducts the full CDI from TBV, so the CDI deferred tax liability is not netted.
    cdi = d["cdi_pct"] * t["core_deposits"]
    gross = d["cdi_tax_treatment"] == "gross"
    cdi_dtl_ded = tax * cdi if gross else 0.0
    # Write-downs create a deferred tax asset, the CDI a liability; positive = net asset.
    net_dta = -tax * (net_marks + cdi)
    fv_net_assets = t["tbv"] + net_marks + cdi + net_dta
    goodwill = price - fv_net_assets
    # One-time items hitting TBV at close: merger charges plus the CECL day 2 reserve on non-PCD loans.
    # Under the ASU 2025-08 gross-up the allowance (day2_reserve) is added to amortized cost instead:
    # no expense, no TBV hit, and the credit component it covers is never accreted into income.
    gross_up = cm["non_pcd_method"] == "gross_up"
    day2_exp = 0.0 if gross_up else d["day2_reserve"]
    grossed = d["day2_reserve"] - day2_exp
    charges_at = (d["merger_charges"] + day2_exp) * (1 - tax)

    pf_shares = a["shares"] + new_shares
    yrs = []
    for i in range(YEARS):
        y = i + 1
        saves = d["cost_saves_pct"] * t["noninterest_expense"] * d["phase_in"][i]
        funding = d["cost_of_cash"] * cash
        accretion = ((-loan_mark / m["loan_life"] if y <= m["loan_life"] else 0)
                     + (-sec_mark / m["securities_life"] if y <= m["securities_life"] else 0))
        credit_accr = (nonpcd_mark - grossed) / cm["life"] if y <= cm["life"] else 0
        dep_amort = ((dep_mark / m["deposit_life"] if y <= m["deposit_life"] else 0)
                     + (borr_mark / m["borrowings_life"] if y <= m["borrowings_life"] else 0))
        n = d["cdi_years"]
        share = (n - y + 1) / (n * (n + 1) / 2) if d["cdi_method"] == "syd" else 1 / n
        cdi_amort = cdi * share if y <= n else 0
        adj_at = (saves - d["revenue_dissynergies"] - funding + accretion + restr + credit_accr - dep_amort - cdi_amort) * (1 - tax)
        ni = a["net_income"][i] + t["net_income"][i] + adj_at
        sa_eps = a["net_income"][i] / a["shares"]
        eps = ni / pf_shares
        yrs.append(dict(saves=saves, dis=d["revenue_dissynergies"], funding=funding, accretion=accretion, restr=restr, credit_accr=credit_accr, dep_amort=dep_amort, cdi_amort=cdi_amort,
                        adj_at=adj_at, ni=ni, eps=eps, sa_eps=sa_eps, acc_d=eps - sa_eps,
                        acc_pct=eps / sa_eps - 1,
                        # CDI amortization is a non-tangible cost. Net treatment: TBV grows by the after-tax
                        # amount. Gross treatment: the deducted CDI falls by the full pre-tax amount.
                        tang_eps=(ni + cdi_amort * (1 if gross else 1 - tax)) / pf_shares))

    pf_tbv = a["tbv"] + t["tbv"] + net_marks * (1 - tax) - cdi_dtl_ded - cash - charges_at
    # Securities sold repay borrowings: tangible assets fall by the sale amount, TBV does not change.
    pf_ta = a["tangible_assets"] + t["tangible_assets"] + net_marks * (1 - tax) - cdi_dtl_ded - cash - charges_at - rs["securities_sold"]
    sa_tbvps, pf_tbvps = a["tbv"] / a["shares"], pf_tbv / pf_shares

    # Simple crossover earnback: each side's TBV per share grows by its own EPS (no dividends,
    # no buybacks). Years past 2 hold the Year 2 EPS flat. Earnback is the first year the
    # pro forma line reaches the standalone line, interpolated within the year. -1 = never.
    sa_path, pf_path = [sa_tbvps], [pf_tbvps]
    for y in range(1, HORIZON + 1):
        r = yrs[min(y, YEARS) - 1]
        sa_path.append(sa_path[-1] + r["sa_eps"])
        pf_path.append(pf_path[-1] + r["tang_eps"])
    gap = [s - p for s, p in zip(sa_path, pf_path)]
    earnback = -1.0
    if gap[0] <= 0:
        earnback = 0.0
    else:
        for y in range(1, HORIZON + 1):
            if gap[y] <= 0:
                earnback = (y - 1) + gap[y - 1] / (gap[y - 1] - gap[y])
                break

    return dict(
        offer_pps=pps, price=price, premium=pps / t["share_price"] - 1, p_tbv=price / t["tbv"],
        p_e=price / t["net_income"][0], stock=stock, cash=cash, exch_ratio=d["exchange_ratio"] or pps / a["share_price"],
        blend_ratio=new_shares / t["shares"],
        new_shares=new_shares, loan_mark=loan_mark, sec_mark=sec_mark, net_marks=net_marks,
        cdi=cdi, net_dta=net_dta, pcd_mark=pcd_mark, nonpcd_mark=nonpcd_mark, cdi_dtl_ded=cdi_dtl_ded, day2_grossed_up=grossed, fv_net_assets=fv_net_assets, goodwill=goodwill, charges_at=charges_at,
        years=yrs, pf_shares=pf_shares, pf_tbv=pf_tbv, pf_ta=pf_ta,
        pf_tce=pf_tbv / pf_ta, sa_tce=a["tbv"] / a["tangible_assets"],
        sa_tbvps=sa_tbvps, pf_tbvps=pf_tbvps, tbv_dil_d=pf_tbvps - sa_tbvps,
        tbv_dil_pct=pf_tbvps / sa_tbvps - 1, earnback=earnback,
        sa_path=sa_path, pf_path=pf_path,
        own_acq=a["shares"] / pf_shares, own_tgt=new_shares / pf_shares,
    )


def axis(base, step, lo=0.0, hi=None, n=5):
    half = n // 2
    return [min(hi, max(lo, base + (i - half) * step)) if hi is not None else max(lo, base + (i - half) * step)
            for i in range(n)]


GRID_STEP = 0.05               # offer price step, share of the base offer
GRID_PHASES = (0.0, 0.5, 1.0)  # share of run-rate cost saves realized in Year 1
SAVES_STEP = 0.05                     # cost saves grid step, points of noninterest expense
MIX_AXIS = (0.0, 0.25, 0.5, 0.75, 1.0)  # stock share of price, consideration mix grid


def sensitivities(case, price_step=GRID_STEP, saves_step=SAVES_STEP):
    """Accretion grids: offer price per share (down, base plus or minus 5% steps) by cost saves
    percent (across, plus or minus 5 point steps). Axes are not market views."""
    base = run(case)
    prices = [base["offer_pps"] * (1 + k * price_step) for k in range(-2, 3)]
    saves = axis(case["deal"]["cost_saves_pct"], saves_step, 0.0, 1.0)
    grids = ([], [])
    for p in prices:
        rows = ([], [])
        for s in saves:
            c = copy.deepcopy(case)
            c["deal"].pop("p_tbv", None)
            c["deal"].update(price_per_share=p, cost_saves_pct=s)
            for i, r in enumerate(run(c)["years"]):
                rows[i].append(r["acc_pct"])
        for g, r in zip(grids, rows):
            g.append(r)
    return {"price_axis": prices, "saves_axis": saves, "acc_y1": grids[0], "acc_y2": grids[1]}


# Contribution metrics: (key, label, value getter for either side). Market cap is shares x price.
CONTRIB = [
    ("ni_ltm", "Net Income, LTM", lambda a: a["ltm_net_income"]),
    ("ni_y1", "Net Income, Year 1", lambda a: a["net_income"][0]),
    ("tce", "Tangible Common Equity", lambda a: a["tbv"]),
    ("assets", "Total Assets", lambda a: a["total_assets"]),
    ("deposits", "Deposits", lambda a: a["deposits"]),
    ("loans", "Loans", lambda a: a["loans"]),
    ("mcap", "Market Capitalization", lambda a: a["shares"] * a["share_price"]),
]


def _pos(v, lo, hi):
    """Where v sits in [lo, hi]: 0 = low end, 1 = high end, outside 0 to 1 = outside the range."""
    return (v - lo) / (hi - lo) if hi > lo else 0.0


def contribution(case):
    """Each side's share of the combined metric, and the all-stock exchange ratio that would give the
    target's holders that share of the pro forma company: (target / acquirer) x acquirer shares / target shares."""
    a, t, r = case["acquirer"], case["target"], run(case)
    rows = {}
    for key, label, get in CONTRIB:
        x, y = get(a), get(t)
        if x > 0 and y > 0:  # 0 = not entered
            rows[key] = dict(label=label, acq=x, tgt=y, acq_pct=x / (x + y), tgt_pct=y / (x + y),
                             ratio=y / x * a["shares"] / t["shares"])
    ratios = [v["ratio"] for v in rows.values()]
    pcts = [v["tgt_pct"] for v in rows.values()]
    lo, hi, plo, phi = min(ratios), max(ratios), min(pcts), max(pcts)
    return dict(rows=rows, ratio_lo=lo, ratio_hi=hi, exch_ratio=r["exch_ratio"],
                ratio_pos=_pos(r["exch_ratio"], lo, hi), tgt_lo=plo, tgt_hi=phi,
                own_tgt=r["own_tgt"], own_pos=_pos(r["own_tgt"], plo, phi))


def breakeven(case):
    """Pre-tax Year 1 cost saves (as realized in Year 1) that make Year 1 EPS accretion exactly 0.
    Saves enter pro forma net income after tax and nothing else depends on them, so:
    breakeven = modeled saves - (pro forma EPS - standalone EPS) x pro forma shares / (1 - tax)."""
    r = run(case)
    y, d, nonint = r["years"][0], case["deal"], case["target"]["noninterest_expense"]
    be = y["saves"] - y["acc_d"] * r["pf_shares"] / (1 - d["tax_rate"])
    ph = d["phase_in"][0]
    return dict(saves=y["saves"], be_saves=be, be_pct=be / nonint,
                be_run_rate=be / (nonint * ph) if ph > 0 else None, cushion=y["saves"] - be)



def accretion_grid(case):
    """Year 1 EPS accretion by offer price (base plus or minus 2 steps) and Year 1 saves realization
    (GRID_PHASES, then the modeled Year 1 phase-in), each point a full engine run."""
    base = run(case)
    prices = [base["offer_pps"] * (1 + k * GRID_STEP) for k in range(-2, 3)]
    phases = [*GRID_PHASES, case["deal"]["phase_in"][0]]
    grid = []
    for p in prices:
        row = []
        for ph in phases:
            c = copy.deepcopy(case)
            c["deal"].pop("p_tbv", None)
            c["deal"].update(price_per_share=p, phase_in=[ph, c["deal"]["phase_in"][1]])
            row.append(run(c)["years"][0]["acc_pct"])
        grid.append(row)
    return {"price_axis": prices, "phase_axis": phases, "acc_y1": grid}
