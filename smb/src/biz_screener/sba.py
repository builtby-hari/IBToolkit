"""SBA 7(a) loan sizing, monthly payment, annual debt service and DSCR.

Rules here follow config, which must be checked against the current SBA SOP
(50 10 8.1 changes change-of-ownership rules for loans numbered on or after
2026-10-01). Seller-note equity credit and guarantee fees are not modeled.
"""
from .models import DebtRun

MAX_LOAN = 5_000_000
STANDBY_CREDIT_SHARE = 0.5  # SOP 50 10 8.1 App. 15: standby seller debt <= half of required equity


def loan_amount(price: float, cash_equity: float, min_injection_pct: float,
                cap: float = MAX_LOAN, seller_standby: float = 0.0) -> float:
    """Loan = price less cash and full-standby seller note.

    The standby note counts toward the injection only up to half of it, so
    cash plus that credit must still cover the required injection.
    """
    if price <= 0:
        raise ValueError("price must be positive")
    required = min_injection_pct * price
    credit = min(seller_standby, STANDBY_CREDIT_SHARE * required)
    if cash_equity + credit < required:
        raise ValueError("cash equity is below the minimum equity injection")
    loan = price - cash_equity - seller_standby
    if loan <= 0:
        raise ValueError("cash and seller note cover the whole price; no loan needed")
    if loan > cap:  # capping silently would leave the gap unfunded and overstate DSCR
        raise ValueError("loan of $%.0f exceeds the SBA cap of $%.0f; needs $%.0f more equity"
                         % (loan, cap, loan - cap))
    return loan


def guarantee_fee(loan: float) -> float:
    """Upfront fee at the SOP maximum chart, on the guaranteed portion (loans over 12 months)."""
    guaranteed = loan * (0.85 if loan <= 150_000 else 0.75)
    if loan <= 150_000:
        return 0.02 * guaranteed
    if loan <= 700_000:
        return 0.03 * guaranteed
    return 0.035 * min(guaranteed, 1_000_000) + 0.0375 * max(guaranteed - 1_000_000, 0)


def spread_for_loan(loan: float, bands: dict) -> float:
    """SOP 50 10 tiers: $50,000 or less; $50,001 to $250,000; $250,001 to $350,000; over $350,000."""
    if loan <= 50_000:
        return bands["spread_under_50k"]
    if loan <= 250_000:
        return bands["spread_50k_to_250k"]
    if loan <= 350_000:
        return bands["spread_250k_to_350k"]
    return bands["spread_over_350k"]


def monthly_payment(principal: float, annual_rate: float, years: int) -> float:
    n = years * 12
    if annual_rate == 0:
        return principal / n
    j = annual_rate / 12
    return principal * j / (1 - (1 + j) ** -n)


def loan_balance(principal: float, annual_rate: float, years: int, months_paid: int) -> float:
    """Principal left after months_paid level monthly payments."""
    n = years * 12
    if months_paid >= n:
        return 0.0
    if annual_rate == 0:
        return principal * (1 - months_paid / n)
    j, g = annual_rate / 12, (1 + annual_rate / 12) ** months_paid
    return principal * g - monthly_payment(principal, annual_rate, years) * (g - 1) / j


def dscr(cash_flow: float, annual_debt_service: float) -> float:
    return float("inf") if annual_debt_service == 0 else cash_flow / annual_debt_service


def debt_summary(price: float, ebitda: float, sde: float, prime: float,
                 sba_cfg: dict, buyer_cfg: dict) -> DebtRun:
    loan = loan_amount(price, buyer_cfg["max_cash_equity"],
                       buyer_cfg["min_equity_injection_pct"],
                       seller_standby=buyer_cfg.get("seller_standby_note", 0.0))
    rate = prime + spread_for_loan(loan, sba_cfg)
    years = sba_cfg["term_years"]
    if not 1 <= years <= 10:
        raise ValueError("term_years must be 1-10 for a change of ownership loan")
    annual = 12 * monthly_payment(loan, rate, years)
    return DebtRun(loan, rate, years, annual, dscr(ebitda, annual),
                   dscr(sde - buyer_cfg["owner_living_draw"], annual),
                   guarantee_fee(loan))
