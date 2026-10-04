#!/usr/bin/env bash
# Plan one fusion per source sample and requested total domain count.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v5_arguments "$@"
v5_api_config
v5_num_args

for count in "${V5_DOMAIN_COUNTS[@]}"; do
  for domain in "${V5_DOMAINS[@]}"; do
    v5_input "$V5_ROOT/0_extract_key_facts/$domain/$V5_SPLIT.jsonl"
    v5_output "$(v5_group_path 1_generate_fusion_plans "$domain" "$count")"
  done
done

for count in "${V5_DOMAIN_COUNTS[@]}"; do
  for domain in "${V5_DOMAINS[@]}"; do
    "$PYTHON_BIN" "$SCRIPT_DIR/1_generate_fusion_plans.py" \
      --input "$V5_ROOT/0_extract_key_facts/$domain/$V5_SPLIT.jsonl" \
      --output "$(v5_group_path 1_generate_fusion_plans "$domain" "$count")" \
      --domain-count "$count" "${V5_NUM_ARGS[@]}" "${STEP_1_ARGS[@]}" "${V5_WRITE_ARGS[@]}"
  done
done
