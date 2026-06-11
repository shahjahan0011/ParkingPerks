"""
reads_db.py -- SQLite store for the continuous Genetec Data Exporter feed,
plus the T2 Flex customer-lookup cache.

One file: backend/data/reads.db
Tables:
    reads(plate, ts, camera)        -- UNIQUE(plate, ts) kills dual-camera dupes
    customer_cache(plate, ...)      -- query-4726 results, so repeat plates are free

Timestamps are stored as ISO "YYYY-MM-DD HH:MM:SS" WALL-CLOCK CAMPUS TIME
(never converted through a timezone -- see the UTC bug in CLAUDE.md).
WAL mode so the always-on ingest writer and the monthly reader coexist.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

_lock = threading.Lock()


def _db_path() -> Path:
    return Path(__file__).parent.parent.parent / "data" / "reads.db"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reads (
            plate TEXT NOT NULL,
            ts    TEXT NOT NULL,
            camera TEXT DEFAULT '',
            received_at TEXT DEFAULT '',
            UNIQUE(plate, ts)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reads_ts ON reads(ts)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS customer_cache (
            plate TEXT PRIMARY KEY,
            found INTEGER NOT NULL,
            name TEXT DEFAULT '',
            email TEXT DEFAULT '',
            primary_id TEXT DEFAULT '',
            subclassification TEXT DEFAULT '',
            active_permit TEXT DEFAULT '',
            fetched_at TEXT NOT NULL
        )
    """)
    return conn


# ---------------------------------------------------------------------------
# Reads feed
# ---------------------------------------------------------------------------

def insert_reads(rows: list[tuple[str, str, str]]) -> int:
    """rows = [(plate, ts_iso, camera)]. Returns how many were new."""
    if not rows:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    with _lock, _connect() as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO reads (plate, ts, camera, received_at) VALUES (?, ?, ?, ?)",
            [(p, t, c, now) for p, t, c in rows],
        )
        return conn.total_changes - before


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    start = f"{year:04d}-{month:02d}-01 00:00:00"
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    end = f"{ny:04d}-{nm:02d}-01 00:00:00"
    return start, end


def month_reads(year: int, month: int) -> list[tuple[str, datetime]]:
    start, end = _month_bounds(year, month)
    with _lock, _connect() as conn:
        cur = conn.execute(
            "SELECT plate, ts FROM reads WHERE ts >= ? AND ts < ? ORDER BY ts",
            (start, end),
        )
        return [
            (plate, datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"))
            for plate, ts in cur.fetchall()
        ]


def month_days_covered(year: int, month: int) -> int:
    start, end = _month_bounds(year, month)
    with _lock, _connect() as conn:
        cur = conn.execute(
            "SELECT COUNT(DISTINCT substr(ts, 1, 10)) FROM reads WHERE ts >= ? AND ts < ?",
            (start, end),
        )
        return cur.fetchone()[0]


def feed_stats() -> dict:
    """Overall feed health for the status endpoint / monthly report."""
    with _lock, _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM reads").fetchone()[0]
        if total == 0:
            return {"rows": 0, "months_covered": [], "first": None, "last": None,
                    "last_received": None}
        first, last = conn.execute("SELECT MIN(ts), MAX(ts) FROM reads").fetchone()
        months = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT substr(ts, 1, 7) FROM reads ORDER BY 1"
            ).fetchall()
        ]
        last_received = conn.execute(
            "SELECT MAX(received_at) FROM reads"
        ).fetchone()[0]
        return {"rows": total, "months_covered": months, "first": first,
                "last": last, "last_received": last_received}


def delete_through_month(year: int, month: int) -> int:
    """Delete all reads up to and including the given month, then compact.
    Called after a month's draw is complete AND its report has been sent."""
    _, end = _month_bounds(year, month)
    with _lock:
        with _connect() as conn:
            cur = conn.execute("DELETE FROM reads WHERE ts < ?", (end,))
            deleted = cur.rowcount
        # VACUUM must run outside a transaction
        conn = _connect()
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()
    return deleted


# ---------------------------------------------------------------------------
# Customer cache (query 4726 results)
# ---------------------------------------------------------------------------

_NOT_FOUND_TTL_DAYS = 30  # re-check unknown plates monthly; found entries are kept


def cache_get_customer(plate: str) -> dict | None:
    """Returns the cached record, or None if not cached / stale not-found."""
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT found, name, email, primary_id, subclassification, "
            "active_permit, fetched_at FROM customer_cache WHERE plate = ?",
            (plate,),
        ).fetchone()
    if row is None:
        return None
    found, name, email, primary_id, subclass, active_permit, fetched_at = row
    if not found:
        try:
            age = datetime.now() - datetime.fromisoformat(fetched_at)
            if age.days >= _NOT_FOUND_TTL_DAYS:
                return None  # stale negative result -- look it up again
        except ValueError:
            return None
    return {
        "found": bool(found), "name": name, "email": email,
        "primary_id": primary_id, "subclassification": subclass,
        "active_permit": active_permit,
    }


def cache_put_customer(plate: str, record: dict | None) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    rec = record or {}
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO customer_cache "
            "(plate, found, name, email, primary_id, subclassification, active_permit, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                plate,
                1 if record else 0,
                rec.get("name", ""),
                rec.get("email", ""),
                rec.get("primary_id", ""),
                rec.get("subclassification", ""),
                rec.get("active_permit", ""),
                now,
            ),
        )
