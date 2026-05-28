"""
T2 Iris — debug getTransactionByPurchasedDate failure.
Tries multiple tokens, date ranges, and methods to isolate the issue.

Usage:
    python check_iris.py
"""
import logging
import sys
from datetime import datetime
from zeep import Client
from zeep.wsse.username import UsernameToken
from app.config import settings

# Enable zeep debug logging so we can see the raw SOAP request/response
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("zeep").setLevel(logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.WARNING)

BASE = settings.t2_iris_base_url.rstrip("/")
WSDL = f"{BASE}/TransactionInfoService?wsdl"
wsse = UsernameToken(settings.t2_iris_username, settings.t2_iris_password)
client = Client(WSDL, wsse=wsse)

# All TransactionInfo tokens to try — add yours here
TOKENS = [
    settings.t2_iris_token,
    # paste any other TransactionInfo tokens below:
    # "OTHER_TOKEN_HERE",
]

print("\n\n=== Testing getTransactionByPurchasedDate ===\n")

for tok in TOKENS:
    print(f"\n--- Token: {tok[:8]}... ---")

    # Try 1: single day (Apr 15)
    print("  1 day (Apr 15):")
    try:
        r = client.service.getTransactionByPurchasedDate(
            token=tok,
            purchasedDateFrom=datetime(2026, 4, 15, 0, 0, 0),
            purchasedDateTo=datetime(2026, 4, 15, 23, 59, 59),
        )
        rows = r if isinstance(r, list) else ([r] if r else [])
        print(f"    OK: {len(rows)} rows")
        for row in rows[:3]:
            print(f"      plate={getattr(row,'plateNumber','?')!r}  charged={getattr(row,'chargedAmount','?')!r}")
    except Exception as e:
        print(f"    FAILED: {e}")

print("\n\n=== Testing getTransactionBySettlementDate (alternative method) ===\n")
print("  1 day (Apr 15):")
try:
    r = client.service.getTransactionBySettlementDate(
        token=settings.t2_iris_token,
        settlementDateFrom=datetime(2026, 4, 15, 0, 0, 0),
        settlementDateTo=datetime(2026, 4, 15, 23, 59, 59),
    )
    rows = r if isinstance(r, list) else ([r] if r else [])
    print(f"  OK: {len(rows)} rows")
    for row in rows[:3]:
        print(f"    plate={getattr(row,'plateNumber','?')!r}  charged={getattr(row,'chargedAmount','?')!r}")
except Exception as e:
    print(f"  FAILED: {e}")
