"""Rule engine for red flags on a listing."""
from typing import List, Optional

from .models import FinancialPeriod, Listing, Normalized, RedFlag


def penalty(flags: List[RedFlag], per_flag: float, cap: float) -> float:
    return min(len(flags) * per_flag, cap)


def _declining_years(periods: List[FinancialPeriod]) -> int:
    """Consecutive year-over-year revenue declines ending at the latest year."""
    ps = sorted(periods, key=lambda p: p.fiscal_year)
    n = 0
    for prev, cur in zip(reversed(ps[:-1]), reversed(ps[1:])):
        if cur.revenue < prev.revenue:
            n += 1
        else:
            break
    return n


def evaluate_flags(listing: Listing, periods: List[FinancialPeriod],
                   normalized: List[Normalized], cfg: dict,
                   industry: Optional[dict] = None) -> List[RedFlag]:
    rf = cfg["red_flags"]
    industry = industry or {}
    flags: List[RedFlag] = []

    def add(code, sev, ev):
        flags.append(RedFlag(code, sev, ev))

    if not periods or not all(p.is_stated for p in periods):
        add("missing_financials", "high", "No financial periods, or figures are estimates")
    if normalized:
        latest = max(normalized, key=lambda n: n.fiscal_year)
        if latest.addback_ratio > rf["max_addback_ratio"]:
            add("addback_ratio", "high", "Add-backs are %.0f%% of pretax income (max %.0f%%)"
                % (latest.addback_ratio * 100, rf["max_addback_ratio"] * 100))
        if latest.sde > 0 and listing.asking_price / latest.sde > rf["max_asking_sde_multiple"]:
            add("asking_multiple", "medium", "Asking is %.2fx SDE (max %.1fx)"
                % (listing.asking_price / latest.sde, rf["max_asking_sde_multiple"]))
        elif latest.sde <= 0:
            add("nonpositive_sde", "high", "SDE is zero or negative")
    n = _declining_years(periods)
    if n >= rf["decline_years_flag"]:
        add("declining_revenue", "high", "Revenue fell %d years in a row" % n)
    if (listing.top_customer_share is not None
            and listing.top_customer_share > rf["max_top_customer_share"]):
        add("concentration", "high", "Top customer is %.0f%% of revenue"
            % (listing.top_customer_share * 100))
    if (listing.lease_years_remaining is not None
            and listing.lease_years_remaining < rf["min_lease_years_remaining"]):
        add("short_lease", "medium", "Only %.1f lease years remain" % listing.lease_years_remaining)
    if industry.get("tabc_transfer_flag"):
        add("tabc_transfer", "medium", "Liquor permit transfer needed (TABC timing risk)")
    if industry.get("environmental_flag"):
        add("environmental", "medium", "Fuel site: tanks and contamination need a Phase I review")
    return flags
