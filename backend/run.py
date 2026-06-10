"""
One-command launcher: starts the server and opens the browser.

  cd backend
  python run.py

(or double-click start_parking_perks.bat in the repo root)
"""

import threading
import time
import webbrowser

import uvicorn

URL = "http://127.0.0.1:8000"


def _open_browser() -> None:
    time.sleep(1.5)  # give uvicorn a moment to bind
    webbrowser.open(URL)


if __name__ == "__main__":
    print(f"Parking Perks starting at {URL} — keep this window open.")
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="info")
