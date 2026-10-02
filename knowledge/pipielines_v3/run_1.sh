#!/usr/bin/env bash
# Plan one fusion per source sample and requested total domain count.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v3_arguments "$@"
v3_api_config
v3_num_args

for count in "${V3_DOMAIN_COUNTS[@]}"; do
  for domain in "${V3_DOMAINS[@]}"; do
    v3_input "$V3_ROOT/0_extract_key_facts/$domain/$V3_SPLIT.jsonl"
    v3_output "$(v3_group_path 1_generate_fusion_plans "$domain" "$count")"
  done
done

for count in "${V3_DOMAIN_COUNTS[@]}"; do
  for domain in "${V3_DOMAINS[@]}"; do
    "$PYTHON_BIN" "$SCRIPT_DIR/1_generate_fusion_plans.py" \
      --input "$V3_ROOT/0_extract_key_facts/$domain/$V3_SPLIT.jsonl" \
      --output "$(v3_group_path 1_generate_fusion_plans "$domain" "$count")" \
      --domain-count "$count" "${V3_NUM_ARGS[@]}" "${STEP_1_ARGS[@]}" "${V3_WRITE_ARGS[@]}"
  done
done
