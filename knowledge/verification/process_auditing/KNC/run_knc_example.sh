#!/usr/bin/env bash
set -euo pipefail

KNC_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
"${PYTHON_BIN:-python3}" -X utf8 "${KNC_SCRIPT_DIR}/knowledge_need_coverage.py" \
  --input "${KNC_SCRIPT_DIR}/../../../pipielines_v4/outputs/3_retrieve_key_fact_matches" \
  --output "${KNC_SCRIPT_DIR}/KNC_outputs/knc_saved_pilot21" \
  --samples-per-source 1 --seed 42 \
  "$@"
