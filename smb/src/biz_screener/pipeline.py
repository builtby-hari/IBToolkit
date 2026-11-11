"""Run one deal through normalize, value, debt, flags and score."""
from typing import List, Optional

from . import dcf, multiples, normalize, red_flags, sba, scoring
from .models import (AddBack, DebtRun, FinancialPeriod, Listing, RedFlag, Result, Score,
                     Valuation)

MARKET_NOTE = "market context not scored (data not built)"
GROWTH_NOTE = "revenue growth not provided: ask the broker"
CONCENTRATION_NOTE = "customer concentration not provided: ask the broker"
OPERATIONAL = {"short_lease", "tabc_transfer", "environmental"}


def cagr_of(periods: List[FinancialPeriod]) -> Optional[float]:
    ps = sorted(periods, key=lambda p: p.fiscal_year)
    years = ps[-1].fiscal_year - ps[0].fiscal_year if ps else 0
    if years < 1 or ps[0].revenue <= 0 or ps[-1].revenue <= 0:
        return None
    return (ps[-1].revenue / ps[0].revenue) ** (1 / years) - 1


def screen_deal(listing: Listing, periods: List[FinancialPeriod], addbacks: List[AddBack],
                cfg: dict, prime: Optional[float] = None, risk_free: Optional[float] = None):
    """Return (Score, Valuation or None, DebtRun or None). Needs >= 1 period."""
    ind = cfg["industries"][listing.category]
    norm = normalize.normalize_periods(periods, addbacks, ind["manager_salary_default"])
    latest = norm[-1]
    flags: List[RedFlag] = red_flags.evaluate_flags(listing, periods, norm, cfg, ind)

    mid = cfg["valuation"]["use_midpoint"]
    d, v = cfg["dcf"], cfg["valuation"]
    latest_p = max(periods, key=lambda p: p.fiscal_year)
    rf = risk_free if risk_free is not None else d["risk_free_fallback"]
    rate = dcf.discount_rate(rf, d["size_illiquidity_premium"], d["industry_premium"])
    # Non-positive earnings cannot be valued by growth; value them at zero.
    ebitda = max(latest.ebitda, 0.0)
    cfs = dcf.project_cash_flows(
        ebitda, latest_p.depreciation + latest_p.amortization, d["revenue_growth_base"],
        d["tax_rate"], d["maintenance_capex_pct_of_ebitda"], d["forecast_years"])
    dcf_v, _ = dcf.dcf_value(cfs, rate, d["terminal_growth"])
    sde_v = multiples.value_from_sde(max(latest.sde, 0.0), ind, mid)
    ebitda_v = multiples.value_from_ebitda(ebitda, ind, mid)
    blended = (v["weight_sde_multiple"] * sde_v + v["weight_dcf"] * dcf_v
               + v["weight_ebitda_multiple"] * ebitda_v)
    valuation = Valuation(sde_v, ebitda_v, dcf_v, blended, rate)

    debt = None
    try:
        debt = sba.debt_summary(listing.asking_price, latest.ebitda, latest.sde,
                                prime if prime is not None else cfg["sba"]["prime_fallback"],
                                cfg["sba"], cfg["buyer"])
    except ValueError as e:  # equity shortfall, bad price, or bad term
        flags.append(RedFlag("equity_shortfall", "high", str(e)))
    if debt and debt.dscr_lender < cfg["sba"]["min_dscr_lender"]:
        flags.append(RedFlag("low_dscr", "high", "Lender DSCR %.2fx is below %.2fx"
                             % (debt.dscr_lender, cfg["sba"]["min_dscr_lender"])))

    market = scoring.market_score(None)  # needs Census data, not built yet
    notes = [] if market is not None else [MARKET_NOTE]
    cagr = cagr_of(periods)
    if cagr is None:
        notes.append(GROWTH_NOTE)
    if listing.top_customer_share is None:
        notes.append(CONCENTRATION_NOTE)
    stated = all(p.is_stated for p in periods)
    comps = {
        "valuation_gap": scoring.valuation_gap_score(listing.asking_price, blended),
        "dscr": scoring.dscr_score(debt.dscr_lender) if debt else 0.0,
        "revenue_trend": scoring.trend_score(cagr),
        "concentration": scoring.concentration_score(listing.top_customer_share),
        "data_quality": 50.0 * stated + 50.0 * min(len(periods), 3) / 3,
        "operational_risk": max(0.0, 100.0 - 25.0 * sum(f.code in OPERATIONAL for f in flags)),
    }
    if market is not None:
        comps["market_context"] = market
    pen = red_flags.penalty(flags, cfg["red_flags"]["penalty_per_flag"],
                            cfg["red_flags"]["penalty_cap"])
    total = scoring.total_score(comps, cfg["scoring"]["weights"], pen)
    return (Score(comps, pen, total, listing.asking_price, flags=flags, ref=listing.external_ref, notes=notes),
            valuation, debt)


def to_result(listing: Listing, score: Score, valuation: Valuation,
              debt: Optional[DebtRun]) -> Result:
    return Result(listing.source, listing.external_ref, listing.category, listing.county_fips,
                  listing.asking_price, valuation.blended_value,
                  debt.dscr_lender if debt else None, score.total, score.rank, score.flags,
                  score.notes)
