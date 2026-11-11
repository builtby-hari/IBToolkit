"""FRED client for DPRIME (Bank Prime Loan Rate) and DGS10 (10-Year Treasury).

Uses the public no-key CSV endpoint (fredgraph.csv). Rates come back as percent and are
returned here as fractions (6.75 -> 0.0675). A maintenance HTML page, an empty series or
an unparsable file raises FredError. get_prime and get_risk_free also raise FredError when
the newest observation is more than MAX_AGE_DAYS old. There is no fallback rate: a rate that
cannot be confirmed is unknown and the caller must stop.
"""
import csv
import io
import urllib.request
from datetime import date
from typing import Callable, Optional, Tuple

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=%s"
PRIME = "DPRIME"
TEN_YEAR = "DGS10"
MAX_AGE_DAYS = 10


class FredError(Exception):
    pass


def parse_latest(text: str, series_id: str) -> Tuple[float, str]:
    """Return (rate as fraction, observation date) for the newest non-missing row."""
    if text.lstrip().startswith("<"):
        raise FredError("FRED returned a web page (maintenance or error), not data")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows[0]) != 2 or rows[0][1].strip() != series_id:
        raise FredError("Unexpected FRED file for %s" % series_id)
    for date, value in reversed(rows[1:]):
        value = value.strip()
        if value in ("", "."):  # FRED marks missing days with "."
            continue
        try:
            return float(value) / 100, date.strip()
        except ValueError:
            raise FredError("Bad value %r in %s" % (value, series_id))
    raise FredError("No observations in %s" % series_id)


def fetch_series_latest(series_id: str, opener: Optional[Callable] = None) -> Tuple[float, str]:
    opener = opener or urllib.request.urlopen
    try:
        with opener(URL % series_id, timeout=15) as resp:
            text = resp.read().decode("utf-8-sig")
    except OSError as e:  # URLError, timeouts and HTTP errors all subclass OSError
        raise FredError("Could not reach FRED for %s: %s" % (series_id, type(e).__name__))
    return parse_latest(text, series_id)


def _get(series_id: str, opener: Optional[Callable], today: Optional[date]) -> Tuple[float, str]:
    rate, obs = fetch_series_latest(series_id, opener)
    age = ((today or date.today()) - date.fromisoformat(obs)).days
    if age > MAX_AGE_DAYS:
        raise FredError("Latest %s value is from %s, %d days old (limit %d)"
                        % (series_id, obs, age, MAX_AGE_DAYS))
    return rate, obs


def get_prime(opener: Optional[Callable] = None, today: Optional[date] = None) -> Tuple[float, str]:
    """(rate, observation date) or FredError. `today` is injectable for tests."""
    return _get(PRIME, opener, today)


def get_risk_free(opener: Optional[Callable] = None, today: Optional[date] = None) -> Tuple[float, str]:
    """(rate, observation date) or FredError. `today` is injectable for tests."""
    return _get(TEN_YEAR, opener, today)
