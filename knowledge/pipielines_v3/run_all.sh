#!/usr/bin/env bash
# Run all five stages after checking every source and output path.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v3_arguments "$@"
v3_api_config
v3_num_args

for domain in "${V3_DOMAINS[@]}"; do
  v3_input "$ATOMIC_ROOT/$domain/$V3_SPLIT.jsonl"
  v3_output "$V3_ROOT/0_extract_key_facts/$domain/$V3_SPLIT.jsonl"
  for count in "${V3_DOMAIN_COUNTS[@]}"; do
    for stage in 1_generate_fusion_plans 2_extract_required_key_facts \
                 3_retrieve_key_fact_matches 4_generate_fusion_question; do
      v3_output "$(v3_group_path "$stage" "$domain" "$count")"
    done
  done
done

"$PYTHON_BIN" -c 'import numpy'
"$EMBEDDING_PYTHON_BIN" -c 'import numpy, torch, transformers, safetensors, packaging'

for step in 0 1 2 3 4; do
  bash "$SCRIPT_DIR/run_${step}.sh" "$@"
done
