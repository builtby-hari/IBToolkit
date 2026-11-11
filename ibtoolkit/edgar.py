"""Optional SEC EDGAR XBRL companyfacts fetcher.

The SEC requires a descriptive User-Agent on every request. It is read only from the
SEC_USER_AGENT environment variable and is never stored in code. The opener is injected
so tests run offline.
"""
import json
import os
import urllib.request

URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# (label, unit, XBRL tags in order of preference)
CONCEPTS = [
    ("revenue", "USD", ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"]),
    ("operating_income", "USD", ["OperatingIncomeLoss"]),
    ("d_and_a", "USD", ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization"]),
    ("net_income", "USD", ["NetIncomeLoss"]),
    ("diluted_eps", "USD/shares", ["EarningsPerShareDiluted"]),
    ("diluted_shares", "shares", ["WeightedAverageNumberOfDilutedSharesOutstanding"]),
    ("cash", "USD", ["CashAndCashEquivalentsAtCarryingValue"]),
    ("debt", "USD", ["LongTermDebt", "LongTermDebtNoncurrent"]),
]


class EdgarError(RuntimeError):
    pass


def user_agent():
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua:
        raise EdgarError("SEC_USER_AGENT is not set. The SEC requires a User-Agent that identifies "
                         "you, for example 'Your Name your-contact'. Set it in your shell first.")
    return ua


def fetch_companyfacts(cik, opener=urllib.request.urlopen):
    cik = str(cik).strip()
    if not cik.isdigit() or len(cik) > 10:
        raise EdgarError(f"CIK must be 1 to 10 digits (got {cik!r})")
    req = urllib.request.Request(URL.format(cik=cik.zfill(10)),
                                 headers={"User-Agent": user_agent(), "Accept": "application/json"})
    with opener(req) as resp:
        return json.loads(resp.read())


def latest_annual(facts, tags, unit):
    """Most recent fiscal-year (10-K, FY) value for the first tag that has one."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        rows = [r for r in gaap.get(tag, {}).get("units", {}).get(unit, [])
                if r.get("form") == "10-K" and r.get("fp") == "FY"]
        if rows:
            r = max(rows, key=lambda r: (r["end"], r.get("filed", "")))
            return {"value": r["val"], "end": r["end"], "tag": tag, "accession": r.get("accn")}
    return None


def summarize(facts):
    """Latest annual values for a few concepts. Values are in raw units (USD, not millions)."""
    return {"entity": facts.get("entityName"), "cik": facts.get("cik"),
            **{label: latest_annual(facts, tags, unit) for label, unit, tags in CONCEPTS}}
