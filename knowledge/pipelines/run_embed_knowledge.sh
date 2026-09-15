#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
KNOWLEDGE_ROOT="${KNOWLEDGE_ROOT:-${SCRIPT_DIR}/..}"
# Edit settings here; Python downloads/loads MODEL_NAME with from_pretrained.
MODEL_NAME="Qwen/Qwen3-Embedding-8B"
GPU_ID="0"
DTYPE="bfloat16"
BATCH_SIZE=8
MAX_LENGTH=2048
CHUNK_OVERLAP=128
EMBEDDING_ROOT="$KNOWLEDGE_ROOT/embeddings/${MODEL_NAME##*/}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Prepare one shared corpus snapshot (train only by default).
CUDA_VISIBLE_DEVICES="$GPU_ID" "$PYTHON_BIN" "$SCRIPT_DIR/embed_knowledge.py" "$@" \
  --kind corpus --input "$KNOWLEDGE_ROOT/atomic" --embedding-root "$EMBEDDING_ROOT" \
  --model "$MODEL_NAME" --device cuda:0 --dtype "$DTYPE" --batch-size "$BATCH_SIZE" \
  --max-length "$MAX_LENGTH" --chunk-overlap "$CHUNK_OVERLAP"

# Prepare queries from both groups in the same vector space.
CUDA_VISIBLE_DEVICES="$GPU_ID" "$PYTHON_BIN" "$SCRIPT_DIR/embed_knowledge.py" "$@" \
  --kind queries \
  --input "$KNOWLEDGE_ROOT/results_5.5/2_generate_knowledge_queries" \
          "$KNOWLEDGE_ROOT/results_6/2_generate_knowledge_queries" \
  --embedding-root "$EMBEDDING_ROOT" --model "$MODEL_NAME" \
  --device cuda:0 --dtype "$DTYPE" --batch-size "$BATCH_SIZE" \
  --max-length "$MAX_LENGTH" --chunk-overlap "$CHUNK_OVERLAP"
