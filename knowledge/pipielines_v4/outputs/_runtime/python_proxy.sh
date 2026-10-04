#!/usr/bin/env bash
set -euo pipefail
RUNTIME_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$RUNTIME_DIR/../../../pipielines_v3/.env/bin/python" "$RUNTIME_DIR/adapter.py" "$@"
