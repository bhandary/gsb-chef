#!/usr/bin/env bash
# Drive sign-up and email verification in the browser, then check the auth database.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$SCRIPT_DIR/../../../.." && pwd)
CURRENT="$ROOT/verification-runs/current"
EMAIL=${VERIFY_EMAIL:-gsb-verify@example.com}
PASSWORD=${VERIFY_PASSWORD:-verify-skill-pass}

if [[ ! -f "$CURRENT/instance.json" ]]; then
  echo "No verification instance. Run scripts/launch.sh first." >&2
  exit 1
fi

eval "$(python3 - "$CURRENT/instance.json" <<'PY'
import json, shlex, sys
data = json.load(open(sys.argv[1]))
print(f"RUN={shlex.quote(data['run_dir'])}")
print(f"DB={shlex.quote(data['db'])}")
print(f"AUTH_LOG={shlex.quote(data['auth_log'])}")
print(f"EVIDENCE={shlex.quote(data['evidence_dir'])}")
print(f"BASE={shlex.quote(data['urls']['web'])}")
PY
)"

python3 - "$DB" <<'PY' || exit 1
import sqlite3, sys
from pathlib import Path
path = Path(sys.argv[1])
if not path.exists():
    raise SystemExit(0)
conn = sqlite3.connect(path)
for table in ("users", "email_verification_tokens", "sessions"):
    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    if count:
        print(f"Refusing to sign up: {table} already has {count} rows in {path}", file=sys.stderr)
        raise SystemExit(1)
PY

WEB_PACKAGE="$ROOT/web/package.json" \
  VERIFY_BASE_URL="$BASE" \
  VERIFY_EMAIL="$EMAIL" \
  VERIFY_PASSWORD="$PASSWORD" \
  VERIFY_AUTH_LOG="$AUTH_LOG" \
  VERIFY_EVIDENCE="$EVIDENCE" \
  node "$SCRIPT_DIR/drive-signup.mjs"

python3 - "$DB" "$EMAIL" "$PASSWORD" "$EVIDENCE" <<'PY'
import pathlib, sqlite3, sys
db_path, email, password, evidence = sys.argv[1:]
evidence = pathlib.Path(evidence)
raw = pathlib.Path(db_path).read_bytes()
token_line = (evidence / "verification-log-line.txt").read_text()
token = token_line.rsplit("token=", 1)[1].strip()
problems = []
if password.encode() in raw:
    problems.append("password bytes are present in the sqlite file")
if token.encode() in raw:
    problems.append("raw verification token is present in the sqlite file")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
user = conn.execute(
    "SELECT email, password_hash, email_verified_at FROM users WHERE email = ?",
    (email,),
).fetchone()
tokens = list(conn.execute(
    "SELECT token_hash, expires_at, used_at FROM email_verification_tokens"
))
sessions = list(conn.execute(
    "SELECT token_hash, expires_at FROM sessions"
))
if user is None:
    problems.append("users row is missing")
elif not str(user["password_hash"]).startswith("$argon2id$"):
    problems.append(f"password_hash is not Argon2id: {user['password_hash'][:12]}")
elif not user["email_verified_at"]:
    problems.append("email_verified_at is empty after opening the link")
expected_token = (evidence / "verification-token-sha256.txt").read_text().strip()
if len(tokens) != 1 or tokens[0]["token_hash"] != expected_token:
    problems.append("email_verification_tokens does not contain the sha256 of the logged token")
elif not tokens[0]["used_at"]:
    problems.append("verification token used_at is empty")
expected_session = (evidence / "session-cookie-sha256.txt").read_text().strip()
if len(sessions) != 1 or sessions[0]["token_hash"] != expected_session:
    problems.append("sessions.token_hash is not the sha256 of the gsb_session cookie")
me = (evidence / "me.json").read_text()
if f'"email": "{email}"' not in me or '"status": 200' not in me:
    problems.append(f"/api/auth/me was not the verified user: {me}")
lines = [
    f"email {email}",
    f"password_hash_prefix {str(user['password_hash'])[:20] if user else 'missing'}",
    f"email_verified_at {user['email_verified_at'] if user else ''}",
    f"token_hash {tokens[0]['token_hash'] if tokens else ''}",
    f"token_used_at {tokens[0]['used_at'] if tokens else ''}",
    f"token_expires_at {tokens[0]['expires_at'] if tokens else ''}",
    f"session_hash {sessions[0]['token_hash'] if sessions else ''}",
    f"session_expires_at {sessions[0]['expires_at'] if sessions else ''}",
    f"password_in_db {'yes' if password.encode() in raw else 'no'}",
    f"raw_token_in_db {'yes' if token.encode() in raw else 'no'}",
]
(evidence / "db-rows.txt").write_text("\n".join(lines) + "\n")
if problems:
    print("SIGNUP PROOF FAIL")
    for item in problems:
        print(f"- {item}")
    sys.exit(1)
(evidence / "proof.txt").write_text(
    "signup-and-verification PASS\n"
    f"email {email}\n"
    "delivery log\n"
    "password_hash argon2id\n"
    "verification_token sha256 and used\n"
    "session_cookie sha256\n"
)
print("SIGNUP PROOF PASS")
print(evidence / "proof.txt")
PY
