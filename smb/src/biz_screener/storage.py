"""SQLite persistence for screened listings, results, runs and sent alerts.

Inputs: Result records from the pipeline, a database path (default data/biz_screener.db).
Outputs: rows written, price history, alert dedupe lookups.
Listings are keyed on "source:external_ref", so re-importing the same deal updates it
instead of duplicating it. This is a smaller schema than the full plan in
docs/ARCHITECTURE.md: it stores results, not every intermediate figure.
"""
import sqlite3
from datetime import date, datetime, timezone
from typing import List, Optional, Tuple

from .models import RedFlag, Result

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL, external_ref TEXT NOT NULL, category TEXT NOT NULL,
    county_fips TEXT NOT NULL, asking_price REAL NOT NULL,
    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS listing_snapshots (
    id INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    captured_on TEXT NOT NULL, asking_price REAL NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY, started_at TEXT NOT NULL,
    fred_stale INTEGER NOT NULL, cbp_stale INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    run_id INTEGER NOT NULL REFERENCES runs(id),
    rank INTEGER NOT NULL, total REAL NOT NULL, blended_value REAL NOT NULL,
    dscr REAL, UNIQUE (listing_id, run_id));
CREATE TABLE IF NOT EXISTS red_flags (
    id INTEGER PRIMARY KEY,
    result_id INTEGER NOT NULL REFERENCES results(id),
    code TEXT NOT NULL, severity TEXT NOT NULL, evidence TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alerts_sent (
    id INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL UNIQUE REFERENCES listings(id),
    run_id INTEGER NOT NULL REFERENCES runs(id),
    sent_at TEXT NOT NULL, score REAL NOT NULL);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def save_run(conn: sqlite3.Connection, fred_stale: bool, cbp_stale: bool = False) -> int:
    cur = conn.execute("INSERT INTO runs (started_at, fred_stale, cbp_stale) VALUES (?, ?, ?)",
                       (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        int(fred_stale), int(cbp_stale)))
    conn.commit()
    return cur.lastrowid


def upsert_listing(conn: sqlite3.Connection, r: Result, today: Optional[str] = None) -> int:
    """Keep first_seen, update last_seen; add a price snapshot when the price changed."""
    today = today or date.today().isoformat()
    row = conn.execute("SELECT id, asking_price FROM listings WHERE key = ?", (r.key,)).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO listings (key, source, external_ref, category, county_fips, asking_price,"
            " first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (r.key, r.source, r.ref, r.category, r.county_fips, r.asking_price, today, today))
        lid = cur.lastrowid
    else:
        lid = row[0]
        conn.execute("UPDATE listings SET category = ?, county_fips = ?, asking_price = ?,"
                     " last_seen = ? WHERE id = ?",
                     (r.category, r.county_fips, r.asking_price, today, lid))
    last = conn.execute("SELECT asking_price FROM listing_snapshots WHERE listing_id = ?"
                        " ORDER BY id DESC LIMIT 1", (lid,)).fetchone()
    if last is None or last[0] != r.asking_price:
        conn.execute("INSERT INTO listing_snapshots (listing_id, captured_on, asking_price)"
                     " VALUES (?, ?, ?)", (lid, today, r.asking_price))
    conn.commit()
    return lid


def save_results(conn: sqlite3.Connection, run_id: int, results: List[Result]) -> None:
    """Store every result of one run. Re-saving a (listing, run) replaces it."""
    for r in results:
        lid = upsert_listing(conn, r)
        conn.execute("DELETE FROM red_flags WHERE result_id IN"
                     " (SELECT id FROM results WHERE listing_id = ? AND run_id = ?)", (lid, run_id))
        conn.execute("DELETE FROM results WHERE listing_id = ? AND run_id = ?", (lid, run_id))
        cur = conn.execute(
            "INSERT INTO results (listing_id, run_id, rank, total, blended_value, dscr)"
            " VALUES (?, ?, ?, ?, ?, ?)", (lid, run_id, r.rank, r.total, r.blended_value, r.dscr))
        conn.executemany(
            "INSERT INTO red_flags (result_id, code, severity, evidence) VALUES (?, ?, ?, ?)",
            [(cur.lastrowid, f.code, f.severity, f.evidence) for f in r.flags])
    conn.commit()


def load_results(conn: sqlite3.Connection, run_id: int) -> List[Result]:
    out = []
    rows = conn.execute(
        "SELECT res.id, l.source, l.external_ref, l.category, l.county_fips, l.asking_price,"
        " res.blended_value, res.dscr, res.total, res.rank FROM results res"
        " JOIN listings l ON l.id = res.listing_id WHERE res.run_id = ? ORDER BY res.rank",
        (run_id,)).fetchall()
    for rid, *rest in rows:
        flags = [RedFlag(*f) for f in conn.execute(
            "SELECT code, severity, evidence FROM red_flags WHERE result_id = ? ORDER BY id",
            (rid,))]
        out.append(Result(*rest, flags=flags))
    return out


def price_history(conn: sqlite3.Connection, key: str) -> List[Tuple[str, float]]:
    return conn.execute(
        "SELECT s.captured_on, s.asking_price FROM listing_snapshots s"
        " JOIN listings l ON l.id = s.listing_id WHERE l.key = ? ORDER BY s.id", (key,)).fetchall()


def already_alerted(conn: sqlite3.Connection, key: str) -> bool:
    return conn.execute("SELECT 1 FROM alerts_sent a JOIN listings l ON l.id = a.listing_id"
                        " WHERE l.key = ?", (key,)).fetchone() is not None


def mark_alerted(conn: sqlite3.Connection, key: str, run_id: int, score: float) -> None:
    """Record a sent alert. Raises KeyError for an unknown listing."""
    row = conn.execute("SELECT id FROM listings WHERE key = ?", (key,)).fetchone()
    if row is None:
        raise KeyError(key)
    conn.execute("INSERT OR IGNORE INTO alerts_sent (listing_id, run_id, sent_at, score)"
                 " VALUES (?, ?, ?, ?)", (row[0], run_id,
                 datetime.now(timezone.utc).isoformat(timespec="seconds"), score))
    conn.commit()
