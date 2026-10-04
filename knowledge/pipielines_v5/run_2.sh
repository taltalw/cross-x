#!/usr/bin/env bash
# Extract retrieval requirements for every plan produced by step 1.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v5_arguments "$@"
v5_api_config

for count in "${V5_DOMAIN_COUNTS[@]}"; do
  for domain in "${V5_DOMAINS[@]}"; do
    v5_input "$(v5_group_path 1_generate_fusion_plans "$domain" "$count")"
    v5_output "$(v5_group_path 2_extract_required_key_facts "$domain" "$count")"
  done
done

for count in "${V5_DOMAIN_COUNTS[@]}"; do
  for domain in "${V5_DOMAINS[@]}"; do
    "$PYTHON_BIN" "$SCRIPT_DIR/2_extract_required_key_facts.py" \
      --input "$(v5_group_path 1_generate_fusion_plans "$domain" "$count")" \
      --output "$(v5_group_path 2_extract_required_key_facts "$domain" "$count")" \
      --domain-count "$count" "${STEP_2_ARGS[@]}" "${V5_WRITE_ARGS[@]}"
  done
done
