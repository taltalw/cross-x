#!/usr/bin/env bash
# Embed corpus and requirement queries, then retrieve for every plan group.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v3_arguments "$@"
export CUDA_VISIBLE_DEVICES="$GPU_ID"

CORPUS_FILES=()
QUERY_FILES=()
for domain in "${V3_DOMAINS[@]}"; do
  v3_input "$ATOMIC_ROOT/$domain/$V3_SPLIT.jsonl"
  v3_input "$V3_ROOT/0_extract_key_facts/$domain/$V3_SPLIT.jsonl"
  CORPUS_FILES+=("$ATOMIC_ROOT/$domain/$V3_SPLIT.jsonl")
  for count in "${V3_DOMAIN_COUNTS[@]}"; do
    query_file="$(v3_group_path 2_extract_required_key_facts "$domain" "$count")"
    v3_input "$query_file"
    QUERY_FILES+=("$query_file")
    v3_output "$(v3_group_path 3_retrieve_key_fact_matches "$domain" "$count")"
  done
done

ENCODER_ARGS=(--embedding-root "$EMBEDDING_ROOT" --model "$EMBEDDING_MODEL"
  --device "$EMBEDDING_DEVICE" --dtype "$EMBEDDING_DTYPE" --batch-size "$EMBEDDING_BATCH_SIZE")

"$EMBEDDING_PYTHON_BIN" "$SCRIPT_DIR/../pipelines/embed_knowledge.py" \
  --kind corpus --input "${CORPUS_FILES[@]}" --splits "$V3_SPLIT" \
  "${ENCODER_ARGS[@]}" "${EMBEDDING_ARGS[@]}"
"$EMBEDDING_PYTHON_BIN" "$SCRIPT_DIR/embed_required_key_facts.py" \
  --kind queries --input "${QUERY_FILES[@]}" \
  "${ENCODER_ARGS[@]}" "${EMBEDDING_ARGS[@]}"

for count in "${V3_DOMAIN_COUNTS[@]}"; do
  for domain in "${V3_DOMAINS[@]}"; do
    "$PYTHON_BIN" "$SCRIPT_DIR/3_retrieve_key_fact_matches.py" \
      --input "$(v3_group_path 2_extract_required_key_facts "$domain" "$count")" \
      --output "$(v3_group_path 3_retrieve_key_fact_matches "$domain" "$count")" \
      --corpus "$V3_ROOT/0_extract_key_facts" --atomic-root "$ATOMIC_ROOT" \
      --embedding-root "$EMBEDDING_ROOT" --splits "$V3_SPLIT" --method hybrid \
      --domain-count "$count" --top-k "$TOP_K" --candidate-limit "$CANDIDATE_LIMIT" \
      "${RETRIEVAL_ARGS[@]}" "${V3_WRITE_ARGS[@]}"
  done
done
