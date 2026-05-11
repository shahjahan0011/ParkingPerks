"""
Parking Perks - Monthly Qualifier Report
=========================================
Produces an Excel report of plates that:
  1. Visited campus on 10+ separate days, each stay > 1 hour
  2. Have a valid payment on record for the month
  3. Did NOT receive a parking citation

Usage:
  python parking_perks.py \
    --reads   "April_Plate_Reads.xlsx" \
    --payments "April_Payments.csv" \
    --citations "Citations_April.xls" \
    [--permits  "Active_Permits.csv"] \
    [--output   "Parking_Perks_April_2026.xlsx"] \
    [--min-visits 10] \
    [--min-hours  1]
"""

import argparse
import sys
import os
from datetime import datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


# ── Plate normalisation ────────────────────────────────────────────────────────
def normalise_plate(raw) -> str:
    """
    Strip formatting differences so plates match across all three files.
    Plate reads:  SH9068  (bare)
    Payments:     ="SH9068"  (Excel formula-quote wrapper)
    Citations:    BC-SH9068-NA  (province prefix + -NA suffix)
    """
    if pd.isna(raw):
        return ""
    s = str(raw).strip().upper()
    s = s.lstrip('="').rstrip('"')          # remove ="..." wrapper
    s = s.replace("-NA", "").replace("-", " ").replace(" ", "")
    # strip leading province codes (2-letter prefix before the plate token)
    # e.g. BCSH9068 → SH9068  but only if it starts with a 2-letter province
    provinces = {"BC","AB","SK","MB","ON","QC","NB","NS","PE","NL","YT","NT","NU"}
    if len(s) > 2 and s[:2] in provinces:
        s = s[2:]
    return s


# ── Loaders ───────────────────────────────────────────────────────────────────
def load_plate_reads(path: str) -> pd.DataFrame:
    """Load plate reads XLSX. Real header is on row 2 (index 1)."""
    df = pd.read_excel(path, header=1)
    df.columns = df.columns.str.strip()
    df = df.rename(columns={"Local time (PDT)": "local_time", "Plate number": "plate_raw"})
    df["plate"] = df["plate_raw"].apply(normalise_plate)
    df = df[df["plate"] != ""]
    df["local_time"] = pd.to_datetime(df["local_time"], format="%m/%d/%Y, %I:%M:%S %p", errors="coerce")
    df = df.dropna(subset=["local_time"])
    df["date"] = df["local_time"].dt.date
    return df[["plate", "local_time", "date"]]


def load_payments(path: str) -> pd.DataFrame:
    """Load payments CSV. Plate field uses =\"...\" Excel quoting."""
    df = pd.read_csv(path, dtype=str)
    df.columns = df.columns.str.strip()
    df["plate"] = df["License Plate"].apply(normalise_plate)
    return df[["plate"]].drop_duplicates()


def load_citations(path: str) -> pd.DataFrame:
    """Load citations XLS. Real header is on row 10 (index 9)."""
    df = pd.read_excel(path, engine="xlrd", header=9)
    df.columns = df.columns.str.strip()
    df = df.rename(columns={"License #": "plate_raw"})
    df = df.dropna(subset=["plate_raw"])
    df["plate"] = df["plate_raw"].apply(normalise_plate)
    return df[["plate"]].drop_duplicates()


def load_permits(path: str) -> pd.DataFrame:
    """
    Load optional permit holders file.
    Expected columns: plate (or License Plate), permit_number, name
    Adjust column names here if your export uses different headers.
    """
    df = pd.read_csv(path, dtype=str) if path.endswith(".csv") else pd.read_excel(path, dtype=str)
    df.columns = df.columns.str.strip()

    plate_col = next((c for c in df.columns if "plate" in c.lower() or "licence" in c.lower() or "license" in c.lower()), None)
    permit_col = next((c for c in df.columns if "permit" in c.lower()), None)
    name_col   = next((c for c in df.columns if "name" in c.lower()), None)

    out = pd.DataFrame()
    if plate_col:
        out["plate"] = df[plate_col].apply(normalise_plate)
    if permit_col:
        out["permit_number"] = df[permit_col].fillna("").astype(str)
    if name_col:
        out["name"] = df[name_col].fillna("").astype(str)
    return out.drop_duplicates(subset=["plate"]) if not out.empty else out


# ── Core logic ────────────────────────────────────────────────────────────────
def compute_qualifying_visits(reads: pd.DataFrame, min_visits: int, min_hours: float) -> pd.DataFrame:
    """
    For each plate, group reads by calendar date.
    A visit qualifies if (last_read - first_read) >= min_hours.
    Return plates with >= min_visits qualifying days, plus visit stats.
    """
    daily = (
        reads.groupby(["plate", "date"])
        .agg(first_read=("local_time", "min"), last_read=("local_time", "max"))
        .reset_index()
    )
    daily["duration_hrs"] = (daily["last_read"] - daily["first_read"]).dt.total_seconds() / 3600
    qualifying = daily[daily["duration_hrs"] >= min_hours]

    summary = (
        qualifying.groupby("plate")
        .agg(
            qualifying_days=("date", "count"),
            total_days_on_campus=("date", "count"),    # same as qualifying here
            avg_hours_per_visit=("duration_hrs", "mean"),
        )
        .reset_index()
    )
    summary = summary[summary["qualifying_days"] >= min_visits]
    summary["avg_hours_per_visit"] = summary["avg_hours_per_visit"].round(1)
    return summary


# ── Report writer ─────────────────────────────────────────────────────────────
HEADER_FILL   = PatternFill("solid", start_color="1F4E79")
HEADER_FONT   = Font(name="Arial", bold=True, color="FFFFFF", size=11)
TITLE_FONT    = Font(name="Arial", bold=True, size=14, color="1F4E79")
BODY_FONT     = Font(name="Arial", size=10)
ALT_FILL      = PatternFill("solid", start_color="EBF3FB")
BORDER_SIDE   = Side(style="thin", color="B8CCE4")
CELL_BORDER   = Border(left=BORDER_SIDE, right=BORDER_SIDE, top=BORDER_SIDE, bottom=BORDER_SIDE)
GREEN_FONT    = Font(name="Arial", size=10, color="375623")
GREEN_FILL    = PatternFill("solid", start_color="E2EFDA")


def style_header_row(ws, row, cols):
    for col in range(1, cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.font    = HEADER_FONT
        cell.fill    = HEADER_FILL
        cell.border  = CELL_BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def write_report(qualifiers: pd.DataFrame, output_path: str, month_label: str, summary_stats: dict):
    wb = Workbook()

    # ── Sheet 1: Qualifiers ───────────────────────────────────────────────────
    ws = wb.active
    ws.title = "Parking Perks Qualifiers"
    ws.freeze_panes = "A4"

    ws.merge_cells("A1:G1")
    ws["A1"] = f"🏆  Parking Perks — Qualifying Participants  |  {month_label}"
    ws["A1"].font = TITLE_FONT
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 32

    ws.merge_cells("A2:G2")
    ws["A2"] = (
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}    "
        f"Total qualifiers: {len(qualifiers)}    "
        f"Criteria: 10+ visits of 1+ hour | Valid payment/permit | No citations"
    )
    ws["A2"].font = Font(name="Arial", size=9, italic=True, color="595959")
    ws["A2"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[2].height = 18

    headers = ["#", "Plate Number", "Name", "Permit Number", "Visits This Month", "Avg Stay (hrs)", "Payment Source"]
    for col, h in enumerate(headers, 1):
        ws.cell(row=3, column=col, value=h)
    style_header_row(ws, 3, len(headers))
    ws.row_dimensions[3].height = 28

    for i, (_, row) in enumerate(qualifiers.iterrows(), 1):
        r = i + 3
        data = [
            i,
            row["plate"],
            row.get("name", ""),
            row.get("permit_number", ""),
            row["qualifying_days"],
            row["avg_hours_per_visit"],
            row.get("payment_source", "Payment"),
        ]
        fill = ALT_FILL if i % 2 == 0 else None
        for col, val in enumerate(data, 1):
            cell = ws.cell(row=r, column=col, value=val)
            cell.font   = GREEN_FONT if row.get("payment_source") == "Permit" else BODY_FONT
            cell.fill   = GREEN_FILL if row.get("payment_source") == "Permit" else (fill or PatternFill())
            cell.border = CELL_BORDER
            cell.alignment = Alignment(horizontal="center" if col in (1, 5, 6) else "left", vertical="center")
        ws.row_dimensions[r].height = 20

    col_widths = [5, 16, 28, 18, 20, 18, 16]
    for col, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = w

    # ── Sheet 2: Summary ──────────────────────────────────────────────────────
    ws2 = wb.create_sheet("Processing Summary")
    ws2.column_dimensions["A"].width = 38
    ws2.column_dimensions["B"].width = 20

    ws2["A1"] = "Parking Perks — Processing Summary"
    ws2["A1"].font = TITLE_FONT
    ws2.row_dimensions[1].height = 30

    rows = [
        ("Month", month_label),
        ("Run date", datetime.now().strftime("%Y-%m-%d %H:%M")),
        (None, None),
        ("── Stage 1: Visit behaviour ──", None),
        ("Total unique plates in reads file", summary_stats["total_plates"]),
        ("Plates with 10+ qualifying visits (≥1 hr)", summary_stats["stage1"]),
        (None, None),
        ("── Stage 2: Valid payment / permit ──", None),
        ("Plates matched to payment record", summary_stats["stage2_payment"]),
        ("Plates matched to permit (if file provided)", summary_stats["stage2_permit"]),
        ("Plates passing stage 2 (either source)", summary_stats["stage2_total"]),
        (None, None),
        ("── Stage 3: No citations ──", None),
        ("Plates removed (had citation)", summary_stats["removed_citations"]),
        ("FINAL QUALIFIERS", summary_stats["final"]),
    ]
    for i, (label, value) in enumerate(rows, 2):
        ws2.cell(row=i, column=1, value=label).font = Font(name="Arial", size=10, bold=label and label.startswith("──") or label == "FINAL QUALIFIERS")
        if value is not None:
            cell = ws2.cell(row=i, column=2, value=value)
            cell.font = Font(name="Arial", size=10, bold=(label == "FINAL QUALIFIERS"), color="1F4E79" if label == "FINAL QUALIFIERS" else "000000")
            cell.alignment = Alignment(horizontal="right")

    # Legend note
    ws2.cell(row=len(rows) + 4, column=1, value="Note: Green rows on the Qualifiers sheet = permit holders.").font = Font(name="Arial", size=9, italic=True, color="595959")

    wb.save(output_path)
    print(f"\n✅  Report saved to: {output_path}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Parking Perks monthly qualifier report")
    parser.add_argument("--reads",     required=True,  help="Plate reads file (.xlsx)")
    parser.add_argument("--payments",  required=True,  help="Payments file (.csv)")
    parser.add_argument("--citations", required=True,  help="Citations file (.xls or .xlsx)")
    parser.add_argument("--permits",   default=None,   help="Optional: active permit holders file (.csv or .xlsx)")
    parser.add_argument("--output",    default="Parking_Perks_Report.xlsx", help="Output filename")
    parser.add_argument("--min-visits",type=int,   default=10,  help="Minimum qualifying visits (default: 10)")
    parser.add_argument("--min-hours", type=float, default=1.0, help="Minimum hours per visit (default: 1.0)")
    args = parser.parse_args()

    # Derive month label from output name or reads file
    month_label = os.path.basename(args.reads).replace("_", " ").replace(".xlsx", "").replace(".xls", "")

    print("Loading files...")
    reads     = load_plate_reads(args.reads)
    payments  = load_payments(args.payments)
    citations = load_citations(args.citations)
    permits   = load_permits(args.permits) if args.permits else pd.DataFrame(columns=["plate"])

    total_plates = reads["plate"].nunique()
    print(f"  Plate reads:  {len(reads):,} rows | {total_plates:,} unique plates")
    print(f"  Payments:     {len(payments):,} unique plates")
    print(f"  Citations:    {len(citations):,} unique plates")
    if not permits.empty:
        print(f"  Permits:      {len(permits):,} unique plates")

    # Stage 1
    print(f"\nStage 1 — filtering plates with {args.min_visits}+ visits of {args.min_hours}+ hours...")
    stage1 = compute_qualifying_visits(reads, args.min_visits, args.min_hours)
    print(f"  → {len(stage1):,} plates qualify")

    # Stage 2 — payments
    paid_plates   = set(payments["plate"])
    permit_plates = set(permits["plate"]) if not permits.empty else set()

    stage1["has_payment"] = stage1["plate"].isin(paid_plates)
    stage1["has_permit"]  = stage1["plate"].isin(permit_plates)
    stage1["valid_payment"] = stage1["has_payment"] | stage1["has_permit"]

    stage2_payment = stage1["has_payment"].sum()
    stage2_permit  = stage1["has_permit"].sum()
    stage2 = stage1[stage1["valid_payment"]].copy()
    print(f"\nStage 2 — cross-referencing payments/permits...")
    print(f"  → {len(stage2):,} plates have valid payment or permit")

    # Stage 3 — citations
    cited_plates = set(citations["plate"])
    stage3 = stage2[~stage2["plate"].isin(cited_plates)].copy()
    removed = len(stage2) - len(stage3)
    print(f"\nStage 3 — removing cited plates...")
    print(f"  → {removed} plates removed | {len(stage3):,} final qualifiers")

    if len(stage3) == 0:
        print("\n⚠️  No qualifying plates found. Check that the reads file covers the full month.")
        print("   (This sample covers only Apr 24–30; a full month of reads is needed for 10+ visit filtering.)")

    # Enrich with permit info
    stage3["payment_source"] = stage3.apply(
        lambda r: "Permit" if r["has_permit"] else "Payment", axis=1
    )
    if not permits.empty and "name" in permits.columns:
        stage3 = stage3.merge(permits[["plate","name"] + (["permit_number"] if "permit_number" in permits.columns else [])], on="plate", how="left")
    else:
        stage3["name"] = ""
        stage3["permit_number"] = ""

    stage3 = stage3.sort_values("qualifying_days", ascending=False).reset_index(drop=True)

    summary_stats = {
        "total_plates":     total_plates,
        "stage1":           len(stage1),
        "stage2_payment":   int(stage2_payment),
        "stage2_permit":    int(stage2_permit),
        "stage2_total":     len(stage2),
        "removed_citations":removed,
        "final":            len(stage3),
    }

    write_report(stage3, args.output, month_label, summary_stats)


if __name__ == "__main__":
    main()
