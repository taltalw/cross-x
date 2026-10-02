#!/usr/bin/env bash
# Extract retrieval requirements for every plan produced by step 1.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v3_arguments "$@"
v3_api_config

for count in "${V3_DOMAIN_COUNTS[@]}"; do
  for domain in "${V3_DOMAINS[@]}"; do
    v3_input "$(v3_group_path 1_generate_fusion_plans "$domain" "$count")"
    v3_output "$(v3_group_path 2_extract_required_key_facts "$domain" "$count")"
  done
done

for count in "${V3_DOMAIN_COUNTS[@]}"; do
  for domain in "${V3_DOMAINS[@]}"; do
    "$PYTHON_BIN" "$SCRIPT_DIR/2_extract_required_key_facts.py" \
      --input "$(v3_group_path 1_generate_fusion_plans "$domain" "$count")" \
      --output "$(v3_group_path 2_extract_required_key_facts "$domain" "$count")" \
      --domain-count "$count" "${STEP_2_ARGS[@]}" "${V3_WRITE_ARGS[@]}"
  done
done
