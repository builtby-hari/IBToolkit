"""Load and validate settings (TOML) and .env keys."""
import os
from typing import Dict, List

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # pip install biz-screener[config]

Settings = dict


def load_settings(path: str) -> Settings:
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_env(path: str) -> Dict[str, str]:
    """Read KEY=VALUE lines; missing file gives {}. Blank values are dropped."""
    out: Dict[str, str] = {}
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if v.strip():
                    out[k.strip()] = v.strip().strip("\"'")
    return out


def validate_settings(s: Settings) -> List[str]:
    errs: List[str] = []
    pct = [("buyer", "min_equity_injection_pct"), ("dcf", "revenue_growth_base"),
           ("dcf", "tax_rate"), ("dcf", "terminal_growth"),
           ("dcf", "maintenance_capex_pct_of_ebitda"),
           ("dcf", "size_illiquidity_premium"), ("sba", "prime_fallback")]
    for sec, key in pct:
        v = s.get(sec, {}).get(key)
        if v is None or not 0 <= v <= 1:
            errs.append("%s.%s must be a fraction between 0 and 1" % (sec, key))
    for name, ind in s.get("industries", {}).items():
        for k in ("sde", "ebitda"):
            lo, hi = ind.get(k + "_multiple_low"), ind.get(k + "_multiple_high")
            if lo is None or hi is None or lo > hi or lo <= 0:
                errs.append("industries.%s.%s multiple range is invalid" % (name, k))
    v = s.get("valuation", {})
    total = (v.get("weight_sde_multiple", 0) + v.get("weight_dcf", 0)
             + v.get("weight_ebitda_multiple", 0))
    if abs(total - 1.0) > 1e-9:
        errs.append("valuation weights must sum to 1.0 (got %s)" % total)
    w = sum(s.get("scoring", {}).get("weights", {}).values())
    if abs(w - 100) > 1e-9:
        errs.append("scoring weights must sum to 100 (got %s)" % w)
    if not 1 <= s.get("sba", {}).get("term_years", 0) <= 10:
        errs.append("sba.term_years must be 1-10")
    if any(x < 0 for x in s.get("scoring", {}).get("weights", {}).values()):
        errs.append("scoring weights must not be negative")
    d = s.get("dcf", {})
    rate = (d.get("risk_free_fallback", 0) + d.get("size_illiquidity_premium", 0)
            + d.get("industry_premium", 0))
    if rate <= d.get("terminal_growth", 0):
        errs.append("discount rate must exceed dcf.terminal_growth")
    years = d.get("forecast_years")  # zero would crash the DCF with no cash flows
    if not isinstance(years, int) or isinstance(years, bool) or years < 1:
        errs.append("dcf.forecast_years must be a whole number of at least 1")
    return errs
