#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
V2_ROOT="${V2_ROOT:-${SCRIPT_DIR}/outputs}"
INPUT_ROOT="${INPUT_ROOT:-${V2_ROOT}/2_extract_required_key_facts}"
EMBEDDING_ROOT="${EMBEDDING_ROOT:-${SCRIPT_DIR}/../embeddings/Qwen3-Embedding-8B}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
# Existing vector-store model/settings are reused automatically.
"$PYTHON_BIN" "$SCRIPT_DIR/embed_required_key_facts.py" \
  --kind queries --input "$INPUT_ROOT" --embedding-root "$EMBEDDING_ROOT" "$@"
