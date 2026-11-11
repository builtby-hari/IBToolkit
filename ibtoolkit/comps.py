"""Trading comps engine. Money is in $ millions except per-share figures.

The Excel workbook (dcf_book.py) mirrors these formulas, so both give the same numbers.
"""
from statistics import mean, median

# (key, label, kind, peer field, target field). kind ev = enterprise value multiple, pe = price multiple.
METRICS = [
    ("ev_rev_ltm", "EV / Revenue (LTM)", "ev", "revenue_ltm", "ltm_revenue"),
    ("ev_rev_ntm", "EV / Revenue (NTM)", "ev", "revenue_ntm", "ntm_revenue"),
    ("ev_ebitda_ltm", "EV / EBITDA (LTM)", "ev", "ebitda_ltm", "ltm_ebitda"),
    ("ev_ebitda_ntm", "EV / EBITDA (NTM)", "ev", "ebitda_ntm", "ntm_ebitda"),
    ("pe_ltm", "P / E (LTM)", "pe", "eps_ltm", "ltm_eps"),
    ("pe_ntm", "P / E (NTM)", "pe", "eps_ntm", "ntm_eps"),
]


def percentile(xs, q):
    """Linear interpolation between closest ranks, same as Excel PERCENTILE and PERCENTILE.INC."""
    s = sorted(xs)
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def stats(xs):
    return dict(mean=mean(xs), median=median(xs), p25=percentile(xs, 0.25), p75=percentile(xs, 0.75))


def peer_row(p):
    mcap = p["price"] * p["shares"]
    ev = mcap + p["net_debt"]
    return dict(mcap=mcap, ev=ev,
                ev_rev_ltm=ev / p["revenue_ltm"], ev_rev_ntm=ev / p["revenue_ntm"],
                ev_ebitda_ltm=ev / p["ebitda_ltm"], ev_ebitda_ntm=ev / p["ebitda_ntm"],
                pe_ltm=p["price"] / p["eps_ltm"], pe_ntm=p["price"] / p["eps_ntm"])


def implied(kind, mult, metric, net_debt, shares):
    """Implied (enterprise value, equity value, share price) from one multiple."""
    if kind == "ev":
        ev = mult * metric
        return ev, ev - net_debt, (ev - net_debt) / shares
    price = mult * metric
    return price * shares + net_debt, price * shares, price


def run(case):
    t = case["target"]
    rows = [peer_row(p) for p in case["peers"]]
    out = {}
    for key, label, kind, _, tfield in METRICS:
        st = stats([r[key] for r in rows])
        out[key] = dict(stats=st, target_metric=t[tfield], implied={
            q: implied(kind, st[q], t[tfield], t["net_debt"], t["diluted_shares"])
            for q in ("p25", "median", "p75")})
    return {"peers": rows, "metrics": out}
