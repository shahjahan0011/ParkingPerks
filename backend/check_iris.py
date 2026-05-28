"""
Quick diagnostic for T2 Iris live connection.

Usage:
    python check_iris.py                        # uses token from .env
    python check_iris.py <token>                # tests a specific token against TransactionDataService
    python check_iris.py <token> info           # tests token against TransactionInfoService instead

Examples:
    python check_iris.py bIBFOSwj...
    python check_iris.py bIBFOSwj... info
"""

import sys
from datetime import datetime, timezone, timedelta

from zeep import Client
from app.config import settings

# Which WSDL to test
BASE = settings.t2_iris_base_url.rstrip("/")
WSDL_DATA = f"{BASE}/TransactionDataService?wsdl"
WSDL_INFO = f"{BASE}/TransactionInfoService?wsdl"

token = sys.argv[1] if len(sys.argv) > 1 else settings.t2_iris_token
use_info_service = len(sys.argv) > 2 and sys.argv[2].lower() == "info"
wsdl = WSDL_INFO if use_info_service else WSDL_DATA

print(f"=== T2 Iris Diagnostic ===")
print(f"  Service : {'TransactionInfoService' if use_info_service else 'TransactionDataService'}")
print(f"  WSDL    : {wsdl}")
print(f"  Token   : {token[:8]}...")
print()


def run():
    print("--- Loading WSDL ---")
    try:
        client = Client(wsdl)
        ops = list(client.service._binding._operations.keys())
        print(f"  OK  Operations: {ops}")
    except Exception as e:
        print(f"  FAILED: {e}")
        sys.exit(1)
    print()

    print("--- getLocations (token-only) ---")
    try:
        r = client.service.getLocations(token=token)
        print(f"  OK  result={r}")
    except Exception as e:
        print(f"  FAILED: {e}")
    print()

    print("--- getTransactionTypes (token-only) ---")
    try:
        r = client.service.getTransactionTypes(token=token)
        items = r if isinstance(r, list) else ([r] if r else [])
        print(f"  OK  {len(items)} types")
        for item in items:
            print(f"       id={getattr(item,'id','?')}  name={getattr(item,'name','?')!r}")
    except Exception as e:
        print(f"  FAILED: {e}")
    print()

    print("--- getTransactionByUpdateDate (April 15 2026) ---")
    from_dt = datetime(2026, 4, 15, 0, 0, 0)
    to_dt   = datetime(2026, 4, 15, 23, 59, 59)
    try:
        r = client.service.getTransactionByUpdateDate(
            token=token,
            updateDateFrom=from_dt,
            updateDateTo=to_dt,
        )
        rows = r if isinstance(r, list) else ([r] if r else [])
        print(f"  OK  {len(rows)} rows")
        for i, row in enumerate(rows[:5]):
            plate   = getattr(row, "plateNumber", "?")
            charged = getattr(row, "chargedAmount", "?")
            print(f"       [{i+1}] plate={plate!r}  charged={charged!r}")
    except Exception as e:
        print(f"  FAILED: {e}")


run()
