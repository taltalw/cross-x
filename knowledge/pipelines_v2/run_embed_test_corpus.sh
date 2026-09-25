#!/usr/bin/env bash
# Embed all seven atomic test corpora into the same store as the v2 query vectors.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ATOMIC_ROOT="${ATOMIC_ROOT:-${SCRIPT_DIR}/../atomic}"
EMBEDDING_ROOT="${EMBEDDING_ROOT:-${SCRIPT_DIR}/../embeddings/v2-test-Qwen3-Embedding-8B}"
PYTHON_BIN="${PYTHON_BIN:-/mnt/data1/wangyatong/anaconda3/envs/crossx/bin/python}"
GPU_ID="${GPU_ID:-1}"
BATCH_SIZE="${BATCH_SIZE:-8}"
export CUDA_VISIBLE_DEVICES="$GPU_ID"

DOMAINS=(medical legal financial mathematics computer_science geography chemistry)
CORPUS_FILES=()
for domain in "${DOMAINS[@]}"; do
  corpus_file="$ATOMIC_ROOT/$domain/test.jsonl"
  [[ -f "$corpus_file" ]] || { printf 'Missing test corpus: %s\n' "$corpus_file" >&2; exit 1; }
  CORPUS_FILES+=("$corpus_file")
done

# One model load for all domains. Reuse the store's model, dtype, revision,
# chunking, and query instruction so corpus/query vectors remain compatible.
# Physical GPU 1 is exposed as logical cuda:0 inside this process.
"$PYTHON_BIN" "$SCRIPT_DIR/../pipelines/embed_knowledge.py" \
  --batch-size "$BATCH_SIZE" "$@" \
  --kind corpus --input "${CORPUS_FILES[@]}" --splits test \
  --embedding-root "$EMBEDDING_ROOT" --device cuda:0
