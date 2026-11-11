"""Buyer equity returns (IRR and MOIC) on the SBA-financed purchase.

Hold for the DCF forecast years, then sell at the entry EBITDA multiple (no multiple
expansion). Each year the buyer keeps the DCF's after-tax cash flow less SBA debt
service. At exit the remaining SBA balance and the standby seller note are repaid.
Equity in = buyer cash plus the SBA guarantee fee paid at closing.
"""
from typing import List, Optional

from . import dcf, sba
from .models import DebtRun


def irr(flows: List[float]) -> Optional[float]:
    """Annual IRR by bisection; None when the flows never change sign in the range."""
    def npv(r):
        return sum(cf / (1 + r) ** t for t, cf in enumerate(flows))
    lo, hi = -0.99, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def equity_returns(price: float, ebitda: float, da: float, debt: DebtRun, cfg: dict) -> Optional[dict]:
    """None when EBITDA is not positive (no exit multiple to apply)."""
    if ebitda <= 0:
        return None
    d, b = cfg["dcf"], cfg["buyer"]
    years = d["forecast_years"]
    # shortcut: taxes ignore the interest deduction (understates cash to equity); add a levered tax line if it matters.
    cash = [cf - debt.annual_payment for cf in dcf.project_cash_flows(
        ebitda, da, d["revenue_growth_base"], d["tax_rate"], d["maintenance_capex_pct_of_ebitda"], years)]
    exit_ev = price / ebitda * ebitda * (1 + d["revenue_growth_base"]) ** (years - 1)
    payoff = sba.loan_balance(debt.loan_amount, debt.rate, debt.term_years, years * 12) \
        + b.get("seller_standby_note", 0.0)
    exit_equity = exit_ev - payoff
    invested = b["max_cash_equity"] + debt.guarantee_fee
    flows = [-invested] + cash[:-1] + [cash[-1] + exit_equity]
    return dict(invested=invested, year1_cash=cash[0], exit_ev=exit_ev, payoff=payoff,
                exit_equity=exit_equity, years=years,
                moic=(sum(cash) + exit_equity) / invested, irr=irr(flows))
