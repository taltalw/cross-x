#!/usr/bin/env bash
# Annotate the complete atomic test corpus in all seven domains.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v4_arguments "$@"
v4_api_config

for domain in "${V4_DOMAINS[@]}"; do
  v4_input "$ATOMIC_ROOT/$domain/$V4_SPLIT.jsonl"
  v4_output "$V4_ROOT/0_extract_key_facts/$domain/$V4_SPLIT.jsonl"
done

for domain in "${V4_DOMAINS[@]}"; do
  "$PYTHON_BIN" "$SCRIPT_DIR/0_extract_key_facts.py" \
    --input "$ATOMIC_ROOT/$domain/$V4_SPLIT.jsonl" --source-domain "$domain" \
    --output "$V4_ROOT/0_extract_key_facts/$domain/$V4_SPLIT.jsonl" \
    "${STEP_0_ARGS[@]}" "${V4_WRITE_ARGS[@]}"
done
