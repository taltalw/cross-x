#!/usr/bin/env bash
# Rerun stages 2, 3, and 4 using existing stages 0 and 1 outputs.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v5_arguments "$@"
v5_api_config

for domain in "${V5_DOMAINS[@]}"; do
  v5_input "$ATOMIC_ROOT/$domain/$V5_SPLIT.jsonl"
  v5_input "$V5_ROOT/0_extract_key_facts/$domain/$V5_SPLIT.jsonl"
  for count in "${V5_DOMAIN_COUNTS[@]}"; do
    v5_input "$(v5_group_path 1_generate_fusion_plans "$domain" "$count")"
    v5_output "$(v5_group_path 2_extract_required_key_facts "$domain" "$count")"
    v5_output "$(v5_group_path 3_retrieve_key_fact_matches "$domain" "$count")"
    v5_output "$(v5_group_path 4_generate_fusion_question "$domain" "$count")"
  done
done

"$PYTHON_BIN" -c 'import numpy'
"$EMBEDDING_PYTHON_BIN" -c 'import numpy, torch, transformers, safetensors, packaging'

for step in 2 3 4; do
  bash "$SCRIPT_DIR/run_${step}.sh" "$@"
done
