"""Debt capacity engine: how much debt a company can carry, and on what structure.

All money is in $ thousands. The Excel workbook (debtcap_book.py) mirrors these
formulas line by line, so both produce the same numbers.

Sizing at close uses four constraints, each solved for total debt D:
  total leverage        D <= max_total x covenant EBITDA
  senior secured lev.   D <= max_senior x covenant EBITDA / secured share
  interest coverage     D <= LTM EBITDA / (min coverage x blended rate)
  FCF / debt            D <= Year 1 cash flow / (min FCF-to-debt + blended rate)
Tranches are fixed shares of total debt, so the blended rate does not depend on D
and every constraint has a closed form (no goal seek, no circularity).

Covenant EBITDA is reported LTM EBITDA plus add-backs, with the add-backs capped at a
percentage of reported EBITDA. Lenders size the two leverage tests on covenant EBITDA;
coverage and FCF / debt use cash (reported and projected) EBITDA. With no add-backs the
two figures are equal and every output matches a model without the bridge.
"""
import json
import tomllib
from pathlib import Path

from .lbo import YEARS, CaseError, _check

TOL = 1e-6  # matches the Check_Tol input written to the workbook
NAMES = ["Total Leverage", "Senior Secured Leverage", "Interest Coverage", "FCF / Debt"]
ADDBACKS = ["synergies", "restructuring", "non_recurring", "pro_forma_acquisitions", "other"]
# Illustrative default: the two SEC-filed credit agreements cited in the README cap add-backs at 25%.
DEFAULT_CAP = 0.25

# (section, field, kind). Kinds as in lbo._check.
REQUIRED = [
    ("company", "ltm_ebitda", "pos"),
    ("projections", "ebitda", "plist"),
    ("projections", "capex", "nlist"),
    ("projections", "cash_taxes", "nlist"),
    ("projections", "nwc_increase", "nlist"),
    ("limits", "max_total_leverage", "pos"),
    ("limits", "max_senior_leverage", "pos"),
    ("limits", "min_interest_coverage", "pos"),
    ("limits", "min_fcf_to_debt", "pct"),
    ("term_loan_b", "share", "pct"),
    ("term_loan_b", "rate", "pct"),
    ("term_loan_b", "amort_pct", "pct"),
    ("term_loan_b", "sweep_pct", "pct"),
    ("senior_notes", "share", "pct"),
    ("senior_notes", "rate", "pct"),
]


def _grid(rows):
    if not isinstance(rows, list) or len(rows) < 2:
        raise CaseError("Missing required input: rating_grid (at least two bands, best first)")
    out = []
    for i, r in enumerate(rows):
        for f in ("rating", "max_leverage", "min_coverage"):
            if f not in r:
                raise CaseError(f"Missing required input: rating_grid[{i}].{f}")
        if not isinstance(r["rating"], str) or not r["rating"].strip() or r["rating"].startswith("="):
            raise CaseError(f"Invalid input rating_grid[{i}].rating: must be plain text (got {r['rating']!r})")
        out.append({"rating": r["rating"].strip(),
                    "max_leverage": _check(f"rating_grid[{i}].max_leverage", r["max_leverage"], "pos"),
                    "min_coverage": _check(f"rating_grid[{i}].min_coverage", r["min_coverage"], "nonneg")})
    for a, b in zip(out, out[1:]):
        if b["max_leverage"] < a["max_leverage"] or b["min_coverage"] > a["min_coverage"]:
            raise CaseError("Invalid input rating_grid: bands run best to worst, so maximum leverage "
                            "must not fall and minimum coverage must not rise down the list")
    return out


def validate(raw):
    """Return a clean case dict, or raise CaseError naming the field."""
    case = {"meta": dict(raw.get("meta", {}))}
    for sec, field, kind in REQUIRED:
        if sec not in raw or field not in raw[sec]:
            raise CaseError(f"Missing required input: {sec}.{field}")
        case.setdefault(sec, {})[field] = _check(f"{sec}.{field}", raw[sec][field], kind)
    case["limits"]["cushion_pct"] = _check("limits.cushion_pct", raw["limits"].get("cushion_pct", 0), "pct")
    sl = raw.get("second_lien")
    if sl is None:
        case["second_lien"] = {"share": 0.0, "rate": 0.0}
    else:
        for f in ("share", "rate"):
            if f not in sl:
                raise CaseError(f"Missing required input: second_lien.{f}")
        case["second_lien"] = {f: _check(f"second_lien.{f}", sl[f], "pct") for f in ("share", "rate")}
    shares = case["term_loan_b"]["share"] + case["senior_notes"]["share"] + case["second_lien"]["share"]
    if abs(shares - 1) > 1e-9:
        raise CaseError(f"Invalid input tranche shares: term_loan_b, senior_notes and second_lien shares "
                        f"must sum to 1 (got {shares:.6f})")
    if case["term_loan_b"]["share"] <= 0:
        raise CaseError("Invalid input term_loan_b.share: must be greater than 0 (first lien anchors the structure)")
    if blended(case) <= 0:
        raise CaseError("Invalid input tranche rates: the blended interest rate must be greater than 0")
    s = raw.get("sensitivity", {})
    case["sensitivity"] = {"haircut_step": _check("sensitivity.haircut_step", s.get("haircut_step", 0.05), "pos"),
                           "rate_step": _check("sensitivity.rate_step", s.get("rate_step", 0.01), "pos")}
    if case["sensitivity"]["haircut_step"] > 0.2:
        raise CaseError("Invalid input sensitivity.haircut_step: must be 0.2 or less (the grid runs four steps)")
    if 2 * case["sensitivity"]["rate_step"] >= blended(case):
        raise CaseError("Invalid input sensitivity.rate_step: two steps down would take the blended rate to zero")
    case["rating_grid"] = _grid(raw.get("rating_grid"))
    cv = raw.get("covenant_ebitda", {})
    case["covenant_ebitda"] = {k: _check(f"covenant_ebitda.{k}", cv.get(k, 0), "nonneg") for k in ADDBACKS}
    case["covenant_ebitda"]["cap_pct"] = _check("covenant_ebitda.cap_pct", cv.get("cap_pct", DEFAULT_CAP), "pct")
    fc = raw.get("free_and_clear", {})
    case["free_and_clear"] = {k: _check(f"free_and_clear.{k}", fc.get(k, 0), "nonneg") for k in ("amount", "pct_ebitda")}
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


def blended(case):
    return sum(case[k]["share"] * case[k]["rate"] for k in ("term_loan_b", "senior_notes", "second_lien"))


def secured_share(case):
    return case["term_loan_b"]["share"] + case["second_lien"]["share"]


def bridge(case):
    """Reported LTM EBITDA to covenant EBITDA: add-backs capped at cap_pct of reported EBITDA."""
    e0, c = case["company"]["ltm_ebitda"], case["covenant_ebitda"]
    total = sum(c[k] for k in ADDBACKS)
    cap = c["cap_pct"] * e0
    allowed = min(total, cap)
    return dict(reported=e0, addbacks=total, cap=cap, allowed=allowed, excluded=total - allowed,
                cap_binds=1 if total > cap else 0, uncapped=e0 + total, covenant=e0 + allowed)


def caps(case, haircut=0.0, shift=0.0, adjusted=True):
    """Maximum total debt under each of the four constraints, in NAMES order.
    haircut cuts LTM and Year 1 EBITDA; shift adds to every tranche rate.
    Leverage tests use covenant EBITDA (reported EBITDA when adjusted is False);
    coverage and FCF / debt always use cash EBITDA."""
    p, lim = case["projections"], case["limits"]
    e0 = case["company"]["ltm_ebitda"] * (1 - haircut)
    el = (bridge(case)["covenant"] if adjusted else case["company"]["ltm_ebitda"]) * (1 - haircut)
    cf1 = p["ebitda"][0] * (1 - haircut) - p["capex"][0] - p["cash_taxes"][0] - p["nwc_increase"][0]
    r = blended(case) + shift
    return [lim["max_total_leverage"] * el,
            lim["max_senior_leverage"] * el / secured_share(case),
            e0 / (lim["min_interest_coverage"] * r),
            max(0.0, cf1) / (lim["min_fcf_to_debt"] + r)]


def rate_grid(grid, lev, cov, has_interest):
    """Indicative rating: the best band where both the leverage and coverage tests pass.
    Returns the fail flags per band and the leverage, coverage and combined labels."""
    lf = [1 if lev > g["max_leverage"] else 0 for g in grid]
    cf = [1 if has_interest and cov < g["min_coverage"] else 0 for g in grid]

    def first(flags):
        return next((g["rating"] for g, f in zip(grid, flags) if f == 0), f"Below {grid[-1]['rating']}")

    return dict(lev_fail=lf, cov_fail=cf, lev_rating=first(lf), cov_rating=first(cf),
                rating=first([max(a, b) for a, b in zip(lf, cf)]))


KEYS = ["ebitda", "capex", "taxes", "dnwc", "ufcf", "t_beg", "t_int", "t_mand", "t_sweep", "t_end",
        "n_beg", "n_int", "n_end", "s_beg", "s_int", "s_end", "int_tot", "fcf", "retained", "cum_cash",
        "debt_tot", "sec_tot", "lev_tot", "lev_sen", "cov_ebitda", "lev_cov", "sen_cov", "cov", "cov_capex", "fcf_debt",
        "lev_ok", "sen_ok", "cov_ok", "fcf_ok", "all_ok", "fail_any", "paid", "pct_paid", "turns"]


def run(case):
    """Size the debt, split it into tranches, and project five years of credit statistics.
    Interest is on beginning balances. Cash taxes come from the case and are not
    re-computed for interest. Only the term loan B amortizes and takes the sweep."""
    p, lim = case["projections"], case["limits"]
    tl, sn, sl = case["term_loan_b"], case["senior_notes"], case["second_lien"]
    e0 = case["company"]["ltm_ebitda"]
    mx = caps(case)
    max_debt = min(mx)
    binding = mx.index(max_debt)
    proposed = max_debt * (1 - lim["cushion_pct"])
    t0, n0, s0 = tl["share"] * proposed, sn["share"] * proposed, sl["share"] * proposed

    y = {k: [None] * (YEARS + 1) for k in KEYS}
    y["ebitda"][0] = e0
    y["t_end"][0], y["n_end"][0], y["s_end"][0] = t0, n0, s0
    y["int_tot"][0] = t0 * tl["rate"] + n0 * sn["rate"] + s0 * sl["rate"]
    y["cum_cash"][0] = 0.0
    for i in range(1, YEARS + 1):
        e, cx, tx, nw = p["ebitda"][i - 1], p["capex"][i - 1], p["cash_taxes"][i - 1], p["nwc_increase"][i - 1]
        t_beg, n_beg, s_beg = y["t_end"][i - 1], y["n_end"][i - 1], y["s_end"][i - 1]
        t_int, n_int, s_int = t_beg * tl["rate"], n_beg * sn["rate"], s_beg * sl["rate"]
        int_tot = t_int + n_int + s_int
        ufcf = e - cx - tx - nw
        fcf = ufcf - int_tot
        t_mand = min(t_beg, tl["amort_pct"] * t0)
        t_sweep = min(t_beg - t_mand, tl["sweep_pct"] * max(0, fcf - t_mand))
        retained = fcf - t_mand - t_sweep
        row = dict(ebitda=e, capex=cx, taxes=tx, dnwc=nw, ufcf=ufcf, t_beg=t_beg, t_int=t_int, t_mand=t_mand,
                   t_sweep=t_sweep, t_end=t_beg - t_mand - t_sweep, n_beg=n_beg, n_int=n_int, n_end=n_beg,
                   s_beg=s_beg, s_int=s_int, s_end=s_beg, int_tot=int_tot, fcf=fcf, retained=retained,
                   cum_cash=y["cum_cash"][i - 1] + retained)
        for k, v in row.items():
            y[k][i] = v
    for i in range(YEARS + 1):
        y["debt_tot"][i] = y["t_end"][i] + y["n_end"][i] + y["s_end"][i]
        y["sec_tot"][i] = y["t_end"][i] + y["s_end"][i]
        y["lev_tot"][i] = y["debt_tot"][i] / y["ebitda"][i]
        y["lev_sen"][i] = y["sec_tot"][i] / y["ebitda"][i]
        # shortcut: add-backs apply at close only; years 1 to 5 assume projections already include them.
        y["cov_ebitda"][i] = bridge(case)["covenant"] if i == 0 else y["ebitda"][i]
        y["lev_cov"][i] = y["debt_tot"][i] / y["cov_ebitda"][i]
        y["sen_cov"][i] = y["sec_tot"][i] / y["cov_ebitda"][i]
        it = y["int_tot"][i]
        y["cov"][i] = y["ebitda"][i] / it if it > 0 else 0.0
        if i:
            y["cov_capex"][i] = (y["ebitda"][i] - y["capex"][i]) / it if it > 0 else 0.0
            prev = y["debt_tot"][i - 1]
            y["fcf_debt"][i] = y["fcf"][i] / prev if prev > 0 else 0.0
            y["fcf_ok"][i] = 1 if prev <= 0 or y["fcf_debt"][i] >= lim["min_fcf_to_debt"] - TOL else 0
            y["paid"][i] = y["debt_tot"][0] - y["debt_tot"][i]
            y["pct_paid"][i] = y["paid"][i] / y["debt_tot"][0] if y["debt_tot"][0] > 0 else 0.0
            y["turns"][i] = y["lev_tot"][0] - y["lev_tot"][i]
    y["fcf_debt"][0], y["fcf_ok"][0] = y["fcf_debt"][1], y["fcf_ok"][1]
    for i in range(YEARS + 1):
        y["lev_ok"][i] = 1 if y["lev_cov"][i] <= lim["max_total_leverage"] + TOL else 0
        y["sen_ok"][i] = 1 if y["sen_cov"][i] <= lim["max_senior_leverage"] + TOL else 0
        y["cov_ok"][i] = (1 if y["cov"][i] >= lim["min_interest_coverage"] - TOL else 0) if y["int_tot"][i] > 0 else 1
        y["all_ok"][i] = y["lev_ok"][i] * y["sen_ok"][i] * y["cov_ok"][i] * y["fcf_ok"][i]
        if i:
            y["fail_any"][i] = 1 - y["all_ok"][i]
    ratings = [rate_grid(case["rating_grid"], y["lev_tot"][i], y["cov"][i], y["int_tot"][i] > 0)
               for i in range(YEARS + 1)]
    br = bridge(case)
    mx_rep = caps(case, adjusted=False)
    fc = case["free_and_clear"]
    free_clear = max(fc["amount"], fc["pct_ebitda"] * br["covenant"])
    return {
        "years": y, "ratings": ratings, "bridge": br,
        "reported": dict(caps=mx_rep, max_debt=min(mx_rep), change=max_debt - min(mx_rep)),
        "free_clear": dict(basket=free_clear, max_with_basket=max_debt + free_clear),
        "sizing": dict(ltm_ebitda=e0, y1_cf=y["ufcf"][1], blended=blended(case), secured_share=secured_share(case),
                       caps=mx, max_debt=max_debt, binding=NAMES[binding], proposed=proposed,
                       tranches=dict(term_loan_b=t0, senior_notes=n0, second_lien=s0)),
        "limit_fails": sum(y["fail_any"][1:]),
    }


def sensitivities(case):
    """Maximum debt and binding constraint by EBITDA haircut (down) and rate shift (across)."""
    s = case["sensitivity"]
    hair = [i * s["haircut_step"] for i in range(5)]
    shift = [(i - 2) * s["rate_step"] for i in range(5)]
    grids = [[caps(case, h, d) for d in shift] for h in hair]
    return {"haircut_axis": hair, "shift_axis": shift,
            "max_debt": [[max(0.0, min(c)) for c in row] for row in grids],
            "binding": [[NAMES[c.index(min(c))] for c in row] for row in grids]}
