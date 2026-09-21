#!/usr/bin/env bash
# Embed complete test corpora and the 21 requirement files, then retrieve all groups.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v2_arguments "$@"
CORPUS_FILES=()
QUERY_FILES=()
for domain in "${V2_DOMAINS[@]}"; do
  v2_input "$ATOMIC_ROOT/$domain/$V2_SPLIT.jsonl"
  v2_input "$V2_ROOT/0_extract_key_facts/$domain/$V2_SPLIT.jsonl"
  CORPUS_FILES+=("$ATOMIC_ROOT/$domain/$V2_SPLIT.jsonl")
  for count in "${V2_DOMAIN_COUNTS[@]}"; do
    query_file="$(v2_group_path 2_extract_required_key_facts "$domain" "$count")"
    v2_input "$query_file"
    QUERY_FILES+=("$query_file")
    v2_output "$(v2_group_path 3_retrieve_key_fact_matches "$domain" "$count")"
  done
done
ENCODER_ARGS=(--embedding-root "$EMBEDDING_ROOT" --model "$EMBEDDING_MODEL"
  --device "$EMBEDDING_DEVICE" --dtype "$EMBEDDING_DTYPE" --batch-size "$EMBEDDING_BATCH_SIZE")

"$EMBEDDING_PYTHON_BIN" "$SCRIPT_DIR/../pipelines/embed_knowledge.py" \
  --kind corpus --input "${CORPUS_FILES[@]}" --splits "$V2_SPLIT" \
  "${ENCODER_ARGS[@]}" "${EMBEDDING_ARGS[@]}"
"$EMBEDDING_PYTHON_BIN" "$SCRIPT_DIR/embed_required_key_facts.py" \
  --kind queries --input "${QUERY_FILES[@]}" "${ENCODER_ARGS[@]}" "${EMBEDDING_ARGS[@]}"

for count in "${V2_DOMAIN_COUNTS[@]}"; do
  for domain in "${V2_DOMAINS[@]}"; do
    "$PYTHON_BIN" "$SCRIPT_DIR/3_retrieve_key_fact_matches.py" \
      --input "$(v2_group_path 2_extract_required_key_facts "$domain" "$count")" \
      --output "$(v2_group_path 3_retrieve_key_fact_matches "$domain" "$count")" \
      --corpus "$V2_ROOT/0_extract_key_facts" --atomic-root "$ATOMIC_ROOT" \
      --embedding-root "$EMBEDDING_ROOT" --splits "$V2_SPLIT" --method hybrid \
      --domain-count "$count" --top-k "$TOP_K" --candidate-limit "$CANDIDATE_LIMIT" \
      "${RETRIEVAL_ARGS[@]}" "${V2_WRITE_ARGS[@]}"
  done
done
