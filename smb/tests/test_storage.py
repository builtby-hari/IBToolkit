"""SQLite storage: dedupe on a stable key, price history, results round trip, alert dedupe."""
import unittest

from biz_screener import storage
from biz_screener.models import RedFlag, Result


def make(ref="A1", price=1000000.0, **kw):
    base = dict(source="csv", ref=ref, category="gas_station", county_fips="48113",
                asking_price=price, blended_value=900000.0, dscr=1.4, total=71.5, rank=1,
                flags=[RedFlag("tabc_transfer", "medium", "Permit transfer")])
    base.update(kw)
    return Result(**base)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.run = storage.save_run(self.conn, fred_stale=True)

    def count(self, table):
        return self.conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def test_same_key_is_one_listing_and_keeps_first_seen(self):
        storage.upsert_listing(self.conn, make(), today="2026-01-01")
        storage.upsert_listing(self.conn, make(), today="2026-02-01")
        self.assertEqual(self.count("listings"), 1)
        self.assertEqual(self.conn.execute("SELECT first_seen, last_seen FROM listings").fetchone(),
                         ("2026-01-01", "2026-02-01"))
        self.assertEqual(self.count("listing_snapshots"), 1)

    def test_price_change_adds_snapshot(self):
        storage.upsert_listing(self.conn, make(), today="2026-01-01")
        storage.upsert_listing(self.conn, make(price=950000.0), today="2026-02-01")
        self.assertEqual(storage.price_history(self.conn, "csv:A1"),
                         [("2026-01-01", 1000000.0), ("2026-02-01", 950000.0)])

    def test_different_source_is_a_different_listing(self):
        storage.upsert_listing(self.conn, make())
        storage.upsert_listing(self.conn, make(source="paste"))
        self.assertEqual(self.count("listings"), 2)

    def test_results_round_trip_with_flags_and_missing_dscr(self):
        storage.save_results(self.conn, self.run, [make(), make("B2", dscr=None, rank=2, flags=[])])
        got = storage.load_results(self.conn, self.run)
        self.assertEqual([r.ref for r in got], ["A1", "B2"])
        self.assertEqual(got[0].flags[0].code, "tabc_transfer")
        self.assertIsNone(got[1].dscr)
        storage.save_results(self.conn, self.run, [make()])  # re-save replaces, no duplicate
        self.assertEqual(self.count("results"), 2)
        self.assertEqual(self.count("red_flags"), 1)

    def test_alert_dedupe_survives_price_change(self):
        storage.save_results(self.conn, self.run, [make()])
        self.assertFalse(storage.already_alerted(self.conn, "csv:A1"))
        storage.mark_alerted(self.conn, "csv:A1", self.run, 71.5)
        storage.mark_alerted(self.conn, "csv:A1", self.run, 71.5)
        storage.save_results(self.conn, self.run, [make(price=800000.0)])
        self.assertTrue(storage.already_alerted(self.conn, "csv:A1"))
        self.assertEqual(self.count("alerts_sent"), 1)
        with self.assertRaises(KeyError):
            storage.mark_alerted(self.conn, "csv:NOPE", self.run, 1.0)


if __name__ == "__main__":
    unittest.main()
