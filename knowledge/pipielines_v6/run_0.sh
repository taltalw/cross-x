#!/usr/bin/env bash
# Annotate the complete atomic test corpus in all seven domains.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v5_arguments "$@"
v5_api_config

for domain in "${V5_DOMAINS[@]}"; do
  v5_input "$ATOMIC_ROOT/$domain/$V5_SPLIT.jsonl"
  v5_output "$V5_ROOT/0_extract_key_facts/$domain/$V5_SPLIT.jsonl"
done

for domain in "${V5_DOMAINS[@]}"; do
  "$PYTHON_BIN" "$SCRIPT_DIR/0_extract_key_facts.py" \
    --input "$ATOMIC_ROOT/$domain/$V5_SPLIT.jsonl" --source-domain "$domain" \
    --output "$V5_ROOT/0_extract_key_facts/$domain/$V5_SPLIT.jsonl" \
    "${STEP_0_ARGS[@]}" "${V5_WRITE_ARGS[@]}"
done
