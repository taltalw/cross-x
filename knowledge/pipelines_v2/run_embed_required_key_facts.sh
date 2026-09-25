#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Defaults for the completed 2026-09-22 run; environment variables may override them.
V2_ROOT="${V2_ROOT:-${SCRIPT_DIR}/../../run_012_joyrouter_20260922}"
INPUT_ROOT="${INPUT_ROOT:-${V2_ROOT}/2_extract_required_key_facts}"
EMBEDDING_ROOT="${EMBEDDING_ROOT:-${SCRIPT_DIR}/../embeddings/v2-test-Qwen3-Embedding-8B}"
PYTHON_BIN="${PYTHON_BIN:-/mnt/data1/wangyatong/anaconda3/envs/crossx/bin/python}"
GPU_ID="${GPU_ID:-1}"
# Expose only physical GPU 1 by default; it becomes cuda:0 inside this process.
export CUDA_VISIBLE_DEVICES="$GPU_ID"
# Existing vector-store model/settings are reused automatically.
"$PYTHON_BIN" "$SCRIPT_DIR/embed_required_key_facts.py" \
  --kind queries --input "$INPUT_ROOT" --embedding-root "$EMBEDDING_ROOT" "$@" --device cuda:0
