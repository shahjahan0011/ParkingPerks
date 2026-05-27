"""
Qualification pipeline — the core business logic.

Two-track structure:
  Payment track: min_visits days with min_hours span, valid payment, no UBCO citation.
  Permit  track: active permit holder, no UBCO citation (no visit threshold).

FAIRNESS GUARANTEES
-------------------
1. One pool entry per permit holder regardless of plate count.
   A person with 8 registered plates has the same 1-in-N chance as a person
   with 1 plate. Only the permit holder's first plate is entered; all other
   plates are excluded from the payment track too.

2. Citations are UBCO-zone only (CZL_UID_ZONE = 2001 in the T2 Flex query).
   A Vancouver citation does NOT disqualify an UBCO parker.

3. Permit track takes precedence over payment track. If a plate appears in
   both, it enters the pool once via the permit track (which has the email).
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

    # permit_pool_map  — plate → holder for pool entries (one plate per person)
    # all_permit_plates — ALL plates of ALL permit holders (for payment track exclusion)
    permit_pool_map, all_permit_plates = _build_permit_maps(permits)

    coverage_days = reads_df["local_time"].dt.date.nunique() if not reads_df.empty else 0
    date_min = reads_df["local_time"].dt.date.min() if not reads_df.empty else None
    date_max = reads_df["local_time"].dt.date.max() if not reads_df.empty else None

    # ---- Permit track -------------------------------------------------------
    permit_qualifiers: list[dict] = []
    permit_removed_citations = 0
    for plate, holder in permit_pool_map.items():
        if plate in cited_plates:
            permit_removed_citations += 1
            continue
        permit_qualifiers.append({
            "plate": plate,
            "name": holder.name,
            "email": holder.email,
            "permit_number": holder.permit_number,
            "qualifying_days": None,
            "avg_hours": None,
            "track": "permit",
        })

    # ---- Payment track -------------------------------------------------------
    stage1 = _compute_qualifying_visits(reads_df, min_visits, min_hours)

    stage2_payment_count = 0
    payment_removed_citations = 0
    payment_qualifiers: list[dict] = []

    for _, row in stage1.iterrows():
        plate = row["plate"]
        if plate in all_permit_plates:
            continue  # all plates of any permit holder are excluded from payment track
        if plate not in paid_plates:
            continue
        stage2_payment_count += 1
        if plate in cited_plates:
            payment_removed_citations += 1
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
        "permit_plates": len(permit_pool_map),
        "min_visits": min_visits,
        "min_hours": min_hours,
        "stage1_count": len(stage1),
        "stage2_payment": stage2_payment_count,
        "stage2_permit": len(permit_qualifiers),
        "stage2_total": stage2_payment_count + len(permit_qualifiers),
        "removed_citations": permit_removed_citations + payment_removed_citations,
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


def _build_permit_maps(
    permits: list[PermitHolder],
) -> tuple[dict[str, PermitHolder], set[str]]:
    """
    Returns:
        permit_pool_map  — plate → holder, with exactly ONE plate per holder.
                           This is what goes into the draw pool.
        all_permit_plates — every plate associated with any active permit holder,
                           used to exclude permit-holder plates from the payment track.

    FAIRNESS: A permit holder with 8 registered plates gets ONE entry in the draw
    pool, not 8. The "primary" plate is whichever comes first in their plates list.
    All 8 plates are still excluded from the payment track so the same person
    cannot appear twice (once via permit, once via payment).
    """
    permit_pool_map: dict[str, PermitHolder] = {}
    all_permit_plates: set[str] = set()

    for holder in permits:
        if holder.series_prefix in EXCLUDED_SERIES:
            continue

        # Collect ALL plates for payment-track exclusion
        for plate in holder.plates:
            if plate:
                all_permit_plates.add(plate)

        # Add ONE plate to the draw pool (first valid plate not already claimed
        # by another holder — rare but possible with shared vehicles)
        for plate in holder.plates:
            if plate and plate not in permit_pool_map:
                permit_pool_map[plate] = holder
                break  # one entry per person

    return permit_pool_map, all_permit_plates


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
