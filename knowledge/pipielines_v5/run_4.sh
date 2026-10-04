#!/usr/bin/env bash
# Screen retrieval evidence and generate three difficulties per accepted plan.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v5_arguments "$@"
v5_api_config

for count in "${V5_DOMAIN_COUNTS[@]}"; do
  for domain in "${V5_DOMAINS[@]}"; do
    v5_input "$(v5_group_path 3_retrieve_key_fact_matches "$domain" "$count")"
    v5_output "$(v5_group_path 4_generate_fusion_question "$domain" "$count")"
  done
done

for count in "${V5_DOMAIN_COUNTS[@]}"; do
  for domain in "${V5_DOMAINS[@]}"; do
    "$PYTHON_BIN" "$SCRIPT_DIR/4_generate_fusion_question.py" \
      --input "$(v5_group_path 3_retrieve_key_fact_matches "$domain" "$count")" \
      --output "$(v5_group_path 4_generate_fusion_question "$domain" "$count")" \
      --domain-count "$count" "${STEP_4_ARGS[@]}" "${V5_WRITE_ARGS[@]}"
  done
done
