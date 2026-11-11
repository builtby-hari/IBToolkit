"""Compute seller SDE and buyer EBITDA with a logged add-back trail."""
from typing import List

from .models import AddBack, FinancialPeriod, Normalized


def compute_sde(pretax_income: float, interest: float, depreciation: float,
                amortization: float, owner_salary: float,
                addbacks: List[AddBack]) -> float:
    return (pretax_income + interest + depreciation + amortization
            + owner_salary + sum(a.amount for a in addbacks))


def compute_ebitda(sde: float, manager_salary: float,
                   payroll_burden: float = 0.0765) -> float:
    return sde - manager_salary * (1 + payroll_burden)


def addback_ratio(period: FinancialPeriod, addbacks: List[AddBack]) -> float:
    """Everything added to pretax income, over pretax income (floored at 1)."""
    total = (period.interest + period.depreciation + period.amortization
             + period.owner_salary + sum(a.amount for a in addbacks))
    return total / max(period.pretax_income, 1.0)


def normalize_periods(periods: List[FinancialPeriod], addbacks: List[AddBack],
                      manager_salary: float,
                      payroll_burden: float = 0.0765) -> List[Normalized]:
    out = []
    for p in sorted(periods, key=lambda p: p.fiscal_year):
        mine = [a for a in addbacks if a.fiscal_year == p.fiscal_year]
        sde = compute_sde(p.pretax_income, p.interest, p.depreciation,
                          p.amortization, p.owner_salary, mine)
        out.append(Normalized(p.fiscal_year, sde,
                              compute_ebitda(sde, manager_salary, payroll_burden),
                              addback_ratio(p, mine)))
    return out
