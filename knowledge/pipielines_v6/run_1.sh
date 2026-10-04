#!/usr/bin/env bash
# Plan one fusion per source sample and requested total domain count.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v4_arguments "$@"
v4_api_config
v4_num_args

for count in "${V4_DOMAIN_COUNTS[@]}"; do
  for domain in "${V4_DOMAINS[@]}"; do
    v4_input "$V4_ROOT/0_extract_key_facts/$domain/$V4_SPLIT.jsonl"
    v4_output "$(v4_group_path 1_generate_fusion_plans "$domain" "$count")"
  done
done

for count in "${V4_DOMAIN_COUNTS[@]}"; do
  for domain in "${V4_DOMAINS[@]}"; do
    "$PYTHON_BIN" "$SCRIPT_DIR/1_generate_fusion_plans.py" \
      --input "$V4_ROOT/0_extract_key_facts/$domain/$V4_SPLIT.jsonl" \
      --output "$(v4_group_path 1_generate_fusion_plans "$domain" "$count")" \
      --domain-count "$count" "${V4_NUM_ARGS[@]}" "${STEP_1_ARGS[@]}" "${V4_WRITE_ARGS[@]}"
  done
done
