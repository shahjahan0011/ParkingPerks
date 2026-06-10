"""
T2 Iris diagnostic — find out why getTransactionByPurchasedDate faults.

The WSDL (confirmed 2026-06-10) defines the request as:
    token              xs:string
    purchasedDateFrom  xs:dateTime
    purchasedDateTo    xs:dateTime
    version            optional, enum v1.0 .. v1.5

Faults carry an InfoServiceFault detail with shortErrorMessage /
techImplementationDetails / errCode — this script prints them, instead of
the useless generic message.

Run from backend/:  python check_iris.py
"""

from datetime import datetime, timedelta, timezone

from zeep import Client
from zeep.exceptions import Fault
from zeep.plugins import HistoryPlugin
from zeep.wsse.username import UsernameToken

from app.config import settings

WSDL = f"{settings.t2_iris_base_url.rstrip('/')}/TransactionInfoService?wsdl"

history = HistoryPlugin()
client = Client(
    WSDL,
    wsse=UsernameToken(settings.t2_iris_username, settings.t2_iris_password),
    plugins=[history],
)

print(f"WSDL  : {WSDL}")
print(f"User  : {settings.t2_iris_username}")
print(f"Token : {settings.t2_iris_token[:8]}...")
print()


def fault_detail(e: Exception) -> str:
    """Extract the InfoServiceFault fields hidden inside a zeep Fault."""
    detail = getattr(e, "detail", None)
    if detail is None:
        return str(e)
    try:
        from lxml import etree
        return etree.tostring(detail, pretty_print=True).decode().strip()
    except Exception:
        return f"{e} (detail present but lxml not installed: pip install lxml)"


def last_response_xml() -> str:
    try:
        from lxml import etree
        return etree.tostring(
            history.last_received["envelope"], pretty_print=True
        ).decode().strip()
    except Exception:
        return "(install lxml to see raw XML: pip install lxml)"


def try_call(label: str, fn, show_raw: bool = False):
    print(f"--- {label} ---")
    try:
        result = fn()
        rows = result if isinstance(result, list) else ([result] if result else [])
        print(f"  OK: {len(rows)} rows")
        if rows:
            r = rows[0]
            plate = getattr(r, "plateNumber", "(no plateNumber attr)")
            charged = getattr(r, "chargedAmount", "?")
            purchased = getattr(r, "purchasedDate", "?")
            print(f"  sample: plate={plate!r} charged={charged} purchased={purchased}")
        print()
        return rows
    except Fault as e:
        print(f"  FAULT: {e}")
        print(f"  detail:\n{fault_detail(e)}")
        if show_raw:
            print(f"  raw response:\n{last_response_xml()[:1500]}")
        print()
        return None
    except Exception as e:
        print(f"  ERROR ({type(e).__name__}): {e}")
        print()
        return None


svc = client.service
TOKEN = settings.t2_iris_token

# 0. Sanity check — known-working call. If this fails, fix auth/VPN first.
ok = try_call("0. getPaystations (sanity)", lambda: svc.getPaystations(token=TOKEN))
if ok is None:
    print("getPaystations failed — credentials/network problem. Stopping here.")
    raise SystemExit(1)

# 1. Tiny window: 1 hour, yesterday noon. Isolates window-size limits.
y = datetime.now() - timedelta(days=1)
t1 = datetime(y.year, y.month, y.day, 12, 0, 0)
try_call(
    f"1. purchasedDate, 1-HOUR window ({t1:%Y-%m-%d} 12:00-13:00), no version",
    lambda: svc.getTransactionByPurchasedDate(
        token=TOKEN, purchasedDateFrom=t1, purchasedDateTo=t1 + timedelta(hours=1)
    ),
    show_raw=True,
)

# 2. Same 1-hour window, each version value.
for v in ("v1.0", "v1.2", "v1.5"):
    try_call(
        f"2. purchasedDate, 1-hour window, version={v}",
        lambda v=v: svc.getTransactionByPurchasedDate(
            token=TOKEN,
            purchasedDateFrom=t1,
            purchasedDateTo=t1 + timedelta(hours=1),
            version=v,
        ),
    )

# 3. 1-hour window with timezone-aware UTC datetimes (some servers demand 'Z').
t1z = t1.replace(tzinfo=timezone.utc)
try_call(
    "3. purchasedDate, 1-hour window, tz-aware UTC",
    lambda: svc.getTransactionByPurchasedDate(
        token=TOKEN, purchasedDateFrom=t1z, purchasedDateTo=t1z + timedelta(hours=1)
    ),
)

# 4. Full day yesterday.
d0 = datetime(y.year, y.month, y.day, 0, 0, 0)
try_call(
    f"4. purchasedDate, 1-DAY window ({d0:%Y-%m-%d})",
    lambda: svc.getTransactionByPurchasedDate(
        token=TOKEN, purchasedDateFrom=d0, purchasedDateTo=d0 + timedelta(days=1)
    ),
)

# 5. 7-day window last week.
w0 = d0 - timedelta(days=7)
try_call(
    f"5. purchasedDate, 7-DAY window ({w0:%Y-%m-%d} → {d0:%Y-%m-%d})",
    lambda: svc.getTransactionByPurchasedDate(
        token=TOKEN, purchasedDateFrom=w0, purchasedDateTo=d0
    ),
)

# 6. Full April 2026 (what the pipeline actually needs).
try_call(
    "6. purchasedDate, FULL MONTH April 2026",
    lambda: svc.getTransactionByPurchasedDate(
        token=TOKEN,
        purchasedDateFrom=datetime(2026, 4, 1, 0, 0, 0),
        purchasedDateTo=datetime(2026, 4, 30, 23, 59, 59),
    ),
)

# 7. Settlement-date method as fallback (1-day).
try_call(
    f"7. settlementDate fallback, 1-day window ({d0:%Y-%m-%d})",
    lambda: svc.getTransactionBySettlementDate(
        token=TOKEN, settlementDateFrom=d0, settlementDateTo=d0 + timedelta(days=1)
    ),
)

print("Done. Paste this full output back.")
