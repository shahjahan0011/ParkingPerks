# Parking Perks — Server Deployment Guide (UBCO-SPARKP01)

Everything to turn the server into a fully automated monthly draw machine.
Work through the sections in order. Each one is independent — if you get
stuck, the previous sections keep working.

---

## Overview

```
Genetec scheduled report (daily ~12am, "last day", Excel, no images)
        │ email with .xlsx attachment
        ▼
Gmail mailbox (the Parking Perks account)
        ▲ pulled daily by monthly_run via Gmail API; parsed into data/reads.db
        │
Task Scheduler (daily 06:30) ──► monthly_run.bat
    └── step 0: pull new report emails → reads.db (every day)
    └── exits if last month is already drawn+reported
    └── otherwise: coverage gate → T2 Flex + T2 Iris → qualify → enrich (4726)
        → draw NUM_WINNERS → save → email Jeff + Jahan (CSV attached)
        → delete that month's reads from reads.db

IIS (443) /parkingperks/* → 127.0.0.1:8000 → always-on app
    └── web UI (manual draws, redraws, fallback .xlsx upload, /api/status)
    └── /api/ingest/* (dormant Data Exporter receiver -- not used; the
        exporter's 20 reads/sec licence cap made the emailed report safer)
```

---

## 1. Get the code + environment onto the server

1. Copy the whole `ParkingPerks` folder to the server (e.g. `C:\ParkingPerks`),
   or `git clone` it there (branch `automate`).
2. Copy `backend\.env` from your machine to the server's `backend\.env`
   (it is gitignored — it will NOT come along with a clone).
3. Double-click `server_app.bat` once. First run creates the environment and
   installs everything (a few minutes). When it says uvicorn is running,
   browse to `http://localhost:8000` on the server — the UI should load.
   Leave it running for now (Ctrl+C stops it).

## 2. IIS reverse proxy rule (ask your colleague — 2 minutes)

The same pattern as his `/genetec/*` rule. In IIS Manager (with ARR +
URL Rewrite, which his setup already uses):

- Site: the one bound to `ubco-sparkp01.ead.ubc.ca:443`
- Add an Inbound URL Rewrite rule:
  - Pattern: `^parkingperks/(.*)`
  - Action: Rewrite → `http://127.0.0.1:8000/{R:1}`
- Verify from any browser:
  `https://ubco-sparkp01.ead.ubc.ca/parkingperks/health` → `{"status":"ok"}`

The app itself stays bound to 127.0.0.1 — never directly exposed.

## 3. Schedule the daily reads report in Genetec

(The Data Exporter push was abandoned: its 20 reads/sec licence cap silently
drops reads at busy times. The emailed daily report has no such limit.)

In Security Desk / Config Tool, set up the scheduled report task:

- Report: Reads Report — **all cameras, deselect LPR cars, NO images**
- Event timestamp: relative range, **"During the last 1 day"**
- Schedule: **daily at 12:00 AM**
- Export format: **Excel (.xlsx)**
- Report name: `DailyReadsReport-ParkingPerks` (the email subject must
  contain this — it's what `GMAIL_REPORT_QUERY` in `.env` matches)
- Email destination: **the Parking Perks Gmail address** (the same account
  set up in step 4) — NOT your UBC inbox

If you rename the report, update `GMAIL_REPORT_QUERY` in `backend\.env`
to match the new subject.

**Verify (after step 4 + 5 are done):** the morning after the first
scheduled report, check `https://ubco-sparkp01.ead.ubc.ca/parkingperks/api/status`
→ `sources.reads.feed.rows` > 0 and `months_covered` shows the current
month. Each processed email gets the Gmail label `pperks-processed`.
You can also trigger a pull manually any time:
`backend\.venv\Scripts\python monthly_run.py` (it pulls mail first, then
exits if there's nothing to draw).

## 4. Gmail (one-time, ~10 minutes, on your laptop)

This one account does BOTH jobs: it RECEIVES the daily Genetec report
emails, and it SENDS the monthly manager report (the single gmail.modify
scope covers reading, labelling, and sending).

1. Create/choose the Google account (e.g. `ubco.parking.perks@gmail.com`).
2. Follow the instructions at the top of `backend\gmail_auth_setup.py`
   (Google Cloud project → enable Gmail API → consent screen with the sender
   as Test User → Desktop-app OAuth client).
3. Run `python gmail_auth_setup.py`, sign in as the sender, approve.
4. Paste the printed lines into the SERVER's `backend\.env`
   (`EMAIL_BACKEND=gmail`, `GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN/SENDER`).
5. Test from the server:
   `backend\.venv\Scripts\python -c "from app.email.sender import send_email; send_email(['jahan.shah@ubc.ca'],'Parking Perks test','It works.')"`

Recipients of the monthly report are `REPORT_RECIPIENTS` in `.env`
(currently Jeff + you). Winner emails are NEVER sent automatically.

## 5. Task Scheduler (two tasks)

Run these in an **Administrator** Command Prompt (adjust `C:\ParkingPerks`
if you put it elsewhere):

```bat
rem Always-on app (web UI + reads ingest) - starts at boot, restarts if it dies
schtasks /Create /TN "ParkingPerks Server" /TR "C:\ParkingPerks\server_app.bat" ^
  /SC ONSTART /RU SYSTEM /RL HIGHEST /F

rem Monthly draw - checks DAILY at 06:30, only acts when needed
schtasks /Create /TN "ParkingPerks Monthly Draw" /TR "C:\ParkingPerks\monthly_run.bat" ^
  /SC DAILY /ST 06:30 /RU SYSTEM /RL HIGHEST /F
```

Then in Task Scheduler GUI, open each task's Settings tab and tick
"If the task fails, restart every 1 minute, up to 3 times" for the server
task. Start the server task once manually:
`schtasks /Run /TN "ParkingPerks Server"`

Why daily, not monthly: each run first checks "is last month drawn AND
reported?" — if yes it exits in under a second. So a failure on the 1st
(VPN down, feed gap, Iris hiccup) emails you an alert and retries
automatically on the 2nd, 3rd, ... No partial-data draw can ever happen
(coverage gate: `MIN_COVERAGE_DAYS` in `.env`).

## 6. Things you can change later (all one-line .env edits)

| Setting | Meaning |
|---|---|
| `NUM_WINNERS=1` | winners per month (or one-off: `monthly_run.bat --winners 3`) |
| `REPORT_RECIPIENTS=` | who gets the monthly report |
| `MIN_COVERAGE_DAYS=26` | minimum days of reads before a draw is allowed |
| `MIN_VISITS=10` / `MIN_HOURS=1.0` | qualification thresholds |

## 7. Manual overrides

```bat
cd C:\ParkingPerks\backend
.venv\Scripts\python monthly_run.py --month 2026-06          rem run a specific month
.venv\Scripts\python monthly_run.py --winners 3              rem one-off winner count
.venv\Scripts\python monthly_run.py --resend-report          rem re-email last report
```

The web UI at `http://localhost:8000` (on the server) still does everything
manually: review pools, draw, redraw with the manager code, upload a
Security Desk .xlsx if the feed had a gap (the source with the most days of
coverage wins automatically).

## Files on the server worth knowing

- `backend\data\reads.db` — live plate reads + customer-lookup cache
  (auto-pruned after each month's report goes out)
- `backend\data\draws.csv`, `audit.csv` — permanent draw + audit history
- `backend\data\qualifiers_YYYY-MM.csv` — the attachment sent each month
- `backend\data\monthly_run.log` — every automated run's log
