"""Data classes for listings, financial periods, add-backs, valuations and scores."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Listing:
    source: str
    external_ref: str
    category: str
    asking_price: float
    county_fips: str = ""
    status: str = "active"
    top_customer_share: Optional[float] = None  # 0..1, None when unknown
    lease_years_remaining: Optional[float] = None


@dataclass
class AddBack:
    fiscal_year: int
    label: str
    amount: float
    category: str = "one_time"  # personal, one_time, non_cash, owner_comp
    source_note: str = ""


@dataclass
class FinancialPeriod:
    fiscal_year: int
    revenue: float
    pretax_income: float
    interest: float = 0.0
    depreciation: float = 0.0
    amortization: float = 0.0
    owner_salary: float = 0.0
    is_stated: bool = True


@dataclass
class Normalized:
    fiscal_year: int
    sde: float
    ebitda: float
    addback_ratio: float


@dataclass
class Valuation:
    sde_value: float
    ebitda_value: float
    dcf_value: float
    blended_value: float
    discount_rate: float


@dataclass
class DebtRun:
    loan_amount: float
    rate: float
    term_years: int
    annual_payment: float
    dscr_ebitda: float
    dscr_owner: float
    guarantee_fee: float = 0.0  # upfront SBA fee, paid at closing on top of equity

    @property
    def dscr_lender(self) -> float:
        """Lender test uses the lower of the two views."""
        return min(self.dscr_ebitda, self.dscr_owner)


@dataclass
class RedFlag:
    code: str
    severity: str  # "high" or "medium"
    evidence: str


@dataclass
class Score:
    components: Dict[str, float]
    penalty: float
    total: float
    asking_price: float = 0.0
    rank: int = 0
    flags: List[RedFlag] = field(default_factory=list)
    ref: Optional[str] = None
    notes: List[str] = field(default_factory=list)  # scoring caveats shown in reports


@dataclass
class Result:
    """One screened deal, flattened for storage, reports and alerts."""
    source: str
    ref: str
    category: str
    county_fips: str
    asking_price: float
    blended_value: float
    dscr: Optional[float]  # None when no debt figure could be computed
    total: float
    rank: int = 0
    flags: List[RedFlag] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return "%s:%s" % (self.source, self.ref)

    @property
    def blockers(self) -> List[RedFlag]:
        """High-severity flags. A deal with any of these, or no DSCR, does not pass."""
        return [f for f in self.flags if f.severity == "high"]

    @property
    def passes(self) -> bool:
        return self.dscr is not None and not self.blockers
