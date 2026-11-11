"""Command line entry point. Built so far: `screen <csv>` with optional reports, storage,
live FRED rates and Telegram alerts."""
import argparse
import os
import sys
from typing import List, Optional

from . import alerts, config, fred, ingest, pipeline, report, scoring, storage, teaser

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _settings(path: Optional[str]) -> dict:
    if not path:
        mine = os.path.join(ROOT, "config", "settings.toml")
        path = mine if os.path.exists(mine) else os.path.join(ROOT, "config", "settings.example.toml")
    s = config.load_settings(path)
    errs = config.validate_settings(s)
    if errs:
        raise SystemExit("Invalid settings:\n  " + "\n  ".join(errs))
    return s


def _env(name: str) -> str:
    return os.environ.get(name) or config.load_env(os.path.join(ROOT, ".env")).get(name, "")


def screen(csv_path: str, settings_path: Optional[str] = None, db: Optional[str] = None,
           html: Optional[str] = None, csv_out: Optional[str] = None,
           live_rates: bool = False, alert: bool = False, opener=None, today=None,
           teasers: Optional[str] = None) -> int:
    if alert and not db:
        raise SystemExit("--alert needs --db so each deal is sent only once")
    cfg = _settings(settings_path)
    prime = risk_free = None
    if live_rates:  # network call; unknown or stale rates stop the run
        try:
            prime = fred.get_prime(opener, today)[0]
            risk_free = fred.get_risk_free(opener, today)[0]
        except fred.FredError as e:
            raise SystemExit("Stopped: live rates are unknown (%s). Nothing was scored or sent. "
                             "Retry later or run without --live-rates to use the typed rates "
                             "in settings." % e)
    deals, rejects = ingest.parse_csv(csv_path)
    scores, rows = [], {}
    for listing, periods, adds in deals:
        if listing.category not in cfg["industries"]:
            rejects.append("%s: unknown category %r" % (listing.external_ref, listing.category))
            continue
        sc, val, debt = pipeline.screen_deal(listing, periods, adds, cfg, prime, risk_free)
        scores.append(sc)
        rows[sc.ref] = (val, debt, listing)
    w = max([12] + [len(s.ref) for s in scores])  # Ref column fits the longest ref
    print("%-4s %-*s %-14s %10s %10s %6s %6s  %s" %
          ("Rank", w, "Ref", "Category", "Asking", "Blended", "DSCR", "Score", "Flags"))
    cat = {d[0].external_ref: d[0].category for d in deals}
    ranked = scoring.rank_listings(scores)
    for s in ranked:
        val, debt, _ = rows[s.ref]
        print("%-4d %-*s %-14s %10s %10s %6s %6.1f  %s" % (
            s.rank, w, s.ref, cat[s.ref], "${:,.0f}".format(s.asking_price),
            "${:,.0f}".format(val.blended_value),
            "%.2f" % debt.dscr_lender if debt else "n/a", s.total,
            ", ".join(f.code for f in s.flags) or "-"))
    for r in rejects:
        print("REJECTED " + r, file=sys.stderr)
    results = [pipeline.to_result(rows[s.ref][2], s, rows[s.ref][0], rows[s.ref][1])
               for s in ranked]
    if html:
        report.write_report(report.render_html(results), html)
    if csv_out:
        report.write_report(report.render_csv(results), csv_out)
    if teasers:  # one page per passing deal
        by_ref = {d[0].external_ref: d for d in deals}
        for r in results:
            if r.passes:
                _, periods, adds = by_ref[r.ref]
                val, debt, listing = rows[r.ref]
                teaser.write_teaser(teaser.render_teaser(r, listing, periods, adds, val, debt, cfg),
                                    teasers, r.rank, r.ref)
    if db:
        conn = storage.connect(db)
        try:
            run_id = storage.save_run(conn, False)
            storage.save_results(conn, run_id, results)
            if alert:
                sent, failed = alerts.send_alerts(
                    conn, results, run_id, _env("TELEGRAM_BOT_TOKEN"), _env("TELEGRAM_CHAT_ID"),
                    cfg["alerts"]["min_score_for_alert"], opener)
                print("Alerts sent: %d, failed: %d" % (sent, failed))
        finally:
            conn.close()
    print("\nScreening aid only, built on seller-stated unaudited numbers. Not advice.")
    return 0 if scores or not rejects else 1


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="biz-screener")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("screen", help="score and rank deals from a CSV")
    sp.add_argument("csv")
    sp.add_argument("--settings")
    sp.add_argument("--db", help="SQLite file to store results in")
    sp.add_argument("--html", help="write an HTML report here")
    sp.add_argument("--csv-out", help="write a CSV report here")
    sp.add_argument("--live-rates", action="store_true", help="fetch prime and 10-year from FRED")
    sp.add_argument("--alert", action="store_true", help="send Telegram alerts (needs --db)")
    sp.add_argument("--teasers", help="folder for one-page HTML teasers of passing deals")
    a = p.parse_args(argv)
    return screen(a.csv, a.settings, a.db, a.html, a.csv_out, a.live_rates, a.alert,
                  teasers=a.teasers)


if __name__ == "__main__":
    sys.exit(main())
