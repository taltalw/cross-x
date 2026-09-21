#!/usr/bin/env bash
set -euo pipefail

SOURCE_DOMAIN="${SOURCE_DOMAIN:-geography}"
DOMAIN_COUNT="${DOMAIN_COUNT:-3}"
ATOMIC_SPLIT="${ATOMIC_SPLIT:-test}"
NUM="${NUM:-10}"
TOP_K="${TOP_K:-10}"
CANDIDATE_LIMIT="${CANDIDATE_LIMIT:-20}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
V2_ROOT="${V2_ROOT:-${SCRIPT_DIR}/outputs}"
CORPUS_ROOT="${CORPUS_ROOT:-${V2_ROOT}/0_extract_key_facts}"
INPUT_ROOT="${INPUT_ROOT:-${V2_ROOT}/2_extract_required_key_facts}"
OUTPUT_ROOT="${OUTPUT_ROOT:-${V2_ROOT}/3_retrieve_key_fact_matches}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
EMBEDDING_ROOT="${EMBEDDING_ROOT:-${SCRIPT_DIR}/../embeddings/Qwen3-Embedding-8B}"
ATOMIC_ROOT="${ATOMIC_ROOT:-${SCRIPT_DIR}/../atomic}"
METHOD="${METHOD:-hybrid}"

"$PYTHON_BIN" "$SCRIPT_DIR/3_retrieve_key_fact_matches.py" \
  --input "$INPUT_ROOT/$SOURCE_DOMAIN/${ATOMIC_SPLIT}_domain_count_${DOMAIN_COUNT}.jsonl" --corpus "$CORPUS_ROOT" \
  --output "$OUTPUT_ROOT/$SOURCE_DOMAIN/${ATOMIC_SPLIT}_domain_count_${DOMAIN_COUNT}.jsonl" \
  --domain-count "$DOMAIN_COUNT" \
  --method "$METHOD" --embedding-root "$EMBEDDING_ROOT" --atomic-root "$ATOMIC_ROOT" \
  --top-k "$TOP_K" --candidate-limit "$CANDIDATE_LIMIT" --num "$NUM" "$@"
