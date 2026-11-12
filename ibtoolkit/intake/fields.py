"""The shared field list for filing intake.

Every intake source (SEC XBRL, a PDF of a 10-K or 10-Q, a deal document) returns the same thing:
a list of SourcedValue. Downstream code (draft case writers, the review step, the variance adapter)
only ever reads SourcedValue, so sources can be added without touching the models.

Rules:
- Money is in raw units as filed (USD, not millions). Case writers convert to $ millions.
- Every value carries where it came from. No source, no value.
- Anything we can't find is not guessed: it is left out and shows up as TODO in the draft.
"""
from dataclasses import dataclass, field, asdict

# Status of a value after extraction or review.
OK = "ok"            # found, passed checks
FLAG = "flag"        # found, but a check failed or it looks odd; needs a human look
APPROVED = "approved"  # a human signed off in the review step

# Source kinds.
XBRL = "xbrl"
PDF = "pdf"
MANUAL = "manual"

# Period types.
FY = "FY"      # fiscal year, from a 10-K
QTR = "Q"      # a single quarter, from a 10-Q
YTD = "YTD"    # year to date, from a 10-Q
LTM = "LTM"    # last twelve months, computed (FY + YTD - prior YTD)
INSTANT = "instant"  # balance sheet value at period_end

# Canonical fields: name -> (unit, kind, description). kind is "flow" (income/cash flow, has a
# period) or "stock" (balance sheet, a point in time).
FIELDS = {
    # Income statement
    "revenue": ("USD", "flow", "Total revenue"),
    "operating_income": ("USD", "flow", "Operating income (EBIT)"),
    "d_and_a": ("USD", "flow", "Depreciation and amortization"),
    "interest_expense": ("USD", "flow", "Interest expense"),
    "income_tax": ("USD", "flow", "Income tax expense"),
    "net_income": ("USD", "flow", "Net income attributable to the company"),
    "diluted_eps": ("USD/shares", "flow", "Diluted earnings per share"),
    "diluted_shares": ("shares", "flow", "Weighted average diluted shares"),
    # Cash flow
    "capex": ("USD", "flow", "Capital expenditures (positive number)"),
    "operating_cash_flow": ("USD", "flow", "Net cash from operating activities"),
    # Balance sheet
    "cash": ("USD", "stock", "Cash and cash equivalents"),
    "debt": ("USD", "stock", "Total debt (current plus long term)"),
    "current_assets": ("USD", "stock", "Total current assets"),
    "current_liabilities": ("USD", "stock", "Total current liabilities"),
    "total_assets": ("USD", "stock", "Total assets"),
    "liabilities_and_equity": ("USD", "stock", "Total liabilities and stockholders' equity (the review step checks it ties to total assets)"),
    "total_equity": ("USD", "stock", "Total stockholders' equity"),
    "goodwill": ("USD", "stock", "Goodwill"),
    "intangibles": ("USD", "stock", "Intangible assets other than goodwill"),
    "shares_outstanding": ("shares", "stock", "Common shares outstanding"),
}


@dataclass
class SourcedValue:
    field: str                 # a key of FIELDS
    value: float               # raw units as filed
    unit: str                  # must match FIELDS[field][0]
    period_type: str           # FY, Q, YTD, LTM or instant
    period_end: str            # ISO date, e.g. "2025-12-31"
    source_kind: str           # xbrl, pdf or manual
    source_ref: str            # xbrl: "10-K FY2025 accn 0000000000-25-000000 tag Revenues"; pdf: "file.pdf p.47"
    period_start: str = ""     # ISO date for flows; blank for instants
    form: str = ""             # 10-K, 10-Q, 8-K, ...
    filed: str = ""            # ISO filing date if known
    segment: str = ""          # blank for the whole company; e.g. "Americas" for segment values
    status: str = OK
    notes: list = field(default_factory=list)  # human-readable flags and explanations

    def __post_init__(self):
        if self.field not in FIELDS:
            raise ValueError(f"unknown field {self.field!r}")
        if self.unit != FIELDS[self.field][0]:
            raise ValueError(f"{self.field}: unit {self.unit!r} should be {FIELDS[self.field][0]!r}")
        if not self.source_ref:
            raise ValueError(f"{self.field}: every value needs a source_ref")

    def flag(self, note):
        self.status = FLAG
        self.notes.append(note)
        return self

    def to_dict(self):
        return asdict(self)


def by_field(values, segment=""):
    """Index values by field for one segment (blank = whole company). Last one wins."""
    return {v.field: v for v in values if v.segment == segment}
