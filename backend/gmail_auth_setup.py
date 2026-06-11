"""
One-time Gmail OAuth setup -- run this ON A COMPUTER WITH A BROWSER
(your laptop is fine; you paste the result into the server's .env).

Prerequisites (5 minutes, once):
  1. Go to https://console.cloud.google.com/ signed in as the Gmail account
     that will SEND the reports (e.g. ubco.parking.perks@gmail.com).
  2. Create a project (any name), then: APIs & Services > Library >
     enable "Gmail API".
  3. APIs & Services > OAuth consent screen: External, fill in app name +
     your email, add the sender Gmail as a TEST USER. No verification needed.
  4. APIs & Services > Credentials > Create credentials > OAuth client ID >
     Application type: "Desktop app". Copy the Client ID and Client secret.

Then run:
    python gmail_auth_setup.py

It opens a browser, you sign in as the sender account and approve
"Send email on your behalf", and it prints the three .env lines.

Run:  pip install httpx   first if needed.
"""

import http.server
import secrets
import threading
import urllib.parse
import webbrowser

import httpx

PORT = 8765
REDIRECT = f"http://localhost:{PORT}/"
SCOPE = "https://www.googleapis.com/auth/gmail.send"

client_id = input("Paste the OAuth Client ID: ").strip()
client_secret = input("Paste the OAuth Client secret: ").strip()

state = secrets.token_urlsafe(16)
auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
    "client_id": client_id,
    "redirect_uri": REDIRECT,
    "response_type": "code",
    "scope": SCOPE,
    "access_type": "offline",   # this is what yields a refresh token
    "prompt": "consent",        # force a fresh refresh token every time
    "state": state,
})

code_holder: dict = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if params.get("state", [""])[0] != state:
            self.send_response(400); self.end_headers()
            self.wfile.write(b"State mismatch - close this tab and retry.")
            return
        code_holder["code"] = params.get("code", [""])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h2>Done - you can close this tab and return to the terminal.</h2>")

    def log_message(self, *args):
        pass


server = http.server.HTTPServer(("localhost", PORT), Handler)
threading.Thread(target=server.handle_request, daemon=True).start()

print("\nOpening the browser - sign in as the SENDER Gmail account and approve...")
webbrowser.open(auth_url)
print(f"(If nothing opened, paste this in a browser:\n{auth_url}\n)")

while "code" not in code_holder:
    pass

print("Exchanging the code for tokens...")
resp = httpx.post("https://oauth2.googleapis.com/token", data={
    "code": code_holder["code"],
    "client_id": client_id,
    "client_secret": client_secret,
    "redirect_uri": REDIRECT,
    "grant_type": "authorization_code",
}, timeout=30)
data = resp.json()

if "refresh_token" not in data:
    print(f"\nFAILED: {data}")
    print("Most common cause: the account wasn't added as a Test User on the "
          "OAuth consent screen.")
    raise SystemExit(1)

print("\nSUCCESS. Put these lines in the SERVER's backend/.env:\n")
print(f"EMAIL_BACKEND=gmail")
print(f"GMAIL_CLIENT_ID={client_id}")
print(f"GMAIL_CLIENT_SECRET={client_secret}")
print(f"GMAIL_REFRESH_TOKEN={data['refresh_token']}")
print(f"GMAIL_SENDER=<the gmail address you just signed in with>")
