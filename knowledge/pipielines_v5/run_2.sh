#!/usr/bin/env bash
# Extract retrieval requirements for every plan produced by step 1.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v4_arguments "$@"
v4_api_config

for count in "${V4_DOMAIN_COUNTS[@]}"; do
  for domain in "${V4_DOMAINS[@]}"; do
    v4_input "$(v4_group_path 1_generate_fusion_plans "$domain" "$count")"
    v4_output "$(v4_group_path 2_extract_required_key_facts "$domain" "$count")"
  done
done

for count in "${V4_DOMAIN_COUNTS[@]}"; do
  for domain in "${V4_DOMAINS[@]}"; do
    "$PYTHON_BIN" "$SCRIPT_DIR/2_extract_required_key_facts.py" \
      --input "$(v4_group_path 1_generate_fusion_plans "$domain" "$count")" \
      --output "$(v4_group_path 2_extract_required_key_facts "$domain" "$count")" \
      --domain-count "$count" "${STEP_2_ARGS[@]}" "${V4_WRITE_ARGS[@]}"
  done
done
