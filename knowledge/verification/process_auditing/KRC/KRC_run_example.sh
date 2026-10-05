#!/usr/bin/env bash
set -euo pipefail

KRC_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
"${PYTHON_BIN:-python3}" -X utf8 "${KRC_SCRIPT_DIR}/KRC_evaluate.py" \
  --input "${KRC_SCRIPT_DIR}/../../../pipielines_v4/outputs/3_retrieve_key_fact_matches" \
  --sample-manifest "${KRC_SCRIPT_DIR}/../KNC/KNC_outputs/knc_saved_pilot21/run_manifest.json" \
  --output "${KRC_SCRIPT_DIR}/KRC_outputs/KRC_pilot21" \
  --seed 42 --threshold 0.50 --alpha 0.50 \
  "$@"
