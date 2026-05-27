"""
csv_store.py — lightweight CSV-based persistence layer.

Replaces SQLite/SQLAlchemy for a system that runs once a month.
All storage lives in backend/data/ (two CSV files, human-readable in Excel).

Files:
    data/draws.csv        — one row per monthly draw (overwritten on redraw)
    data/audit.csv        — append-only event log (never deleted)
    data/missing_emails.csv — plates with no email; resolved by manager

Thread safety: a module-level Lock() guards every read-modify-write.
For a once-a-month system this is more than sufficient.
"""

from __future__ import annotations

import csv
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    # Relative to this file: backend/app/store/ → backend/data/
    return Path(__file__).parent.parent.parent / "data"


def _draws_path() -> Path:
    return _data_dir() / "draws.csv"


def _audit_path() -> Path:
    return _data_dir() / "audit.csv"


def _missing_path() -> Path:
    return _data_dir() / "missing_emails.csv"


_DRAWS_FIELDS = [
    "id", "month", "drawn_at", "drawn_by",
    "num_winners", "pool_size", "is_redraw", "winners_json",
]
_AUDIT_FIELDS = ["id", "timestamp", "action", "month", "actor", "details_json"]
_MISSING_FIELDS = ["id", "month", "plate", "resolved", "email", "resolved_by", "resolved_at"]


def _ensure_data_dir() -> None:
    _data_dir().mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Draws
# ---------------------------------------------------------------------------

def get_all_draws() -> list[dict[str, Any]]:
    path = _draws_path()
    if not path.exists():
        return []
    with _lock, open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # Parse winners_json back to list
    for row in rows:
        row["winners"] = json.loads(row.get("winners_json") or "[]")
        row["is_redraw"] = row.get("is_redraw", "false").lower() == "true"
        row["id"] = int(row["id"])
        row["num_winners"] = int(row.get("num_winners", 1))
        row["pool_size"] = int(row.get("pool_size", 0))
    return rows


def get_draw_by_month(month: str) -> dict[str, Any] | None:
    for row in get_all_draws():
        if row["month"] == month:
            return row
    return None


def save_draw(
    month: str,
    drawn_at: datetime,
    drawn_by: str,
    num_winners: int,
    pool_size: int,
    is_redraw: bool,
    winners: list[dict],
) -> dict[str, Any]:
    """Insert or replace the draw record for this month."""
    _ensure_data_dir()

    with _lock:
        path = _draws_path()
        # Read existing (without lock — already inside lock)
        rows: list[dict] = []
        if path.exists():
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

        existing_idx = next((i for i, r in enumerate(rows) if r["month"] == month), None)
        if existing_idx is not None:
            new_id = int(rows[existing_idx]["id"])
        else:
            new_id = max((int(r["id"]) for r in rows), default=0) + 1

        record = {
            "id": str(new_id),
            "month": month,
            "drawn_at": drawn_at.isoformat(),
            "drawn_by": drawn_by,
            "num_winners": str(num_winners),
            "pool_size": str(pool_size),
            "is_redraw": str(is_redraw).lower(),
            "winners_json": json.dumps(winners),
        }

        if existing_idx is not None:
            rows[existing_idx] = record
        else:
            rows.append(record)

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_DRAWS_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    return {
        "id": new_id,
        "month": month,
        "drawn_at": drawn_at.isoformat(),
        "drawn_by": drawn_by,
        "num_winners": num_winners,
        "pool_size": pool_size,
        "is_redraw": is_redraw,
        "winners": winners,
    }


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def append_audit(action: str, month: str, actor: str, details: dict) -> None:
    """Append one audit event. Never modifies existing rows."""
    _ensure_data_dir()

    with _lock:
        path = _audit_path()
        rows: list[dict] = []
        if path.exists():
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

        new_id = max((int(r["id"]) for r in rows), default=0) + 1
        rows.append({
            "id": str(new_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "month": month,
            "actor": actor,
            "details_json": json.dumps(details),
        })

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_AUDIT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)


# ---------------------------------------------------------------------------
# Missing emails queue
# ---------------------------------------------------------------------------

def get_missing_emails(month: str) -> list[dict[str, Any]]:
    path = _missing_path()
    if not path.exists():
        return []
    with _lock, open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [
        {
            "plate": r["plate"],
            "resolved": r.get("resolved", "false").lower() == "true",
            "email": r.get("email") or None,
        }
        for r in rows
        if r["month"] == month
    ]


def add_missing_email(month: str, plate: str) -> None:
    """Record a plate that needs its email resolved. Idempotent."""
    _ensure_data_dir()

    with _lock:
        path = _missing_path()
        rows: list[dict] = []
        if path.exists():
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

        # Don't add duplicates
        if any(r["month"] == month and r["plate"] == plate for r in rows):
            return

        new_id = max((int(r["id"]) for r in rows), default=0) + 1
        rows.append({
            "id": str(new_id),
            "month": month,
            "plate": plate,
            "resolved": "false",
            "email": "",
            "resolved_by": "",
            "resolved_at": "",
        })

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_MISSING_FIELDS)
            writer.writeheader()
            writer.writerows(rows)


def resolve_missing_email(month: str, plate: str, email: str, resolved_by: str) -> bool:
    """Mark a missing-email entry as resolved. Returns False if not found."""
    _ensure_data_dir()

    with _lock:
        path = _missing_path()
        if not path.exists():
            return False

        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        found = False
        for row in rows:
            if row["month"] == month and row["plate"] == plate and row.get("resolved") != "true":
                row["resolved"] = "true"
                row["email"] = email
                row["resolved_by"] = resolved_by
                row["resolved_at"] = datetime.now(timezone.utc).isoformat()
                found = True
                break

        if not found:
            return False

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_MISSING_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    return True


def has_unresolved_missing_emails(month: str) -> bool:
    return any(
        not item["resolved"]
        for item in get_missing_emails(month)
    )


def get_resolved_email_map(month: str) -> dict[str, str]:
    """plate → email for all resolved entries in this month."""
    return {
        item["plate"]: item["email"]
        for item in get_missing_emails(month)
        if item["resolved"] and item["email"]
    }
