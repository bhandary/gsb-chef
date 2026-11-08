#!/usr/bin/env bash
# Read-only check that the current verification instance is worth driving.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$SCRIPT_DIR/../../../.." && pwd)
CURRENT="$ROOT/verification-runs/current"
PORTS_PY="$SCRIPT_DIR/ports.py"

if [[ ! -f "$CURRENT/instance.json" ]]; then
  echo "No verification instance. Run scripts/launch.sh first." >&2
  exit 1
fi

python3 - "$CURRENT/instance.json" "$ROOT" "$PORTS_PY" <<'PY'
import json, os, subprocess, sys, urllib.error, urllib.request

instance_path, root, ports_py = sys.argv[1:]
data = json.load(open(instance_path))
problems = []

head = subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True).strip()
if head != data["head"]:
    problems.append(f"git HEAD is {head}, launch recorded {data['head']}")

for name, leader in data["groups"].items():
    leader = int(leader)
    try:
        os.kill(leader, 0)
    except OSError:
        problems.append(f"{name} process group leader {leader} is not running")

raw = subprocess.check_output([sys.executable, ports_py, "listeners", "8000", "2024", "3000"], text=True)
rows = json.loads(raw)
by_port = {}
for row in rows:
    by_port.setdefault(int(row["port"]), []).append(row)

expected = {"auth": 8000, "langgraph": 2024, "web": 3000}
for name, port in expected.items():
    listeners = by_port.get(port, [])
    if not listeners:
        problems.append(f"nothing is listening on {port}")
        continue
    leader = int(data["groups"][name])
    owned = []
    for row in listeners:
        result = subprocess.run(
            [sys.executable, ports_py, "owned", str(row["pid"]), str(leader)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            owned.append(row["pid"])
    if not owned:
        problems.append(
            f"port {port} listeners {[row['pid'] for row in listeners]} are not in the {name} group {leader}"
        )

def fetch(url, method="GET", payload=None):
    req = urllib.request.Request(url, data=payload, method=method)
    if payload is not None:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        return 0, str(exc).encode()

status, body = fetch(data["urls"]["auth"] + "/auth/me")
if status != 401 or json.loads(body).get("error") != "Sign in required.":
    problems.append(f"auth /auth/me returned {status} {body[:120]!r}")

status, body = fetch(data["urls"]["langgraph"] + "/ok")
if status != 200 or json.loads(body).get("ok") is not True:
    problems.append(f"langgraph /ok returned {status} {body[:120]!r}")

status, body = fetch(
    data["urls"]["langgraph"] + "/assistants/search",
    method="POST",
    payload=b"{}",
)
rows = json.loads(body) if status == 200 else []
if status != 200 or not any(row.get("graph_id") == "agent" for row in rows):
    problems.append(f"langgraph assistants/search returned {status}")

status, body = fetch(data["urls"]["web"] + "/")
if status != 200 or b"<title>GSB Chef</title>" not in body:
    problems.append(f"web UI returned {status} without the GSB Chef title")

status, body = fetch(data["urls"]["web"] + "/api/auth/me")
if status != 401 or json.loads(body).get("error") != "Sign in required.":
    problems.append(f"web /api/auth/me returned {status} {body[:120]!r}")

status, body = fetch(data["urls"]["web"] + "/api/ok")
if status != 401 or json.loads(body).get("error") != "Sign in required.":
    problems.append(f"web /api/ok without a session returned {status} {body[:120]!r}")

if problems:
    print("DOCTOR FAIL")
    for item in problems:
        print(f"- {item}")
    sys.exit(1)

print("DOCTOR OK")
print(f"head {head}")
print(f"run {data['run_dir']}")
print(f"groups {data['groups']}")
PY
