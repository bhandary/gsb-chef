#!/usr/bin/env bash
# Drive thumbs feedback on a seeded chef reply. Run this after drive-signup.sh.
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
print(f"EVIDENCE={shlex.quote(data['evidence_dir'])}")
print(f"BASE={shlex.quote(data['urls']['web'])}")
PY
)"

WEB_PACKAGE="$ROOT/web/package.json" \
  VERIFY_BASE_URL="$BASE" \
  VERIFY_EMAIL="$EMAIL" \
  VERIFY_PASSWORD="$PASSWORD" \
  VERIFY_EVIDENCE="$EVIDENCE" \
  node "$SCRIPT_DIR/drive-feedback.mjs"
