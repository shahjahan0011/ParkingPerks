"""
Qualification pipeline — the core business logic.

Ported from parking_perks.py with the same two-track structure:
  Payment track: 10+ days with 1+ hour spans, valid payment, no citation
  Permit  track: active permit holder, no citation (no visit threshold)

This module works with structured Python objects (dataclasses) from the
integration layer. Pandas is used internally for efficient computation.
"""

from __future__ import annotations

import pandas as pd

from app.integrations.base import Citation, Payment, PermitHolder, PlateRead


EXCLUDED_SERIES = {"BIKE"}


def run_qualification(
    reads: list[PlateRead],
    payments: list[Payment],
    citations: list[Citation],
    permits: list[PermitHolder],
    min_visits: int = 10,
    min_hours: float = 1.0,
) -> tuple[list[dict], dict]:
    """
    Run the full qualification pipeline.

    Returns:
        qualifiers — list of qualifier dicts, sorted by qualifying_days desc
        summary    — processing funnel counts for the audit log / dashboard
    """
    reads_df = _reads_to_df(reads)
    paid_plates = {p.plate for p in payments}
    cited_plates = {c.plate for c in citations}
    permit_map = _build_permit_map(permits)

    coverage_days = reads_df["local_time"].dt.date.nunique() if not reads_df.empty else 0
    date_min = reads_df["local_time"].dt.date.min() if not reads_df.empty else None
    date_max = reads_df["local_time"].dt.date.max() if not reads_df.empty else None

    # ---- Permit track -------------------------------------------------------
    permit_qualifiers: list[dict] = []
    for plate, holder in permit_map.items():
        if plate not in cited_plates:
            permit_qualifiers.append({
                "plate": plate,
                "name": holder.name,
                "email": holder.email,
                "permit_number": holder.permit_number,
                "qualifying_days": None,
                "avg_hours": None,
                "track": "permit",
            })

    permit_plates_set = set(permit_map.keys())

    # ---- Payment track -------------------------------------------------------
    stage1 = _compute_qualifying_visits(reads_df, min_visits, min_hours)

    stage2_payment_count = 0
    payment_qualifiers: list[dict] = []

    for _, row in stage1.iterrows():
        plate = row["plate"]
        if plate in permit_plates_set:
            continue  # permit track takes precedence
        if plate not in paid_plates:
            continue
        stage2_payment_count += 1
        if plate in cited_plates:
            continue
        payment_qualifiers.append({
            "plate": plate,
            "name": "",
            "email": None,
            "permit_number": None,
            "qualifying_days": int(row["qualifying_days"]),
            "avg_hours": float(row["avg_hours_per_visit"]),
            "track": "payment",
        })

    qualifiers = permit_qualifiers + payment_qualifiers
    qualifiers.sort(key=lambda q: (q["qualifying_days"] or 0), reverse=True)

    summary = {
        "date_range": f"{date_min} to {date_max}" if date_min else "N/A",
        "coverage_days": int(coverage_days),
        "read_rows": len(reads),
        "total_plates": int(reads_df["plate"].nunique()) if not reads_df.empty else 0,
        "payment_plates": len(paid_plates),
        "citation_plates": len(cited_plates),
        "permit_plates": len(permit_map),
        "min_visits": min_visits,
        "min_hours": min_hours,
        "stage1_count": len(stage1),
        "stage2_payment": stage2_payment_count,
        "stage2_permit": len(permit_qualifiers),
        "stage2_total": stage2_payment_count + len(permit_qualifiers),
        "removed_citations": 0,  # already excluded above
        "final": len(qualifiers),
        "missing_emails": [q["plate"] for q in qualifiers if not q["email"]],
    }

    return qualifiers, summary


def _reads_to_df(reads: list[PlateRead]) -> pd.DataFrame:
    if not reads:
        return pd.DataFrame(columns=["plate", "local_time"])
    df = pd.DataFrame([{"plate": r.plate, "local_time": r.timestamp} for r in reads])
    df["local_time"] = pd.to_datetime(df["local_time"])
    df = df.drop_duplicates(subset=["plate", "local_time"], keep="first")
    df = df[df["plate"] != ""]
    return df.reset_index(drop=True)


def _build_permit_map(permits: list[PermitHolder]) -> dict[str, PermitHolder]:
    """Expand multi-plate permit holders into a plate → holder mapping."""
    mapping: dict[str, PermitHolder] = {}
    for holder in permits:
        if holder.series_prefix in EXCLUDED_SERIES:
            continue
        for plate in holder.plates:
            if plate and plate not in mapping:
                mapping[plate] = holder
    return mapping


def _compute_qualifying_visits(
    reads: pd.DataFrame,
    min_visits: int,
    min_hours: float,
) -> pd.DataFrame:
    """Return one row per plate that passes the visit threshold."""
    if reads.empty:
        return pd.DataFrame(columns=["plate", "qualifying_days", "avg_hours_per_visit"])

    reads = reads.copy()
    reads["visit_date"] = reads["local_time"].dt.date

    daily = (
        reads
        .groupby(["plate", "visit_date"])
        .agg(first_read=("local_time", "min"), last_read=("local_time", "max"))
        .reset_index()
    )

    daily["duration_hrs"] = (
        daily["last_read"] - daily["first_read"]
    ).dt.total_seconds() / 3600

    qualifying = daily[daily["duration_hrs"] >= min_hours].copy()

    if qualifying.empty:
        return pd.DataFrame(columns=["plate", "qualifying_days", "avg_hours_per_visit"])

    summary = (
        qualifying
        .groupby("plate")
        .agg(
            qualifying_days=    ("visit_date",   "nunique"),
            avg_hours_per_visit=("duration_hrs", "mean"),
        )
        .reset_index()
    )
    summary["avg_hours_per_visit"] = summary["avg_hours_per_visit"].round(1)
    return summary[summary["qualifying_days"] >= min_visits].copy()
