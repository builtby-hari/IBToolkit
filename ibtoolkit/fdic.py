"""Optional FDIC BankFind fetcher (public API, no key).

Source: https://banks.data.fdic.gov/api/ (financials endpoint). Figures are
bank-level call report data in $ thousands, converted here to $ millions. It
supplies only net income, tangible equity, total assets and dividends. Share
count, share price and peer multiples are market data and must come from the
case file. Net income and dividends are year-to-date, so use a Q4 report date
(for example 20241231) for a full year.
"""
import json
from urllib.parse import quote
from urllib.request import urlopen

from .lbo import CaseError

URL = "https://banks.data.fdic.gov/api/financials"
FIELDS = "CERT,REPDTE,ASSET,EQ,INTAN,NETINC,EQCDIV"


def fetch_target(cert, repdte, opener=urlopen):
    """Return {"net_income", "tce", "total_assets", "dividends"} in $ millions.

    `opener` takes a URL and returns a file-like object with JSON bytes, so tests
    can inject a fixture instead of calling the network.
    """
    url = f"{URL}?filters={quote(f'CERT:{cert} AND REPDTE:{repdte}')}&fields={FIELDS}&limit=1"
    with opener(url) as resp:
        rows = json.load(resp).get("data", [])
    if not rows:
        raise CaseError(f"FDIC returned no data for CERT {cert} at {repdte}")
    d = rows[0]["data"]
    missing = [f for f in ("ASSET", "EQ", "INTAN", "NETINC", "EQCDIV") if d.get(f) is None]
    if missing:
        raise CaseError(f"FDIC data for CERT {cert} at {repdte} is missing {', '.join(missing)}")
    return {"net_income": d["NETINC"] / 1000, "tce": (d["EQ"] - d["INTAN"]) / 1000,
            "total_assets": d["ASSET"] / 1000, "dividends": d["EQCDIV"] / 1000}


def as_toml(t, cert, repdte):
    return (f"# Source: FDIC BankFind, CERT {cert}, report date {repdte}, bank-level, $ millions.\n"
            "# Tangible common equity here is total equity less intangibles.\n"
            "[target]\n" + "".join(f"{k} = {v:.1f}\n" for k, v in t.items())
            + "# shares and share_price must come from market data.\n")
