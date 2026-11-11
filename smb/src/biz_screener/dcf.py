"""Five-year discounted cash flow with a Gordon growth terminal value."""
from typing import List, Tuple


def discount_rate(risk_free: float, size_premium: float, industry_premium: float) -> float:
    return risk_free + size_premium + industry_premium


def project_cash_flows(ebitda0: float, da: float, growth: float, tax_rate: float,
                       capex_pct: float, years: int) -> List[float]:
    """Year 1 is ebitda0 (run-rate); later years grow at `growth`.

    CF_t = EBITDA_t - capex_pct * EBITDA_t - tax_rate * max(EBITDA_t - D&A, 0).
    """
    flows = []
    for t in range(years):
        e = ebitda0 * (1 + growth) ** t
        flows.append(e - capex_pct * e - tax_rate * max(e - da, 0.0))
    return flows


def dcf_value(cash_flows: List[float], rate: float,
              terminal_growth: float) -> Tuple[float, float]:
    """Return (value, terminal share of value)."""
    if rate <= terminal_growth:
        raise ValueError("discount rate must exceed terminal growth")
    if not cash_flows:
        raise ValueError("need at least one cash flow")
    n = len(cash_flows)
    explicit = sum(cf / (1 + rate) ** t for t, cf in enumerate(cash_flows, 1))
    tv = cash_flows[-1] * (1 + terminal_growth) / (rate - terminal_growth)
    pv_tv = tv / (1 + rate) ** n
    value = explicit + pv_tv
    return value, (pv_tv / value if value else 0.0)
