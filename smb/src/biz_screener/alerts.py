"""Telegram alerts for deals that pass and score at or above the threshold.

Inputs: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from the environment or .env, Result records,
threshold from settings (alerts.min_score_for_alert), an open storage connection.
Outputs: one message per new deal; sent deals are recorded so they are never sent twice, even
after a price change. Failed sends are retried once, then reported, never raised past
send_alerts. The token is never logged or put in an error message.
"""
import json
import time
import urllib.parse
import urllib.request
from typing import Callable, List, Optional, Tuple

from . import storage
from .models import Result

LABEL = "Research estimate, not advice."
API = "https://api.telegram.org/bot%s/sendMessage"


def select_alert_candidates(conn, results: List[Result], threshold: float) -> List[Result]:
    return [r for r in results if r.passes and r.total >= threshold
            and not storage.already_alerted(conn, r.key)]


def render_message(r: Result) -> str:
    """Short summary only: no full financial statements."""
    watch = "; ".join(f.evidence for f in r.flags[:2])[:500] or "none"
    return ("Deal passed screening: %s (%s, county %s)\nAsking $%s, blended value $%s, "
            "lender DSCR %.2fx, score %.1f\nWatch: %s\n%s" % (
                r.ref, r.category, r.county_fips or "unknown", "{:,.0f}".format(r.asking_price),
                "{:,.0f}".format(r.blended_value), r.dscr, r.total, watch, LABEL))


def send_message(token: str, chat_id: str, text: str, opener: Optional[Callable] = None,
                 retries: int = 1, sleep: Callable[[float], None] = time.sleep) -> bool:
    """POST one message; retry `retries` times after a failure. True only if Telegram says ok."""
    opener = opener or urllib.request.urlopen
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(API % token, data=data)
            with opener(req, timeout=15) as resp:
                if json.loads(resp.read().decode("utf-8")).get("ok") is True:
                    return True
        except (OSError, ValueError):  # network, HTTP and bad-JSON errors; text may hold the token
            pass
        if attempt < retries:
            sleep(2)
    return False


def send_alerts(conn, results: List[Result], run_id: int, token: str, chat_id: str,
                threshold: float, opener: Optional[Callable] = None, dry_run: bool = False,
                sleep: Callable[[float], None] = time.sleep) -> Tuple[int, int]:
    """Return (sent, failed). A dry run sends and records nothing."""
    if not token or not chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    sent = failed = 0
    for r in select_alert_candidates(conn, results, threshold):
        if dry_run:
            print(render_message(r))
            continue
        if send_message(token, chat_id, render_message(r), opener, sleep=sleep):
            storage.mark_alerted(conn, r.key, run_id, r.total)
            sent += 1
        else:
            failed += 1
    return sent, failed
