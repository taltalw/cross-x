#!/usr/bin/env bash
# Screen retrieval evidence and generate three difficulties per accepted plan.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v3_arguments "$@"
v3_api_config

for count in "${V3_DOMAIN_COUNTS[@]}"; do
  for domain in "${V3_DOMAINS[@]}"; do
    v3_input "$(v3_group_path 3_retrieve_key_fact_matches "$domain" "$count")"
    v3_output "$(v3_group_path 4_generate_fusion_question "$domain" "$count")"
  done
done

for count in "${V3_DOMAIN_COUNTS[@]}"; do
  for domain in "${V3_DOMAINS[@]}"; do
    "$PYTHON_BIN" "$SCRIPT_DIR/4_generate_fusion_question.py" \
      --input "$(v3_group_path 3_retrieve_key_fact_matches "$domain" "$count")" \
      --output "$(v3_group_path 4_generate_fusion_question "$domain" "$count")" \
      --domain-count "$count" "${STEP_4_ARGS[@]}" "${V3_WRITE_ARGS[@]}"
  done
done
