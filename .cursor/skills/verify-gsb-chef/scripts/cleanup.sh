#!/usr/bin/env bash
# Stop the process groups this verification launch started. Evidence directories stay.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$SCRIPT_DIR/../../../.." && pwd)
CURRENT="$ROOT/verification-runs/current"

if [[ ! -f "$CURRENT/instance.json" ]]; then
  echo "No verification instance to clean up."
  exit 0
fi

RUN=$(readlink -f "$CURRENT")
case "$RUN" in
  "$ROOT/verification-runs"/*) ;;
  *)
    echo "Refusing to clean $RUN; it is outside verification-runs." >&2
    exit 1
    ;;
esac

python3 - "$RUN/instance.json" <<'PY'
import json, os, signal, sys, time
data = json.load(open(sys.argv[1]))
leaders = [int(pid) for pid in data["groups"].values() if int(pid) > 1]

def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

for pid in leaders:
    if not alive(pid):
        continue
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass

deadline = time.time() + 10
while time.time() < deadline and any(alive(pid) for pid in leaders):
    time.sleep(0.2)

for pid in leaders:
    if not alive(pid):
        continue
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

still = [pid for pid in leaders if alive(pid)]
if still:
    print(f"CLEANUP FAIL still running: {still}", file=sys.stderr)
    sys.exit(1)
print("CLEANUP OK")
print(f"evidence kept at {data['evidence_dir']}")
PY
