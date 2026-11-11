"""Parse CSV listing exports into Listing records, one deal per external_ref.

Columns: ref, category, asking_price, fiscal_year, revenue, pretax_income and
optional county_fips, interest, depreciation, amortization, owner_salary,
addbacks (one lump sum, personal/one-time), top_customer_share, lease_years_remaining.
Several rows with the same ref add fiscal years to one deal.
"""
import csv
import math
from typing import Dict, List, Optional, Tuple

from .models import AddBack, FinancialPeriod, Listing

Deal = Tuple[Listing, List[FinancialPeriod], List[AddBack]]
REQUIRED = ("ref", "category", "asking_price", "fiscal_year", "revenue", "pretax_income")


def parse_money(raw: str) -> Optional[float]:
    """'$1,250', '(5,000)' -> -5000.0, '' -> None. Raises ValueError on junk."""
    s = (raw or "").strip().replace("$", "").replace(",", "")
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    value = float(s.strip("()"))
    if not math.isfinite(value):
        raise ValueError("not a finite number: %r" % raw)
    return -value if neg else value


def _num(row: dict, key: str, default: Optional[float] = 0.0) -> Optional[float]:
    v = parse_money(row.get(key, ""))
    return default if v is None else v


def parse_csv(path: str, mapping: Optional[Dict[str, str]] = None) -> Tuple[List[Deal], List[str]]:
    """Return (deals, reject messages). `mapping` renames file headers to ours."""
    deals: Dict[str, Deal] = {}
    rejects: List[str] = []
    with open(path, newline="", encoding="utf-8-sig") as f:  # Excel adds a BOM
        for i, raw in enumerate(csv.DictReader(f), start=2):
            row = {(mapping or {}).get(k, k).strip(): v for k, v in raw.items() if k}
            try:
                missing = [k for k in REQUIRED if not (row.get(k) or "").strip()]
                if missing:
                    raise ValueError("missing " + ", ".join(missing))
                ref = row["ref"].strip()
                year = int(row["fiscal_year"])
                period = FinancialPeriod(
                    year, _num(row, "revenue"), _num(row, "pretax_income"),
                    _num(row, "interest"), _num(row, "depreciation"),
                    _num(row, "amortization"), _num(row, "owner_salary"))
                listing = Listing(
                    "csv", ref, row["category"].strip(), _num(row, "asking_price"),
                    (row.get("county_fips") or "").strip(),
                    top_customer_share=_num(row, "top_customer_share", None),
                    lease_years_remaining=_num(row, "lease_years_remaining", None))
                if listing.asking_price <= 0:
                    raise ValueError("asking_price must be positive")
                share = listing.top_customer_share  # a negative or whole-number share would score wrongly
                if share is not None and not 0 <= share <= 1:
                    raise ValueError("top_customer_share must be between 0 and 1 "
                                     "(20 percent is 0.20), got %g" % share)
                seen = deals.get(ref)
                if seen and (seen[0].asking_price, seen[0].category) != (
                        listing.asking_price, listing.category):
                    raise ValueError("%s conflicts with an earlier row's price or category" % ref)
                if seen and any(p.fiscal_year == year for p in seen[1]):
                    raise ValueError("%s repeats fiscal year %d" % (ref, year))
            except ValueError as e:
                rejects.append("line %d: %s" % (i, e))
                continue
            deal = deals.setdefault(ref, (listing, [], []))
            deal[1].append(period)
            extra = _num(row, "addbacks")
            if extra:
                deal[2].append(AddBack(year, "addbacks (csv total)", extra))
    return list(deals.values()), rejects
