# =============================================================================
# PARKING PERKS — Monthly Qualifier Report
# =============================================================================
#
# WHAT THIS SCRIPT DOES IN PLAIN ENGLISH:
#   1. Reads three files: plate camera reads, payment records, citations
#   2. Finds plates that visited campus 10+ times, each stay over 1 hour
#   3. Keeps only plates that paid (or hold a permit)
#   4. Removes plates that got a citation
#   5. Writes the winners to a formatted Excel report
#
# HOW TO RUN IT:
#   python parking_perks.py \
#     --reads   "April_Plate_Reads.xlsx" \
#     --payments "April_Payments.csv" \
#     --citations "Citations_April.xls" \
#     --output  "Parking_Perks_April_2026.xlsx"
#
#   Add --permits "Active_Permits.csv" once you have that file.
#   Use --min-visits 4 for testing with partial data.
# =============================================================================


# -----------------------------------------------------------------------------
# IMPORTS — what libraries we need and why
# -----------------------------------------------------------------------------

import argparse     # reads the flags you type after "python parking_perks.py"
import os           # lets us work with file paths (e.g. strip the extension)
from datetime import datetime  # used to stamp the report with today's date

import pandas as pd
# pandas is the core data library. Think of it like Excel in Python.
# A "DataFrame" (df) is just a table with rows and columns.
# We use it to load files, filter rows, join tables, and do calculations.

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
# openpyxl creates and styles Excel files.
# pandas can write Excel too, but openpyxl gives us control over colours,
# fonts, borders, and merged cells — everything needed for a nice report.


# =============================================================================
# SECTION 1: PLATE NORMALISATION
# =============================================================================
#
# THE PROBLEM:
#   The same physical licence plate is stored differently in each file:
#
#   Plate reads file:   SK041H          <- bare plate, exactly as on the car
#   Payments file:      ="SK041H"       <- Excel wraps it in ="" to prevent
#                                          the app treating it as a formula
#   Citations file:     SK-SK041H-NA   <- system adds province prefix and
#                                          a "-NA" suffix
#
#   If we try to match these as-is, "SK041H" != "="SK041H"" != "SK-SK041H-NA"
#   even though they're the same car. We need to clean each one to "SK041H".
#
# THE FIX — file-specific functions:
#   Rather than one function that tries to handle all three formats (which
#   caused the SK041H bug — it saw "SK" and stripped it thinking it was a
#   province code), we write one small function per file. Each function only
#   does the exact transformation that file needs. Nothing more.
# -----------------------------------------------------------------------------

def normalise_reads_plate(raw) -> str:
    """
    Plate reads file — plates are already clean. We just standardise the
    format (uppercase, no stray spaces).

    pd.isna() checks for missing/blank values (NaN = Not a Number, which
    is what pandas uses for empty cells). We return "" so the caller can
    easily filter these out.
    """
    if pd.isna(raw):
        return ""
    # str() converts whatever type pandas read it as into text
    # .strip() removes leading/trailing spaces: "  SK041H  " -> "SK041H"
    # .upper() makes it uppercase so "sk041h" == "SK041H"
    return str(raw).strip().upper()


def normalise_payments_plate(raw) -> str:
    """
    Payments file — plates are wrapped in Excel formula syntax: ="SK041H"
    We only need to strip the =" from the front and the " from the back.

    lstrip('="') removes any leading = or " characters (left side only).
    rstrip('"')  removes any trailing " characters (right side only).

    Why NOT strip province codes here? Because the payments file contains
    real plates like "SK041H" where SK is part of the plate — not a province
    prefix. The payments file never adds province prefixes.
    """
    if pd.isna(raw):
        return ""
    s = str(raw).strip().upper()
    s = s.lstrip('="').rstrip('"')
    return s


def normalise_citations_plate(raw) -> str:
    """
    Citations file — plates follow the format:  PROVINCE-PLATE-SUFFIX
    Examples:  BC-SK041H-NA   AB-XR099L-NA   SK-SK041H-NA

    The province prefix and -NA suffix are added by the citation system.
    We want ONLY the middle part — the actual plate number.

    How it works:
      "BC-SK041H-NA".split("-")  ->  ["BC", "SK041H", "NA"]
                                               ^ index [1] = what we want

    Edge cases handled:
      - "License #"  -> the citation export reprints its own header every
                        page. We return "" to filter these out.
      - Blank plates -> "BC-  -NA" after splitting gives ["BC","  ","NA"].
                        We strip and check — if the middle is empty, skip it.
      - Non-NA suffixes -> "BC-XE115F-BIKE" still works because we always
                           take index [1] regardless of what index [2] is.
      - Rows with no dashes -> malformed data. We return "" to skip them.
    """
    if pd.isna(raw):
        return ""

    s = str(raw).strip()

    # Filter out the header rows that got mixed into the data
    if s == "License #":
        return ""

    parts = s.split("-")

    # We expect exactly 3 parts: province, plate, suffix
    # If there aren't 3, the data is malformed — skip it
    if len(parts) != 3:
        return ""

    # parts[1] is the middle segment — the actual plate number
    plate = parts[1].strip().upper()

    # If the middle part is blank (e.g. "BC-  -NA"), skip it
    if not plate:
        return ""

    return plate


# =============================================================================
# SECTION 2: FILE LOADERS
# =============================================================================
#
# Each loader is responsible for one file. It reads the raw file, cleans it,
# and returns a tidy DataFrame with only the columns we actually need.
#
# WHY SEPARATE FUNCTIONS?
#   Because each file has a different format quirk. Separating them means
#   if the citations file changes its format next month, you only touch
#   load_citations() — nothing else breaks.
# =============================================================================

def load_plate_reads(path: str) -> pd.DataFrame:
    """
    Loads the plate reads XLSX.

    FORMAT QUIRK: The first row of this file is a report timestamp
    ("Report created: FRI MAY 8 2026..."). The actual column headers
    are on row 2. So we tell pandas to use row index 1 as the header
    with header=1. (Pandas counts from 0, so index 1 = second row.)
    """
    df = pd.read_excel(path, header=1)

    # .str.strip() on column names removes any invisible spaces that might
    # have crept in — otherwise "Plate number " != "Plate number"
    df.columns = df.columns.str.strip()

    # Rename to shorter, consistent names so the rest of the code is readable
    df = df.rename(columns={
        "Local time (PDT)": "local_time",
        "Plate number":     "plate_raw",
    })

    # Apply our reads-specific normalisation to every plate value.
    # .apply(func) runs the function on each value in the column one by one.
    df["plate"] = df["plate_raw"].apply(normalise_reads_plate)

    # Remove rows where the plate came back empty (missing data, "-" entries)
    df = df[df["plate"] != ""]

    # Parse the timestamp string into a real datetime object.
    # format= tells pandas exactly how to interpret the string.
    # %m=month %d=day %Y=4-digit year %I=12hr hour %M=minute %S=second %p=AM/PM
    # errors="coerce" means: if a value can't be parsed, set it to NaT
    # (Not a Time) instead of crashing the whole script.
    df["local_time"] = pd.to_datetime(
        df["local_time"],
        format="%m/%d/%Y, %I:%M:%S %p",
        errors="coerce"
    )

    # Drop rows where the timestamp couldn't be parsed (NaT values)
    # subset= means "only look at this column when deciding what to drop"
    df = df.dropna(subset=["local_time"])

    # FIX — Issue 5: Deduplicate exact same plate+timestamp.
    # Some camera setups have two readers at the same entrance. When a car
    # drives past, both cameras fire at the same second, creating duplicate
    # rows. keep="first" means keep one copy, discard the rest.
    df = df.drop_duplicates(subset=["plate", "local_time"], keep="first")

    # Return only the two columns the rest of the script needs.
    # Dropping unused columns keeps memory usage low on large files.
    return df[["plate", "local_time"]]


def load_payments(path: str) -> pd.DataFrame:
    """
    Loads the payments CSV.

    dtype=str tells pandas to read every column as text, not numbers.
    Without this, pandas might interpret "="SK041H"" as a formula and
    mangle it, or try to convert plate numbers to integers.
    """
    df = pd.read_csv(path, dtype=str)
    df.columns = df.columns.str.strip()

    df["plate"] = df["License Plate"].apply(normalise_payments_plate)

    # Remove rows where plate came back empty
    df = df[df["plate"] != ""]

    # drop_duplicates() removes identical rows.
    # We only care whether a plate paid at all — not how many times.
    return df[["plate"]].drop_duplicates()


def load_citations(path: str) -> pd.DataFrame:
    """
    Loads the citations XLS (legacy Excel format).

    FORMAT QUIRKS:
      1. It's an .xls file (old Excel format), not .xlsx.
         pandas needs engine="xlrd" to read these — openpyxl (the default)
         can only read .xlsx files.
      2. The first 9 rows are report metadata (title, date range, etc).
         The actual column headers are on row 10, which is index 9.
         So we use header=9.
    """
    df = pd.read_excel(path, engine="xlrd", header=9)
    df.columns = df.columns.str.strip()

    df = df.rename(columns={"License #": "plate_raw"})
    df = df.dropna(subset=["plate_raw"])

    # Apply citations-specific normalisation (extracts middle of PROV-PLATE-SUFFIX)
    # This also filters out the 94 "License #" header-repeat rows automatically
    df["plate"] = df["plate_raw"].apply(normalise_citations_plate)

    # Filter out empty strings (malformed rows, blank plates)
    df = df[df["plate"] != ""]

    return df[["plate"]].drop_duplicates()


def load_permits(path: str) -> pd.DataFrame:
    """
    Loads the optional permit holders file (planned for future use).

    This function is flexible — it tries to find the right columns by
    looking for keywords in column names, because permit exports vary.
    """
    if path.endswith(".csv"):
        df = pd.read_csv(path, dtype=str)
    else:
        df = pd.read_excel(path, dtype=str)

    df.columns = df.columns.str.strip()

    # next() returns the first item from a sequence, or None if empty.
    # The generator expression creates a lazy sequence of matching column names.
    plate_col  = next((c for c in df.columns if any(
                    w in c.lower() for w in ["plate", "licence", "license"])), None)
    permit_col = next((c for c in df.columns if "permit" in c.lower()), None)
    name_col   = next((c for c in df.columns if "name"   in c.lower()), None)

    out = pd.DataFrame()
    if plate_col:
        out["plate"] = df[plate_col].apply(normalise_payments_plate)
    if permit_col:
        out["permit_number"] = df[permit_col].fillna("").astype(str)
    if name_col:
        out["name"] = df[name_col].fillna("").astype(str)

    if out.empty:
        return out

    out = out[out["plate"] != ""]
    return out.drop_duplicates(subset=["plate"])


# =============================================================================
# SECTION 3: VISIT DETECTION (THE CORE LOGIC)
# =============================================================================
#
# THE PROBLEM WE'RE SOLVING:
#   The camera system doesn't give us clean "arrived at X, left at Y" events.
#   It records every time a camera spots a plate driving past.
#   A car parked for 3 hours might generate 40+ reads as it passes cameras.
#
# HOW WE DETECT A SESSION (FIX — Issue 4, gap-based approach):
#   We sort all reads for a plate by time, then look at the GAP between
#   consecutive reads. If the gap exceeds SESSION_GAP_MINUTES, we treat
#   that as the car having left and come back — a new session starts.
#
#   Example for plate SK041H with SESSION_GAP_MINUTES = 120:
#
#   Time      Gap from previous
#   09:01     ---        <- first read, start of session 1
#   09:14     13 min     <- still session 1 (gap < 120)
#   09:45     31 min     <- still session 1
#   10:22     37 min     <- still session 1
#   *** 13:05  163 min   <- GAP > 120 -> NEW SESSION STARTS ***
#   13:08     3 min      <- session 2
#   14:30     82 min     <- still session 2
#   15:01     31 min     <- still session 2
#
#   Session 1: 09:01 -> 10:22 = 1h 21m  qualifies (> 1 hour)
#   Session 2: 13:05 -> 15:01 = 1h 56m  qualifies
#   -> 2 qualifying visits for this plate
#
#   This also solves midnight crossings automatically. A car seen at 11pm
#   and 1am has a 2-hour gap — below threshold — so it stays one session
#   instead of being split across two calendar days.
#
# WHY 120 MINUTES?
#   We analysed the actual gap distribution in the data. Gaps under 120 mins
#   are common even for parked cars (cameras pick them up intermittently).
#   After 120 mins the frequency drops sharply — signalling genuine departure.
# =============================================================================

SESSION_GAP_MINUTES = 120  # change this one number to adjust the session boundary


def compute_qualifying_visits(
    reads: pd.DataFrame,
    min_visits: int,
    min_hours: float
) -> pd.DataFrame:
    """
    Takes the cleaned plate reads and returns plates that have enough
    qualifying sessions to be considered for a perk.

    Parameters:
        reads       -- DataFrame with columns: plate, local_time
        min_visits  -- how many qualifying sessions required (default: 10)
        min_hours   -- minimum session duration to count (default: 1.0)

    Returns a DataFrame with one row per qualifying plate.
    """

    # STEP A: Sort reads by plate then by time.
    # This is essential — gap calculations only make sense in chronological order.
    reads = reads.sort_values(["plate", "local_time"])

    # STEP B: Calculate the time gap before each read.
    # .groupby("plate") splits the DataFrame into one group per plate.
    # ["local_time"].shift(1) shifts the time column down by 1 row WITHIN
    # each group, so each row gets the timestamp of the PREVIOUS read for
    # that same plate.
    #
    # Before shift:             After shift(1):
    #   plate    time             plate    time    prev_time
    #   SK041H   09:01            SK041H   09:01   NaT       <- first, no previous
    #   SK041H   09:14            SK041H   09:14   09:01
    #   SK041H   13:05            SK041H   13:05   09:14
    #   XR099L   08:00            XR099L   08:00   NaT       <- new plate, resets
    #   XR099L   08:15            XR099L   08:15   08:00
    reads["prev_time"] = reads.groupby("plate")["local_time"].shift(1)

    # Subtract to get the gap as a timedelta, then convert to minutes.
    reads["gap_mins"] = (
        reads["local_time"] - reads["prev_time"]
    ).dt.total_seconds() / 60

    # STEP C: Mark where new sessions begin.
    # A new session starts when gap_mins is NaN (first read for this plate)
    # OR when gap_mins exceeds our threshold (car was gone long enough).
    # The | operator means OR. Result is a True/False column.
    reads["is_new_session"] = (
        reads["gap_mins"].isna() |
        (reads["gap_mins"] > SESSION_GAP_MINUTES)
    )

    # STEP D: Assign a session ID to every read.
    # .cumsum() on a True/False column counts the True values seen so far.
    # Since is_new_session is True at the start of each session, cumsum()
    # gives us an incrementing session number within each plate's group.
    #
    # is_new_session    cumsum = session_id
    # True              1      <- session 1 starts
    # False             1      <- still session 1
    # False             1
    # True              2      <- session 2 starts
    # False             2
    reads["session_id"] = reads.groupby("plate")["is_new_session"].cumsum()

    # STEP E: Measure each session's duration.
    # Group by plate + session_id, get first and last read time.
    # The difference = how long the car was on campus in that session.
    sessions = (
        reads
        .groupby(["plate", "session_id"])
        .agg(
            session_start=("local_time", "min"),
            session_end=  ("local_time", "max"),
        )
        .reset_index()
        # reset_index() promotes plate and session_id from index levels back
        # into regular columns, making the DataFrame easier to work with.
    )

    sessions["duration_hrs"] = (
        sessions["session_end"] - sessions["session_start"]
    ).dt.total_seconds() / 3600

    # STEP F: Keep only sessions that meet the minimum duration.
    qualifying_sessions = sessions[sessions["duration_hrs"] >= min_hours].copy()

    # STEP G: Count qualifying sessions per plate and compute average duration.
    plate_summary = (
        qualifying_sessions
        .groupby("plate")
        .agg(
            qualifying_visits=  ("session_id",    "count"),
            avg_hours_per_visit=("duration_hrs",  "mean"),
        )
        .reset_index()
    )

    plate_summary["avg_hours_per_visit"] = plate_summary["avg_hours_per_visit"].round(1)

    # STEP H: Keep only plates with enough qualifying visits.
    return plate_summary[plate_summary["qualifying_visits"] >= min_visits].copy()


# =============================================================================
# SECTION 4: REPORT WRITER
# =============================================================================
#
# Style constants defined at module level (outside any function).
# Defining them once here means if you want to change the header colour,
# you change it in one place and it updates everywhere.
#
# Colours are hex codes (same as in CSS/HTML):
#   "1F4E79" = dark navy blue   "FFFFFF" = white
#   "EBF3FB" = light blue       "E2EFDA" = light green (permit holders)
# =============================================================================

HEADER_FILL = PatternFill("solid", start_color="1F4E79")
HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=11)
TITLE_FONT  = Font(name="Arial", bold=True, size=14, color="1F4E79")
BODY_FONT   = Font(name="Arial", size=10)
ALT_FILL    = PatternFill("solid", start_color="EBF3FB")
GREEN_FILL  = PatternFill("solid", start_color="E2EFDA")
GREEN_FONT  = Font(name="Arial", size=10, color="375623")
THIN_SIDE   = Side(style="thin", color="B8CCE4")
CELL_BORDER = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)


def _style_header_row(ws, row_num: int, num_cols: int):
    """
    Applies dark blue header style to a row.
    Underscore prefix = internal helper, not meant to be called from outside.
    """
    for col in range(1, num_cols + 1):
        cell           = ws.cell(row=row_num, column=col)
        cell.font      = HEADER_FONT
        cell.fill      = HEADER_FILL
        cell.border    = CELL_BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def write_report(
    qualifiers: pd.DataFrame,
    output_path: str,
    month_label: str,
    summary_stats: dict
):
    """
    Writes the final Excel report with two sheets:
      Sheet 1 — Qualifiers: one formatted row per winning plate
      Sheet 2 — Processing Summary: funnel counts from each stage
    """

    # Workbook() creates a new empty Excel file in memory.
    # Nothing is written to disk until wb.save() at the very end.
    wb = Workbook()

    # ---- SHEET 1: QUALIFIERS ---------------------------------------------
    ws = wb.active
    ws.title = "Parking Perks Qualifiers"

    # freeze_panes = "A4" keeps rows 1-3 visible when scrolling down.
    ws.freeze_panes = "A4"

    # Row 1: title spanning all 7 columns
    ws.merge_cells("A1:G1")
    ws["A1"] = f"Parking Perks — Qualifying Participants  |  {month_label}"
    ws["A1"].font      = TITLE_FONT
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 32

    # Row 2: metadata (date generated, count, criteria used)
    ws.merge_cells("A2:G2")
    ws["A2"] = (
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}    "
        f"Total qualifiers: {len(qualifiers)}    "
        f"Criteria: {summary_stats['min_visits']}+ visits of "
        f"{summary_stats['min_hours']}+ hr | Valid payment/permit | No citations"
    )
    ws["A2"].font      = Font(name="Arial", size=9, italic=True, color="595959")
    ws["A2"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[2].height = 18

    # Row 3: column headers
    headers = ["#", "Plate Number", "Name", "Permit Number",
               "Visits This Month", "Avg Stay (hrs)", "Payment Source"]

    # enumerate(headers, 1) gives (1, "#"), (2, "Plate Number"), ...
    # Starting at 1 because Excel columns are 1-indexed.
    for col_num, header_text in enumerate(headers, 1):
        ws.cell(row=3, column=col_num, value=header_text)
    _style_header_row(ws, row_num=3, num_cols=len(headers))
    ws.row_dimensions[3].height = 28

    # Rows 4+: one row per qualifying plate
    CENTRE_COLS = {1, 5, 6}   # columns where numbers look better centred

    for display_num, (_, row) in enumerate(qualifiers.iterrows(), 1):
        excel_row = display_num + 3   # offset past the 3 header rows

        row_data = [
            display_num,
            row["plate"],
            row.get("name", ""),
            row.get("permit_number", ""),
            row["qualifying_visits"],
            row["avg_hours_per_visit"],
            row.get("payment_source", "Payment"),
        ]

        is_permit = row.get("payment_source") == "Permit"
        row_fill  = GREEN_FILL if is_permit else (ALT_FILL if display_num % 2 == 0 else PatternFill())
        row_font  = GREEN_FONT if is_permit else BODY_FONT

        for col_num, value in enumerate(row_data, 1):
            cell           = ws.cell(row=excel_row, column=col_num, value=value)
            cell.font      = row_font
            cell.fill      = row_fill
            cell.border    = CELL_BORDER
            cell.alignment = Alignment(
                horizontal="center" if col_num in CENTRE_COLS else "left",
                vertical="center"
            )
        ws.row_dimensions[excel_row].height = 20

    # Set column widths (in character units)
    for col_num, width in enumerate([5, 16, 28, 18, 20, 18, 16], 1):
        ws.column_dimensions[get_column_letter(col_num)].width = width

    # ---- SHEET 2: PROCESSING SUMMARY -------------------------------------
    # An audit trail showing how many plates passed through each stage.
    ws2 = wb.create_sheet("Processing Summary")
    ws2.column_dimensions["A"].width = 42
    ws2.column_dimensions["B"].width = 20

    ws2["A1"] = "Parking Perks — Processing Summary"
    ws2["A1"].font = TITLE_FONT
    ws2.row_dimensions[1].height = 30

    summary_rows = [
        ("Month",    month_label),
        ("Run date", datetime.now().strftime("%Y-%m-%d %H:%M")),
        (None, None),
        ("-- Stage 1: Visit behaviour --", None),
        ("Total unique plates in reads file",                        summary_stats["total_plates"]),
        (f"Plates with {summary_stats['min_visits']}+ qualifying sessions (>={summary_stats['min_hours']} hr)",
                                                                     summary_stats["stage1"]),
        ("Session gap threshold used",                               f"{SESSION_GAP_MINUTES} minutes"),
        (None, None),
        ("-- Stage 2: Valid payment / permit --", None),
        ("Plates matched to payment record",                         summary_stats["stage2_payment"]),
        ("Plates matched to permit (if file provided)",              summary_stats["stage2_permit"]),
        ("Plates passing stage 2 (either source)",                   summary_stats["stage2_total"]),
        (None, None),
        ("-- Stage 3: No citations --", None),
        ("Plates removed (had citation)",                            summary_stats["removed_citations"]),
        ("FINAL QUALIFIERS",                                         summary_stats["final"]),
    ]

    for row_idx, (label, value) in enumerate(summary_rows, start=2):
        is_section = bool(label and label.startswith("--"))
        is_final   = label == "FINAL QUALIFIERS"

        label_cell      = ws2.cell(row=row_idx, column=1, value=label)
        label_cell.font = Font(name="Arial", size=10,
                               bold=(is_section or is_final),
                               color="1F4E79" if is_final else "000000")

        if value is not None:
            val_cell           = ws2.cell(row=row_idx, column=2, value=value)
            val_cell.font      = Font(name="Arial", size=10, bold=is_final,
                                      color="1F4E79" if is_final else "000000")
            val_cell.alignment = Alignment(horizontal="right")

    ws2.cell(row=len(summary_rows) + 4, column=1,
             value="Note: Green rows on the Qualifiers sheet = permit holders."
    ).font = Font(name="Arial", size=9, italic=True, color="595959")

    wb.save(output_path)
    print(f"  Report saved: {output_path}")


# =============================================================================
# SECTION 5: MAIN — orchestrates everything in order
# =============================================================================
#
# This function doesn't do data processing itself. It:
#   1. Reads your command-line arguments
#   2. Calls the loaders to get clean DataFrames
#   3. Runs the three filter stages in sequence
#   4. Passes results to write_report()
#
# Think of it as the manager — it delegates to specialists.
# =============================================================================

def main():

    # ---- ARGUMENT PARSING ------------------------------------------------
    # argparse lets us accept named flags on the command line.
    # required=True  -> script errors clearly if you forget this flag
    # default=       -> used when the flag is not provided
    # type=          -> automatically converts the string to the right type
    parser = argparse.ArgumentParser(
        description="Parking Perks — monthly qualifying plate report"
    )
    parser.add_argument("--reads",      required=True,  help="Plate reads file (.xlsx)")
    parser.add_argument("--payments",   required=True,  help="Payments file (.csv)")
    parser.add_argument("--citations",  required=True,  help="Citations file (.xls or .xlsx)")
    parser.add_argument("--permits",    default=None,   help="Optional: permit holders (.csv or .xlsx)")
    parser.add_argument("--output",     default="Parking_Perks_Report.xlsx")
    parser.add_argument("--min-visits", type=int,   default=5)
    parser.add_argument("--min-hours",  type=float, default=1.0)
    args = parser.parse_args()

    month_label = (
        os.path.basename(args.reads)
        .replace("_", " ").replace(".xlsx", "").replace(".xls", "")
    )

    # ---- LOAD FILES ------------------------------------------------------
    print("\nLoading and cleaning files...")
    reads     = load_plate_reads(args.reads)
    payments  = load_payments(args.payments)
    citations = load_citations(args.citations)
    permits   = load_permits(args.permits) if args.permits else pd.DataFrame(columns=["plate"])

    total_plates = reads["plate"].nunique()
    # :, inside an f-string formats numbers with commas: 50000 -> "50,000"
    print(f"  Plate reads:  {len(reads):,} rows | {total_plates:,} unique plates")
    print(f"  Payments:     {len(payments):,} unique plates")
    print(f"  Citations:    {len(citations):,} unique plates")
    if not permits.empty:
        print(f"  Permits:      {len(permits):,} unique plates")

    # ---- STAGE 1: VISIT BEHAVIOUR ----------------------------------------
    print(f"\nStage 1 — sessions of {args.min_hours}+ hrs, gap threshold {SESSION_GAP_MINUTES} mins...")
    stage1 = compute_qualifying_visits(reads, args.min_visits, args.min_hours)
    print(f"  -> {len(stage1):,} plates have {args.min_visits}+ qualifying sessions")

    if len(stage1) == 0:
        print("  Tip: use --min-visits 4 to test with a partial-month file.")

    # ---- STAGE 2: VALID PAYMENT OR PERMIT --------------------------------
    # Convert plate columns to Python sets for O(1) lookup speed.
    # Checking "x in a_set" is instant regardless of set size.
    # Checking "x in a_list" gets slower as the list grows.
    paid_plates   = set(payments["plate"])
    permit_plates = set(permits["plate"]) if not permits.empty else set()

    # .isin(set) checks each plate against the set, returning a True/False column
    stage1["has_payment"]   = stage1["plate"].isin(paid_plates)
    stage1["has_permit"]    = stage1["plate"].isin(permit_plates)
    stage1["valid_payment"] = stage1["has_payment"] | stage1["has_permit"]

    stage2_payment_count = int(stage1["has_payment"].sum())
    stage2_permit_count  = int(stage1["has_permit"].sum())
    stage2 = stage1[stage1["valid_payment"]].copy()

    print(f"\nStage 2 — cross-referencing payment and permit records...")
    print(f"  Matched via payment: {stage2_payment_count}")
    print(f"  Matched via permit:  {stage2_permit_count}")
    print(f"  -> {len(stage2):,} plates have valid payment or permit")

    # ---- STAGE 3: NO CITATIONS -------------------------------------------
    cited_plates = set(citations["plate"])

    # The ~ operator inverts a boolean column: True -> False, False -> True
    # So ~stage2["plate"].isin(cited_plates) = "plate is NOT in cited set"
    stage3 = stage2[~stage2["plate"].isin(cited_plates)].copy()
    removed_count = len(stage2) - len(stage3)

    print(f"\nStage 3 — removing plates with citations...")
    print(f"  Removed: {removed_count}")
    print(f"  -> {len(stage3):,} final qualifiers")

    # ---- ENRICH WITH PERMIT DATA -----------------------------------------
    # Label each qualifier's payment source for display in the report
    stage3["payment_source"] = stage3.apply(
        # lambda = anonymous one-line function. r = each row.
        lambda r: "Permit" if r["has_permit"] else "Payment",
        axis=1   # axis=1 = apply row-by-row (not column-by-column)
    )

    # If we have permit data, merge in names and permit numbers.
    # merge() is like a SQL JOIN — matches rows from two DataFrames on "plate".
    # how="left" keeps ALL rows from stage3, adds permit columns where matched,
    # fills NaN where there's no match.
    if not permits.empty:
        permit_cols = ["plate"]
        if "name"          in permits.columns: permit_cols.append("name")
        if "permit_number" in permits.columns: permit_cols.append("permit_number")
        stage3 = stage3.merge(permits[permit_cols], on="plate", how="left")

    if "name"          not in stage3.columns: stage3["name"]          = ""
    if "permit_number" not in stage3.columns: stage3["permit_number"] = ""
    stage3[["name", "permit_number"]] = stage3[["name", "permit_number"]].fillna("")

    # Sort by most visits first so top performers appear at the top
    stage3 = stage3.sort_values("qualifying_visits", ascending=False).reset_index(drop=True)

    # ---- WRITE REPORT ----------------------------------------------------
    summary_stats = {
        "total_plates":      total_plates,
        "stage1":            len(stage1),
        "stage2_payment":    stage2_payment_count,
        "stage2_permit":     stage2_permit_count,
        "stage2_total":      len(stage2),
        "removed_citations": removed_count,
        "final":             len(stage3),
        "min_visits":        args.min_visits,
        "min_hours":         args.min_hours,
    }

    print(f"\nWriting report...")
    write_report(stage3, args.output, month_label, summary_stats)
    print(f"Done. Final qualifier count: {len(stage3)}\n")


# =============================================================================
# ENTRY POINT
# =============================================================================
#
# This block only runs when you execute the file directly:
#   python parking_perks.py --reads ...
#
# It does NOT run if another Python file imports this one.
# This lets you reuse functions from this file in other scripts without
# triggering the whole pipeline accidentally.
# =============================================================================

if __name__ == "__main__":
    main()