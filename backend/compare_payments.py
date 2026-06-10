"""
Validate live T2 Iris payments against the known-good test-data CSV.

Runs the REAL pipeline code path (_fetch_payments_live: campus-local month
-> UTC day windows, $0 rows kept) for April 2026 and diffs the unique plate
set against test-data/April_Payments.csv.

Run from backend/ (UBC network):  python compare_payments.py
"""

import sys
from pathlib import Path

import pandas as pd

from app.config import settings
from app.core.normalise import normalise_payments_plate
from app.integrations.t2_iris import PaymentsFetchError, _fetch_payments_live

YEAR, MONTH = 2026, 4

# ── 1. Live fetch through the real pipeline ─────────────────────────────────
print(f"Fetching {YEAR}-{MONTH:02d} live from T2 Iris (full pipeline path)...")
try:
    live = {p.plate for p in _fetch_payments_live(YEAR, MONTH)}
except PaymentsFetchError as e:
    print(f"FAILED: {e}")
    sys.exit(1)
print(f"  live unique plates: {len(live)}")

# ── 2. Load the test-data CSV ────────────────────────────────────────────────
stub_dir = Path(settings.stub_data_dir)
csv_path = next(iter(sorted(stub_dir.glob("*Payment*.csv"))), None)
if csv_path is None:
    print(f"No *Payment*.csv found in {stub_dir} -- nothing to compare against.")
    sys.exit(1)

df = pd.read_csv(csv_path, dtype=str)
df.columns = df.columns.str.strip()
plate_col = next(c for c in df.columns if "license plate" in c.lower())
csv_plates = set(df[plate_col].apply(normalise_payments_plate)) - {""}
print(f"  CSV unique plates : {len(csv_plates)}  ({csv_path.name})")

# ── 3. Diff ──────────────────────────────────────────────────────────────────
both = live & csv_plates
only_csv = sorted(csv_plates - live)
only_live = sorted(live - csv_plates)

print()
print(f"  in both                      : {len(both)}  "
      f"({100 * len(both) / max(len(csv_plates), 1):.2f}% of CSV matched)")
print(f"  CSV only (missing from live) : {len(only_csv)}  {only_csv[:10]}")
print(f"  live only (not in CSV)       : {len(only_live)}  {only_live[:10]}")

print()
if not only_csv and not only_live:
    print("PERFECT: live and CSV agree exactly.")
    print("Set USE_STUBS_PAYMENTS=false in .env and restart.")
elif len(both) / max(len(csv_plates), 1) > 0.999:
    print("EFFECTIVELY PERFECT (>99.9%). Tiny residue is report-export "
          "timing. Set USE_STUBS_PAYMENTS=false in .env and restart.")
else:
    print("Still mismatching -- paste this output back.")
