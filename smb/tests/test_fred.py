"""FRED client from saved fixtures. No network."""
import os
import unittest
import urllib.error
from datetime import date

from biz_screener import fred

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "data", "sample")

TODAY = date(2026, 10, 21)


def read(name):
    with open(os.path.join(SAMPLE, name), encoding="utf-8") as f:
        return f.read()


class FakeResp:
    def __init__(self, text):
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.text.encode("utf-8")


def opener_for(text=None, exc=None):
    def opener(url, timeout=None):
        if exc:
            raise exc
        opener.url = url
        return FakeResp(text)
    return opener


class FredTests(unittest.TestCase):
    def test_skips_missing_values_and_converts_percent(self):
        self.assertEqual(fred.parse_latest(read("fred_dprime.csv"), "DPRIME"), (0.0675, "2026-10-13"))

    def test_maintenance_page_fails_clearly(self):
        with self.assertRaisesRegex(fred.FredError, "web page"):
            fred.parse_latest(read("fred_maintenance.html"), "DPRIME")

    def test_wrong_series_empty_and_bad_value(self):
        for text in ("observation_date,DGS10\n2026-01-01,4.2\n", "observation_date,DPRIME\n",
                     "observation_date,DPRIME\n2026-01-01,abc\n", ""):
            with self.assertRaises(fred.FredError):
                fred.parse_latest(text, "DPRIME")

    def test_fetch_uses_series_url(self):
        op = opener_for(read("fred_dprime.csv"))
        self.assertEqual(fred.fetch_series_latest("DPRIME", op)[0], 0.0675)
        self.assertTrue(op.url.endswith("id=DPRIME"))

    def test_fresh_data_returns_rate_and_date(self):
        op = opener_for(read("fred_dprime.csv"))
        self.assertEqual(fred.get_prime(op, TODAY), (0.0675, "2026-10-13"))
        ten = opener_for(read("fred_dprime.csv").replace("DPRIME", "DGS10"))
        self.assertEqual(fred.get_risk_free(ten, TODAY)[0], 0.0675)

    def test_stale_observation_raises(self):
        with self.assertRaisesRegex(fred.FredError, "days old"):
            fred.get_prime(opener_for(read("fred_dprime.csv")), date(2026, 10, 24))
        fred.get_prime(opener_for(read("fred_dprime.csv")), date(2026, 10, 23))  # 10 days is ok

    def test_maintenance_page_and_network_error_raise(self):
        with self.assertRaises(fred.FredError):
            fred.get_prime(opener_for(read("fred_maintenance.html")), TODAY)
        down = opener_for(exc=urllib.error.URLError("no route"))
        with self.assertRaises(fred.FredError):
            fred.get_risk_free(down, TODAY)


if __name__ == "__main__":
    unittest.main()
