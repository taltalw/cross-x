#!/usr/bin/env bash
# Generate questions for all seven sources x domain counts 2/3/4.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v2_arguments "$@"
v2_api_config
for count in "${V2_DOMAIN_COUNTS[@]}"; do
  for domain in "${V2_DOMAINS[@]}"; do
    v2_input "$(v2_group_path 3_retrieve_key_fact_matches "$domain" "$count")"
    v2_output "$(v2_group_path 4_generate_fusion_question "$domain" "$count")"
  done
done
for count in "${V2_DOMAIN_COUNTS[@]}"; do
  for domain in "${V2_DOMAINS[@]}"; do
    "$PYTHON_BIN" "$SCRIPT_DIR/4_generate_fusion_question.py" \
      --input "$(v2_group_path 3_retrieve_key_fact_matches "$domain" "$count")" \
      --output "$(v2_group_path 4_generate_fusion_question "$domain" "$count")" \
      --domain-count "$count" "${STEP_4_ARGS[@]}" "${V2_WRITE_ARGS[@]}"
  done
done
