# Parking Perks — Project Context for Codex

## What this project is

A monthly raffle tool for UBC Okanagan Parking Services.
It identifies well-behaved parkers and draws winners for a monthly perk/prize.

The project currently has two deliverables that must stay in sync:
- `parking_perks.py` — command-line Python script (for staff who prefer terminal)
- `index.html` — self-contained browser tool (no server, runs locally)
Both implement identical logic. Any logic change must be applied to both.

On a different branch 'dry-run-1' :
I would like to creat this a production ready app. 
Instead of a person manually submitting the plate reads, payments, citations and permit holders we will use APIs to get that info and run the draw every month. The main goal is to automate the complete process from pulling the data to running the process every month once and then also contacting the winners of the process through emails directly without any human intervention. The APIs are as follows, the parking serrvices team uses Genetec, T2 Iris and T2 Flex. Genetec will be used to get the palte reads data for the month, T2 Iris is for the payments and T2 flex will have info about the citations and permit holders. There will be people for whom the email address is not available mostly people who aren't permit holders, in that case we would like to promnpt the manager to find them nmanually. The vision is to have all of this running in the background, but still being able to have maybe a dashboard of sorts (haven't yet thought much about that.)

---

## Qualification rules

There are two independent tracks. A plate qualifies if it passes either track.

### Payment track
1. Appears in plate reads on **10+ separate calendar days** (configurable via `--min-visits`)
2. Each qualifying day: first camera read to last camera read spans **≥ 1 hour** (configurable via `--min-hours`)
3. Plate appears in the **payments file** for that month
4. Plate has **no citation** that month

### Permit track
1. Plate appears in the **active permit holders file**
2. Plate has **no citation** that month
3. No visit threshold — permit holders qualify automatically

Final pool = permit qualifiers + payment qualifiers (permit takes precedence if plate appears in both, because permit data has the email address).

---

## Input files

| File | Format | Notes |
|------|--------|-------|
| Plate reads | `.xlsx` | Header on row 2 (row 1 is a report timestamp). Columns: `Plate number`, `Local time (PDT)`, `Plate state`, others. |
| Payments | `.csv` | Plates stored as `="SK041H"` (Excel formula quoting). Column: `License Plate`. |
| Citations | `.xls` | Header on row 10 (rows 1–9 are report metadata). Column: `License #`. Format: `BC-SK041H-NA` (PROVINCE-PLATE-SUFFIX). |
| Permit holders | `.txt` | Comma-separated. Columns: `Distinct of ENT_UID`, `EMAIL_ADDRESS`, `SERIES_PREFIX`, `PERMIT_NUMBER`, `LICENSE_PLATES`. `LICENSE_PLATES` can be a single plate or a quoted comma-separated list e.g. `"674PRL,TC765L"`. |

---

## Plate normalisation — critical, file-specific

**Each file uses a different plate format. There are three separate normalisation functions — one per file. Never use a single shared normaliser.**

| File | Raw example | Normalised | Function |
|------|-------------|------------|----------|
| Plate reads | `SK041H` | `SK041H` | `normReads` / `normalise_reads_plate` — uppercase + trim only |
| Payments | `="SK041H"` | `SK041H` | `normPayments` / `normalise_payments_plate` — strip `="..."` wrapper |
| Citations | `BC-SK041H-NA` | `SK041H` | `normCitations` / `normalise_citations_plate` — extract middle segment |
| Permits | `SK041H` | `SK041H` | same as reads — uppercase + trim |

**The SK041H bug:** an earlier version used one shared normaliser that stripped province codes (BC, SK, AB, etc.) from the front of plates. This incorrectly turned `SK041H` into `041H`. Fixed by making normalisation file-specific. Never reintroduce shared province-stripping.

**Citation edge cases handled:**
- `"License #"` — header row repeated by export system, filtered out
- `BC-  -NA` — blank middle segment, filtered out
- `BC-XE115F-BIKE` — non-NA suffix, still works (always takes middle segment)
- `BC-SK-041H-NA` — 4 parts, joins middle segments → `SK041H`

---

## Known data quirks

**Plate reads file**
- Only covers April 24–30 in the sample data (7 days). Full month needed for 10-visit threshold.
- 1,674 duplicate rows (same plate + same timestamp) from dual-camera installations. Deduplicated on load.
- `"-"` plate values are invalid — filtered out.

**Payments file**
- RFC-4180 CSV quoting: `="SK041H"` is stored as `"=""SK041H"""` in the raw file bytes. The simple-toggle CSV parser handles this correctly. Do NOT use the complex ChatGPT-style parser (`&& cur === ''` condition) — it breaks this format.
- All transactions are `Trans Type: Regular`, no refunds or voids in current data.

**Citations file**
- ~94 rows are repeated header rows (`License #`). Filtered by normaliser returning `""`.
- A few rows have blank plates (`BC-  -NA`). Filtered.

**Permit holders file**
- 1,070 data rows, 2,382 unique plates after multi-plate expansion
- 16 rows are BIKE permits (series `BIKE`) — excluded. Constant `EXCLUDED_SERIES` controls this.
- Some people have up to 8 plates registered on one permit.

---

## UTC timezone bug (solved — do not reintroduce)

The plate reads timestamps are PDT (UTC-7). In JavaScript, `Date.toISOString().slice(0,10)` returns the UTC date, not local. Any read at or after 5:00 PM PDT shifts to the next calendar day in UTC, causing wrong date grouping.

**Fix:** `parseTimestamp()` extracts the date key directly from the timestamp string using regex — never from a `Date` object's date methods. `Date.UTC()` is used only for millisecond arithmetic (duration calculations), which is timezone-safe because we subtract two UTC values on the same conceptual day.

This bug caused JS to return 48 qualifiers instead of 52 when tested. The fix restores parity with the Python script.

---

## Draw system

- Uses `window.crypto.getRandomValues()` — cryptographically secure, OS entropy pool
- **Rejection sampling** eliminates modulo bias: values in the incomplete final bucket of Uint32 range are discarded and redrawn
- **Partial Fisher-Yates shuffle** — standard algorithm, unbiased
- **Single history entry per month** — re-drawing a month that already has a recorded draw requires the manager approval code
- Manager code: `UBCO-PERKS-2025` — stored as `MANAGER_CODE` constant in `index.html`. **In production this must move server-side.**
- History stored in `localStorage` under key `parking_perks_winner_history`

---

## Excel output columns

Sheet 1 — Qualifiers:
`# | Plate | Name | Email | Permit No. (or "None") | Qualifying Days (or "N/A") | Track`

Sheet 2 — Processing Summary: funnel counts for both tracks.

---

## Python script usage

```bash
# Full month run
python parking_perks.py \
  --reads    "April_Plate_Reads.xlsx" \
  --payments "April_Payments.csv" \
  --citations "Citations_April.xls" \
  --permits  "UBCO_Active_Permits_with_Email_Address_-_Plates__1_.txt" \
  --output   "Parking_Perks_April_2026.xlsx"

# Testing with partial data
python parking_perks.py \
  --reads    "April_Plate_Reads.xlsx" \
  --payments "April_Payments.csv" \
  --citations "Citations_April.xls" \
  --permits  "UBCO_Active_Permits_with_Email_Address_-_Plates__1_.txt" \
  --min-visits 4 \
  --output   "Parking_Perks_TEST.xlsx"
```

Dependencies: `pip install pandas openpyxl xlrd`

---

## Architecture — current vs planned

### Current (local HTML file)
- Single `index.html` — all logic runs in the browser
- `localStorage` for winner history
- Manager code is in client-side JS (acceptable for local internal tool)
- No authentication

### Planned (hosted)
```
Frontend (React or plain HTML, served statically)
    ↕ HTTPS API calls
Backend (Python FastAPI)
    ├── POST /api/analyze      — accepts 4 files, returns qualifiers JSON
    ├── POST /api/draw         — accepts pool + count, returns winners
    ├── GET/POST /api/history  — read/write draw history (real database)
    └── POST /api/auth/redraw  — validates manager code SERVER-SIDE
    ↕
Database (PostgreSQL)
    ├── draw_history table
    └── audit_log table (every draw/redraw/approval, non-deletable)
```

Security layers to add (in priority order):
1. UBC CWL (SSO) authentication — blocks non-staff entirely
2. Role-based access — staff vs manager roles
3. Manager code as server-side env variable (not in client code)
4. HTTPS enforced at reverse proxy
5. File validation — type check, 50MB size limit, virus scan before processing
6. Audit log — all draws recorded with user, timestamp, winners
7. Rate limiting on draw endpoint
8. CORS — backend only accepts from known frontend domain

---

## AI/Agentic opportunities

Highest value, roughly in order:

1. **Automated report fetching** — agent logs into parking management system monthly, pulls the 3 reports, triggers analysis. Removes all manual steps from the routine path.
2. **Anomaly detection** — flag suspicious patterns before analysis (plate with 47 payments in one month, permit holder whose email is non-UBC, plate in both payment and citation on same day).
3. **Winner notification drafting** — auto-draft contact email for winner using their email and track type; staff reviews and sends.
4. **Natural language queries** — after draw, staff can ask "how many STEM faculty qualified this month?" over the structured results.

---

## Testing plan

### Unit tests (`pytest`)
- All three normalisation functions with known edge cases (especially SK041H)
- `compute_qualifying_visits` with synthetic data (exact days/hours boundary cases)
- `parseCsvText` with quoted fields, empty values, multi-value plate fields
- Citation header-repeat filtering

### Integration tests
- Full pipeline with synthetic dataset → known expected output
- Parity test: same input through Python and JS → same qualifier list

### Bias/fairness test
```python
def test_draw_uniformity():
    # 100,000 simulated draws, chi-squared test
    # Each plate in a pool of N should win ~100000/N times
    # p > 0.05 confirms no statistically significant bias
```

### Regression tests
- Sample data files locked at known qualifier count (52 with min-visits=4)
- Any code change that alters this count must be explicitly reviewed

### Security tests
- XSS: plate value `<script>alert(1)</script>` — must render escaped
- CSV injection: plate `=CMD(...)` — normaliser must neutralise
- Manager code endpoint: wrong code returns error, no timing leak

---

## Decisions made and why

| Decision | Reason |
|----------|--------|
| Daily-span method (first-to-last read per day) over session-based | Simpler, directly matches the stated rule "10 separate days", easier to explain to stakeholders |
| 120-minute session gap was considered but rejected | Adds complexity without meaningfully changing outcomes for this dataset |
| Permit track bypasses visit threshold | Permit holders have already demonstrated commitment via annual/monthly permit purchase |
| Reject sampling for draw randomness | Eliminates modulo bias, mathematically provable fairness |
| Single history entry per month | Prevents draw manipulation via repeated re-draws; manager approval creates audit trail |
| No session logic, no review candidates sheet | Removed as unnecessary complexity after design discussion |
| File-specific normalisers | Required after discovering the SK041H bug from shared province-stripping logic |