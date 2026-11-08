#!/usr/bin/env bash
# Start one isolated gsb-chef verification instance from an empty auth database.
# Two instances cannot share ports 8000, 2024, and 3000 or the repo-root .langgraph_api directory.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$SCRIPT_DIR/../../../.." && pwd)
PORTS_PY="$SCRIPT_DIR/ports.py"
RUNS="$ROOT/verification-runs"
CURRENT="$RUNS/current"

cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python" || ! -x "$ROOT/.venv/bin/langgraph" ]]; then
  echo "Missing $ROOT/.venv. From the repo root: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi
if [[ ! -x "$ROOT/web/node_modules/.bin/next" ]]; then
  echo "Missing $ROOT/web/node_modules. From web/: pnpm install" >&2
  exit 1
fi
if [[ ! -f "$ROOT/web/node_modules/@playwright/test/package.json" ]]; then
  echo "Missing @playwright/test in web/node_modules. From web/: pnpm install" >&2
  exit 1
fi

busy=$(python3 "$PORTS_PY" busy 8000 2024 3000 || true)
if [[ "$busy" != "[]" ]]; then
  echo "Ports 8000, 2024, or 3000 are already in use. This app cannot run two instances side by side." >&2
  echo "$busy" >&2
  exit 1
fi

if [[ -f "$CURRENT/instance.json" ]]; then
  if python3 - "$CURRENT/instance.json" <<'PY'
import json, os, sys
data = json.load(open(sys.argv[1]))
alive = False
for leader in data.get("groups", {}).values():
    try:
        os.kill(int(leader), 0)
        alive = True
    except OSError:
        pass
sys.exit(0 if alive else 1)
PY
  then
    echo "verification-runs/current still has live process groups. Run scripts/cleanup.sh before launching another instance." >&2
    exit 1
  fi
fi

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
RUN="$RUNS/$STAMP"
mkdir -p "$RUN/data" "$RUN/logs" "$RUN/evidence"
if [[ -e "$RUN/data/auth.db" ]]; then
  echo "Refusing to launch: $RUN/data/auth.db already exists." >&2
  exit 1
fi

HEAD=$(git -C "$ROOT" rev-parse HEAD)
AUTH_LOG="$RUN/logs/auth.log"
LANGGRAPH_LOG="$RUN/logs/langgraph.log"
WEB_LOG="$RUN/logs/web.log"
: >"$AUTH_LOG"
: >"$LANGGRAPH_LOG"
: >"$WEB_LOG"

set -m
AUTH_PID=""
LANGGRAPH_PID=""
WEB_PID=""

write_instance() {
  python3 - "$RUN/instance.json" <<PY
import json
json.dump({
  "stamp": "$STAMP",
  "head": "$HEAD",
  "root": "$ROOT",
  "run_dir": "$RUN",
  "db": "$RUN/data/auth.db",
  "auth_log": "$AUTH_LOG",
  "langgraph_log": "$LANGGRAPH_LOG",
  "web_log": "$WEB_LOG",
  "evidence_dir": "$RUN/evidence",
  "groups": {"auth": ${AUTH_PID:-0}, "langgraph": ${LANGGRAPH_PID:-0}, "web": ${WEB_PID:-0}},
  "ports": {"auth": 8000, "langgraph": 2024, "web": 3000},
  "urls": {
    "web": "http://127.0.0.1:3000",
    "auth": "http://127.0.0.1:8000",
    "langgraph": "http://127.0.0.1:2024"
  }
}, open("$RUN/instance.json", "w"), indent=2)
open("$RUN/instance.json", "a").write("\n")
PY
  ln -sfn "$RUN" "$CURRENT"
}

stop_started() {
  for pid in "$WEB_PID" "$LANGGRAPH_PID" "$AUTH_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    fi
  done
}

fail() {
  echo "$1" >&2
  if [[ -f "$RUN/instance.json" ]]; then
    bash "$SCRIPT_DIR/cleanup.sh" || true
  else
    stop_started
  fi
  exit 1
}

cd "$ROOT"
SMTP_HOST= SMTP_PASSWORD= APP_BASE_URL=http://127.0.0.1:3000 \
  GOOGLE_CLIENT_ID= GOOGLE_CLIENT_SECRET= GOOGLE_DISCOVERY_URL= \
  GSB_AUTH_DB="$RUN/data/auth.db" AUTH_HOST=127.0.0.1 AUTH_PORT=8000 \
  "$ROOT/.venv/bin/python" -m auth_app >>"$AUTH_LOG" 2>&1 &
AUTH_PID=$!

SMTP_HOST= LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false \
  "$ROOT/.venv/bin/langgraph" dev --no-browser --host 127.0.0.1 --port 2024 \
  >>"$LANGGRAPH_LOG" 2>&1 &
LANGGRAPH_PID=$!

cd "$ROOT/web"
NEXT_PUBLIC_API_URL=http://localhost:2024 NEXT_PUBLIC_ASSISTANT_ID=agent \
  AUTH_API_URL=http://127.0.0.1:8000 \
  "$ROOT/web/node_modules/.bin/next" dev --hostname 127.0.0.1 --port 3000 \
  >>"$WEB_LOG" 2>&1 &
WEB_PID=$!
cd "$ROOT"

write_instance

wait_code() {
  local url=$1 expect=$2 bodyfile=$3
  local code=""
  for _ in $(seq 1 90); do
    code=$(curl -s -o "$bodyfile" -w '%{http_code}' --max-time 2 "$url" || true)
    if [[ "$code" == "$expect" ]]; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for $url to return $expect (last status ${code:-none})." >&2
  return 1
}

wait_code "http://127.0.0.1:8000/auth/me" 401 "$RUN/evidence/ready-auth-me.json" || fail "Auth server did not become ready. See $AUTH_LOG"
python3 - "$RUN/evidence/ready-auth-me.json" <<'PY' || fail "Auth /auth/me was 401 but the body was not the sign-in error."
import json, sys
body = json.load(open(sys.argv[1]))
assert body.get("error") == "Sign in required.", body
PY

wait_code "http://127.0.0.1:2024/ok" 200 "$RUN/evidence/ready-langgraph-ok.json" || fail "LangGraph did not become ready. See $LANGGRAPH_LOG"
python3 - "$RUN/evidence/ready-langgraph-ok.json" <<'PY' || fail "LangGraph /ok did not report ok:true."
import json, sys
body = json.load(open(sys.argv[1]))
assert body.get("ok") is True, body
PY

for _ in $(seq 1 30); do
  code=$(curl -s -o "$RUN/evidence/ready-assistants.json" -w '%{http_code}' --max-time 3 \
    -X POST "http://127.0.0.1:2024/assistants/search" \
    -H 'content-type: application/json' -d '{}' || true)
  if [[ "$code" == "200" ]] && python3 - "$RUN/evidence/ready-assistants.json" <<'PY'
import json, sys
rows = json.load(open(sys.argv[1]))
assert any(row.get("graph_id") == "agent" and row.get("name") == "agent" for row in rows)
PY
  then
    break
  fi
  sleep 1
done
python3 - "$RUN/evidence/ready-assistants.json" <<'PY' || fail "LangGraph has no assistant with graph_id agent. See $LANGGRAPH_LOG"
import json, sys
rows = json.load(open(sys.argv[1]))
assert any(row.get("graph_id") == "agent" for row in rows), rows
PY

wait_code "http://127.0.0.1:3000/" 200 "$RUN/evidence/ready-web.html" || fail "Web UI did not become ready. See $WEB_LOG"
grep -q "<title>GSB Chef</title>" "$RUN/evidence/ready-web.html" || fail "Web UI responded but the title was not GSB Chef."
wait_code "http://127.0.0.1:3000/api/auth/me" 401 "$RUN/evidence/ready-proxy-me.json" || fail "Next /api/auth/me did not proxy to the auth server."
python3 - "$RUN/evidence/ready-proxy-me.json" <<'PY' || fail "Next /api/auth/me body was not the sign-in error."
import json, sys
body = json.load(open(sys.argv[1]))
assert body.get("error") == "Sign in required.", body
PY

if ! WEB_PACKAGE="$ROOT/web/package.json" node --input-type=module -e '
import { createRequire } from "node:module";
const require = createRequire(process.env.WEB_PACKAGE);
const { chromium } = require("@playwright/test");
const browser = await chromium.launch({ channel: "chrome", args: ["--no-sandbox", "--disable-dev-shm-usage"] });
const page = await browser.newPage();
await page.goto("http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
await page.getByLabel("Email").waitFor({ timeout: 30000 });
await page.getByRole("button", { name: "Create account" }).waitFor({ timeout: 5000 });
await browser.close();
'; then
  fail "The web UI answered HTTP 200 but the sign-up form did not hydrate. See $WEB_LOG"
fi

python3 - "$RUN/data/auth.db" <<'PY' || fail "Auth database was not empty before sign-up."
import sqlite3, sys
from pathlib import Path
path = Path(sys.argv[1])
if not path.exists():
    raise SystemExit(0)
conn = sqlite3.connect(path)
for table in ("users", "email_verification_tokens", "sessions"):
    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    if count:
        raise SystemExit(f"{table} has {count} rows")
PY

echo "READY $RUN"
echo "HEAD $HEAD"
echo "auth log $AUTH_LOG"
echo "evidence $RUN/evidence"
