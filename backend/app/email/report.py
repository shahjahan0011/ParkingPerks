"""
Manager report for the automated monthly draw.

One email to REPORT_RECIPIENTS with:
  - the winners (plate, track, name/email where known)
  - the processing funnel summary + any warnings
  - the full qualifier list attached as CSV (enriched where possible)

Blank name/email in the CSV means "no customer record found" -- agreed
convention so the manager knows a manual lookup is needed.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime


def build_report(
    month: str,
    winners: list[dict],
    summary: dict,
    warnings: list[str],
    qualifiers: list[dict],
    enrich_stats: dict | None = None,
) -> tuple[str, str, bytes]:
    """Returns (subject, body, qualifiers_csv_bytes)."""
    subject = f"Parking Perks {month}: {_winners_line(winners)}"
    body = _build_body(month, winners, summary, warnings, qualifiers, enrich_stats)
    csv_bytes = build_qualifiers_csv(qualifiers)
    return subject, body, csv_bytes


def _winners_line(winners: list[dict]) -> str:
    plates = ", ".join(w["plate"] for w in winners)
    return f"winner{'s' if len(winners) != 1 else ''} {plates}"


def _build_body(
    month: str,
    winners: list[dict],
    summary: dict,
    warnings: list[str],
    qualifiers: list[dict],
    enrich_stats: dict | None,
) -> str:
    lines: list[str] = []
    lines.append(f"Parking Perks draw for {month}")
    lines.append(f"Run completed {datetime.now():%Y-%m-%d %H:%M} (server time).")
    lines.append("")

    lines.append(f"WINNER{'S' if len(winners) != 1 else ''} "
                 f"(drawn from {summary.get('final', len(qualifiers))} qualifiers):")
    for w in winners:
        track = "permit holder" if w.get("track") == "permit" else "pay-per-use"
        contact = []
        if w.get("name"):
            contact.append(w["name"])
        if w.get("email"):
            contact.append(w["email"])
        contact_str = ", ".join(contact) if contact else "NO CONTACT INFO -- manual lookup needed"
        lines.append(f"  {w['plate']}  ({track})  {contact_str}")
    lines.append("")

    lines.append("Processing summary:")
    lines.append(f"  Plate reads analysed : {summary.get('read_rows', 0):,} "
                 f"({summary.get('coverage_days', 0)} days covered, "
                 f"{summary.get('date_range', 'N/A')})")
    lines.append(f"  Unique plates seen   : {summary.get('total_plates', 0):,}")
    lines.append(f"  Payments (T2 Iris)   : {summary.get('payment_plates', 0):,} plates")
    lines.append(f"  Citations (UBCO)     : {summary.get('citation_plates', 0):,} plates "
                 f"({summary.get('removed_citations', 0)} qualifiers removed)")
    lines.append(f"  Permit-track pool    : {summary.get('stage2_permit', 0):,}")
    lines.append(f"  Payment-track pool   : {summary.get('stage2_payment', 0):,} "
                 f"(>= {summary.get('min_visits', '?')} days, "
                 f">= {summary.get('min_hours', '?')}h per day)")
    lines.append(f"  FINAL POOL           : {summary.get('final', 0):,}")
    lines.append("")

    if enrich_stats and enrich_stats.get("needed"):
        lines.append(
            f"Contact lookup (T2 query 4726): {enrich_stats['needed']} plates had no "
            f"email on file; {enrich_stats['found']} matched a customer record "
            f"({enrich_stats['cache_hits']} from cache, "
            f"{enrich_stats['looked_up']} live lookups"
            + (f", {enrich_stats['errors']} lookup errors" if enrich_stats.get("errors") else "")
            + ")."
        )
        lines.append("")

    if warnings:
        lines.append("WARNINGS -- please review:")
        for w in warnings:
            lines.append(f"  ! {w}")
        lines.append("")

    lines.append("The full qualifier list is attached as CSV. Blank name/email = no")
    lines.append("customer record found in T2.")
    lines.append("")
    lines.append("-- Parking Perks automated monthly run")
    return "\n".join(lines)


def build_qualifiers_csv(qualifiers: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([
        "plate", "track", "name", "email", "customer_id",
        "subclassification", "permit_number", "qualifying_days", "avg_hours",
    ])
    for q in qualifiers:
        writer.writerow([
            q.get("plate", ""),
            q.get("track", ""),
            q.get("name", "") or "",
            q.get("email", "") or "",
            q.get("customer_id", "") or "",
            q.get("subclassification", "") or "",
            q.get("permit_number", "") or "",
            q.get("qualifying_days", "") if q.get("qualifying_days") is not None else "",
            q.get("avg_hours", "") if q.get("avg_hours") is not None else "",
        ])
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel opens it cleanly
