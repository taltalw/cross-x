#!/usr/bin/env bash
set -euo pipefail

# Retrieval reads the completed local embeddings; no model or API configuration.
METHOD="${METHOD:-hybrid}" # hybrid, or bm25 for lexical-only retrieval

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
KNOWLEDGE_ROOT="${KNOWLEDGE_ROOT:-${SCRIPT_DIR}/..}"
EMBEDDING_ROOT="${EMBEDDING_ROOT:-${KNOWLEDGE_ROOT}/embeddings/Qwen3-Embedding-8B}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
RESULT_GROUPS=(results_5.5 results_6)
shopt -s nullglob dotglob
for RESULT_GROUP in "${RESULT_GROUPS[@]}"; do
  INPUT_ROOT="$KNOWLEDGE_ROOT/$RESULT_GROUP/2_generate_knowledge_queries"
  OUTPUT_ROOT="$KNOWLEDGE_ROOT/$RESULT_GROUP/3_retrieve_knowledge"
  INPUT_FILES=()
  for INPUT_FILE in "$INPUT_ROOT"/*.jsonl; do
    [[ -f "$INPUT_FILE" ]] && INPUT_FILES+=("$INPUT_FILE")
  done
  if (( ${#INPUT_FILES[@]} == 0 )); then
    printf 'No JSONL files found in: %s\n' "$INPUT_ROOT" >&2
    exit 1
  fi
  # One process per group keeps corpus indexes in memory across its files.
  "$PYTHON_BIN" "$SCRIPT_DIR/3_retrieve_knowledge.py" "$@" \
    --method "$METHOD" --atomic-root "$KNOWLEDGE_ROOT/atomic" \
    --embedding-root "$EMBEDDING_ROOT" \
    --input "${INPUT_FILES[@]}" --output-root "$OUTPUT_ROOT"
done
