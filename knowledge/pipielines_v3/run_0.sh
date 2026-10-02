#!/usr/bin/env bash
# Annotate the complete atomic test corpus in all seven domains.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v3_arguments "$@"
v3_api_config

for domain in "${V3_DOMAINS[@]}"; do
  v3_input "$ATOMIC_ROOT/$domain/$V3_SPLIT.jsonl"
  v3_output "$V3_ROOT/0_extract_key_facts/$domain/$V3_SPLIT.jsonl"
done

for domain in "${V3_DOMAINS[@]}"; do
  "$PYTHON_BIN" "$SCRIPT_DIR/0_extract_key_facts.py" \
    --input "$ATOMIC_ROOT/$domain/$V3_SPLIT.jsonl" --source-domain "$domain" \
    --output "$V3_ROOT/0_extract_key_facts/$domain/$V3_SPLIT.jsonl" \
    "${STEP_0_ARGS[@]}" "${V3_WRITE_ARGS[@]}"
done
