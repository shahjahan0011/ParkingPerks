"""
Automated monthly Parking Perks run -- invoked by Windows Task Scheduler.

SCHEDULE IT DAILY (e.g. 06:30), not monthly. Every run:
  - figures out the target month (the previous calendar month, campus time)
  - if that month is drawn AND reported -> exits silently (zero cost)
  - if drawn but the report email failed earlier -> re-sends the report only
  - otherwise: coverage gate -> fetch -> qualify -> enrich -> draw -> save ->
    report email -> reads cleanup. Any failure sends an alert email and exits
    non-zero; tomorrow's run retries automatically.

The draw can never happen twice for one month, and a failed email can never
lose a draw (draw is persisted first; the report is retried independently).

Usage:
    python monthly_run.py                     # normal scheduled behaviour
    python monthly_run.py --month 2026-04     # specific month
    python monthly_run.py --winners 3         # override NUM_WINNERS once
    python monthly_run.py --resend-report     # force re-send of the report
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import settings
from app.core.draw import secure_draw
from app.core.enrich import enrich_qualifiers
from app.core.qualify import run_qualification
from app.core.sources import SourceError, fetch_all_sources
from app.email.report import build_qualifiers_csv, build_report
from app.email.sender import EmailNotConfigured, send_email
from app.store import csv_store, reads_db

LOG_FILE = Path(__file__).parent / "data" / "monthly_run.log"
QUALIFIERS_DIR = Path(__file__).parent / "data"

REPORT_SENT_ACTION = "report_sent"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger("monthly_run")


def previous_month() -> tuple[int, int]:
    now = datetime.now(ZoneInfo(settings.campus_timezone))
    first = now.replace(day=1)
    prev = first - timedelta(days=1)
    return prev.year, prev.month


def recipients() -> list[str]:
    return [r.strip() for r in settings.report_recipients.split(",") if r.strip()]


def alert(subject: str, body: str) -> None:
    """Failure alert -- best effort; never raises."""
    try:
        send_email(recipients(), f"[Parking Perks ALERT] {subject}", body)
    except Exception as exc:
        logger.error("Could not send alert email: %s", exc)


def qualifiers_csv_path(month_str: str) -> Path:
    return QUALIFIERS_DIR / f"qualifiers_{month_str}.csv"


async def run(year: int, month: int, num_winners: int, resend_only: bool) -> int:
    month_str = f"{year}-{month:02d}"

    # Step 0 -- every run (daily): pull new Genetec report emails into
    # reads.db, so data accumulates continuously and gaps surface early.
    pull_failed = _pull_mail_reports()

    existing_draw = csv_store.get_draw_by_month(month_str)
    report_sent = csv_store.has_audit(REPORT_SENT_ACTION, month_str)

    # ---- Nothing to do -----------------------------------------------------
    if existing_draw and report_sent and not resend_only:
        logger.info("%s already drawn and reported -- nothing to do.", month_str)
        return 0

    # ---- Draw exists, only the report is missing ---------------------------
    if existing_draw and (not report_sent or resend_only):
        logger.info("%s drawn but report %s -- sending report only.",
                    month_str, "re-requested" if resend_only else "not yet sent")
        return _send_report_for_existing(month_str, existing_draw)

    # ---- Full run -----------------------------------------------------------
    logger.info("Starting full run for %s", month_str)

    if pull_failed:
        msg = (f"Could not pull the daily reads-report emails from Gmail before "
               f"the {month_str} draw. The draw was NOT run (the reads data "
               "may be incomplete). This will retry tomorrow.")
        logger.error(msg)
        alert(f"{month_str}: Gmail report pull failed", msg)
        return 1

    # Coverage gate: never draw on a partial month of reads.
    days = reads_db.month_days_covered(year, month)
    if days < settings.min_coverage_days:
        msg = (
            f"Plate reads coverage for {month_str} is only {days} day(s); "
            f"need at least {settings.min_coverage_days}. The draw was NOT run. "
            "Check the Genetec Data Exporter feed (or upload a Security Desk "
            "export through the web tool). This will retry tomorrow."
        )
        logger.error(msg)
        alert(f"{month_str}: reads coverage too low ({days} days)", msg)
        return 1

    try:
        reads, payments, citations, permits = await fetch_all_sources(year, month)
    except SourceError as exc:
        msg = (f"Data source '{exc.source}' failed for {month_str}:\n\n{exc}\n\n"
               "The draw was NOT run. This will retry tomorrow.")
        logger.error(msg)
        alert(f"{month_str}: {exc.source} failed", msg)
        return 1

    qualifiers, summary = run_qualification(
        reads, payments, citations, permits,
        min_visits=settings.min_visits,
        min_hours=settings.min_hours,
    )

    if not qualifiers:
        msg = f"Qualification produced ZERO qualifiers for {month_str}. Draw NOT run."
        logger.error(msg)
        alert(f"{month_str}: zero qualifiers", msg)
        return 1

    enrich_stats = await enrich_qualifiers(qualifiers)

    warnings = _build_warnings(summary)

    n = min(num_winners, len(qualifiers))
    winners = secure_draw(qualifiers, n)
    drawn_at = datetime.now(ZoneInfo("UTC"))

    # Persist FIRST -- the draw must survive any email failure.
    csv_store.save_draw(
        month=month_str, drawn_at=drawn_at, drawn_by="monthly_run",
        num_winners=n, pool_size=len(qualifiers), is_redraw=False,
        winners=winners,
    )
    csv_store.append_audit(
        action="draw", month=month_str, actor="monthly_run",
        details={"winners": [w["plate"] for w in winners],
                 "pool_size": len(qualifiers),
                 "min_visits": settings.min_visits,
                 "min_hours": settings.min_hours,
                 "enrich": enrich_stats},
    )
    qualifiers_csv_path(month_str).write_bytes(build_qualifiers_csv(qualifiers))
    logger.info("Draw saved for %s: %s (pool %d)",
                month_str, [w["plate"] for w in winners], len(qualifiers))

    # Report email (independent of the draw -- retried tomorrow on failure).
    subject, body, csv_bytes = build_report(
        month_str, winners, summary, warnings, qualifiers, enrich_stats,
    )
    try:
        send_email(recipients(), subject, body,
                   attachments=[(f"qualifiers_{month_str}.csv", csv_bytes, "text/csv")])
    except Exception as exc:
        logger.error("Report email failed (draw IS saved): %s", exc)
        alert(f"{month_str}: draw done but report email failed",
              f"The draw for {month_str} completed and is saved, but the report "
              f"email failed:\n\n{exc}\n\nTomorrow's run will re-send the report.")
        return 1

    csv_store.append_audit(action=REPORT_SENT_ACTION, month=month_str,
                           actor="monthly_run", details={"to": recipients()})
    logger.info("Report sent to %s", recipients())

    _cleanup_reads(year, month, month_str)
    return 0


def _send_report_for_existing(month_str: str, draw_row: dict) -> int:
    """Re-send the report using the saved draw + saved qualifiers CSV."""
    csv_path = qualifiers_csv_path(month_str)
    csv_bytes = csv_path.read_bytes() if csv_path.exists() else b"plate\n"
    winners = draw_row["winners"]

    body = (
        f"Parking Perks draw for {month_str} (re-sent report)\n\n"
        f"Drawn at {draw_row['drawn_at']} from a pool of {draw_row['pool_size']:,}.\n\n"
        "WINNERS:\n"
        + "\n".join(
            f"  {w['plate']}  ({w.get('track', '?')})  "
            f"{w.get('name') or ''} {w.get('email') or 'NO CONTACT INFO -- manual lookup needed'}"
            for w in winners
        )
        + "\n\nThe full qualifier list is attached as CSV.\n\n"
        "-- Parking Perks automated monthly run"
    )
    try:
        send_email(
            recipients(),
            f"Parking Perks {month_str}: winner{'s' if len(winners) != 1 else ''} "
            + ", ".join(w["plate"] for w in winners),
            body,
            attachments=[(f"qualifiers_{month_str}.csv", csv_bytes, "text/csv")],
        )
    except Exception as exc:
        logger.error("Report re-send failed: %s", exc)
        alert(f"{month_str}: report email still failing", str(exc))
        return 1

    csv_store.append_audit(action=REPORT_SENT_ACTION, month=month_str,
                           actor="monthly_run", details={"to": recipients(),
                                                         "resend": True})
    year, month = int(month_str[:4]), int(month_str[5:7])
    _cleanup_reads(year, month, month_str)
    logger.info("Report re-sent for %s", month_str)
    return 0


def _pull_mail_reports() -> bool:
    """Ingest new daily report emails. Returns True if the pull FAILED
    (auth/connectivity) -- per-message failures are retried next run and do
    not count as a pull failure."""
    from app.integrations.mail_reports import pull_reads_reports

    if settings.email_backend != "gmail":
        logger.info("Mail pull skipped: EMAIL_BACKEND is not gmail")
        return False
    try:
        pull_reads_reports()
        return False
    except Exception as exc:
        logger.error("Mail pull failed: %s", exc)
        return True


def _cleanup_reads(year: int, month: int, month_str: str) -> None:
    """Keep the reads DB small: once a month is drawn + reported, its reads
    (and anything older) are no longer needed."""
    try:
        deleted = reads_db.delete_through_month(year, month)
        logger.info("Reads cleanup: deleted %d rows up to end of %s", deleted, month_str)
    except Exception as exc:
        logger.warning("Reads cleanup failed (not critical): %s", exc)


def _build_warnings(summary: dict) -> list[str]:
    warnings: list[str] = []
    coverage = summary.get("coverage_days", 0)
    if coverage and coverage < 28:
        warnings.append(
            f"Plate reads only cover {coverage} days of the month -- check the "
            "Data Exporter feed for gaps."
        )
    if summary.get("citation_plates", 0) == 0:
        warnings.append("Zero citations found this month -- verify the citations "
                        "query if that seems unlikely.")
    if summary.get("stage2_payment", 0) == 0:
        warnings.append("No payment-track qualifiers at all -- possible "
                        "payments/plate-matching problem.")
    return warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Parking Perks automated monthly run")
    parser.add_argument("--month", help="Target month YYYY-MM (default: previous month)")
    parser.add_argument("--winners", type=int, default=None,
                        help=f"Number of winners (default: NUM_WINNERS={settings.num_winners})")
    parser.add_argument("--resend-report", action="store_true",
                        help="Re-send the report for an already-drawn month")
    args = parser.parse_args()

    if args.month:
        try:
            year, month = int(args.month[:4]), int(args.month[5:7])
            assert 1 <= month <= 12
        except (ValueError, AssertionError):
            print("--month must look like 2026-04")
            return 2
    else:
        year, month = previous_month()

    num_winners = args.winners if args.winners else settings.num_winners
    if not (1 <= num_winners <= 50):
        print("--winners must be 1-50")
        return 2

    try:
        return asyncio.run(run(year, month, num_winners, args.resend_report))
    except EmailNotConfigured as exc:
        logger.error("Email is not configured: %s", exc)
        print(f"EMAIL NOT CONFIGURED: {exc}\n"
              "Set EMAIL_BACKEND + Gmail/SMTP settings in .env "
              "(see gmail_auth_setup.py).")
        return 1
    except Exception:
        logger.exception("Unhandled error in monthly run")
        alert("unhandled error in monthly run",
              "See data/monthly_run.log on the server for the full traceback.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
