#!/usr/bin/env bash
# Full test annotations -> all seven sources x domain counts 2/3/4 -> requirements.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v2_arguments "$@"
v2_api_config
PLAN_NUM_ARGS=()
if [[ "$NUM" != all ]]; then
  [[ "$NUM" =~ ^[1-9][0-9]*$ ]] || { printf 'NUM must be a positive integer or all.\n' >&2; exit 2; }
  PLAN_NUM_ARGS=(--num "$NUM")
fi

# Preflight all sources and targets before the first paid request.
for domain in "${V2_DOMAINS[@]}"; do
  v2_input "$ATOMIC_ROOT/$domain/$V2_SPLIT.jsonl"
  v2_output "$V2_ROOT/0_extract_key_facts/$domain/$V2_SPLIT.jsonl"
  for count in "${V2_DOMAIN_COUNTS[@]}"; do
    v2_output "$(v2_group_path 1_generate_fusion_plans "$domain" "$count")"
    v2_output "$(v2_group_path 2_extract_required_key_facts "$domain" "$count")"
  done
done

# 0: process EVERY sample; NUM deliberately applies only to step 1.
for domain in "${V2_DOMAINS[@]}"; do
  "$PYTHON_BIN" "$SCRIPT_DIR/0_extract_key_facts.py" \
    --input "$ATOMIC_ROOT/$domain/$V2_SPLIT.jsonl" --source-domain "$domain" \
    --output "$V2_ROOT/0_extract_key_facts/$domain/$V2_SPLIT.jsonl" \
    "${STEP_0_ARGS[@]}" "${V2_WRITE_ARGS[@]}"
done

# 1: one model-selected combination per source sample for each requested total count.
for count in "${V2_DOMAIN_COUNTS[@]}"; do
  for domain in "${V2_DOMAINS[@]}"; do
    "$PYTHON_BIN" "$SCRIPT_DIR/1_generate_fusion_plans.py" \
      --input "$V2_ROOT/0_extract_key_facts/$domain/$V2_SPLIT.jsonl" \
      --output "$(v2_group_path 1_generate_fusion_plans "$domain" "$count")" \
      --domain-count "$count" "${PLAN_NUM_ARGS[@]}" "${STEP_1_ARGS[@]}" "${V2_WRITE_ARGS[@]}"
  done
done

# 2: consume every record produced in step 1, without a separate sample limit.
for count in "${V2_DOMAIN_COUNTS[@]}"; do
  for domain in "${V2_DOMAINS[@]}"; do
    "$PYTHON_BIN" "$SCRIPT_DIR/2_extract_required_key_facts.py" \
      --input "$(v2_group_path 1_generate_fusion_plans "$domain" "$count")" \
      --output "$(v2_group_path 2_extract_required_key_facts "$domain" "$count")" \
      --domain-count "$count" "${STEP_2_ARGS[@]}" "${V2_WRITE_ARGS[@]}"
  done
done
