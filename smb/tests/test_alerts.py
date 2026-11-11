"""Telegram alerts with a fake opener. No network, no real sends."""
import contextlib
import io
import unittest
import urllib.error

from biz_screener import alerts, storage
from biz_screener.models import RedFlag, Result


def make(ref="A1", total=80.0, dscr=1.4, flags=()):
    return Result("csv", ref, "laundromat", "48085", 600000.0, 650000.0, dscr, total, 1, list(flags))


class Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body.encode()


class Opener:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def __call__(self, req, timeout=None):
        self.calls.append(req)
        o = self.outcomes.pop(0) if self.outcomes else Resp('{"ok": true}')
        if isinstance(o, Exception):
            raise o
        return o


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.conn = storage.connect(":memory:")
        self.run = storage.save_run(self.conn, False)
        self.nap = []
        self.addCleanup(self.conn.close)

    def send(self, results, opener, **kw):
        storage.save_results(self.conn, self.run, results)
        return alerts.send_alerts(self.conn, results, self.run, "TOKEN123", "42", 70, opener,
                                  sleep=self.nap.append, **kw)

    def test_only_passing_deals_over_threshold_are_sent(self):
        high = RedFlag("low_dscr", "high", "thin")
        op = Opener()
        res = [make("OK"), make("LOW", total=60), make("BLOCKED", flags=[high]), make("NODSCR", dscr=None)]
        self.assertEqual(self.send(res, op), (1, 0))
        self.assertEqual(len(op.calls), 1)

    def test_sent_once_even_after_price_change(self):
        op = Opener()
        self.send([make()], op)
        cheaper = make()
        cheaper.asking_price = 500000.0
        self.assertEqual(self.send([cheaper], op), (0, 0))
        self.assertEqual(len(op.calls), 1)

    def test_message_has_label_and_fits(self):
        text = alerts.render_message(make(flags=[RedFlag("short_lease", "medium", "x" * 6000)]))
        self.assertTrue(text.endswith("Research estimate, not advice."))
        self.assertLess(len(text), 4096)

    def test_one_retry_then_failure_not_recorded(self):
        err = urllib.error.URLError("boom")
        op = Opener(err, err)
        self.assertEqual(self.send([make()], op), (0, 1))
        self.assertEqual(len(op.calls), 2)
        self.assertEqual(self.nap, [2])
        self.assertFalse(storage.already_alerted(self.conn, "csv:A1"))

    def test_retry_can_succeed(self):
        op = Opener(urllib.error.URLError("boom"))
        self.assertEqual(self.send([make()], op), (1, 0))

    def test_telegram_not_ok_is_failure(self):
        op = Opener(Resp('{"ok": false}'), Resp("not json"))
        self.assertEqual(self.send([make()], op), (0, 1))

    def test_request_shape_and_dry_run(self):
        op = Opener()
        self.send([make()], op)
        req = op.calls[0]
        self.assertIn("botTOKEN123/sendMessage", req.full_url)
        self.assertIn(b"chat_id=42", req.data)
        op2 = Opener()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.send([make("B")], op2, dry_run=True), (0, 0))
        self.assertEqual(op2.calls, [])
        self.assertFalse(storage.already_alerted(self.conn, "csv:B"))

    def test_missing_credentials_fail(self):
        with self.assertRaises(ValueError):
            alerts.send_alerts(self.conn, [], self.run, "", "42", 70)


if __name__ == "__main__":
    unittest.main()
