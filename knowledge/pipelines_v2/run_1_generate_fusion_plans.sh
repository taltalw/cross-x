#!/usr/bin/env bash
set -euo pipefail

# Configure these values before running, or export them in your shell.
API_BASE_URL="${API_BASE_URL:-}"  # e.g. https://your-provider/v1
API_KEY="${API_KEY:-}"            # API key; use EMPTY for a local API
MODEL="${MODEL:-}"                # Model served by your API
SOURCE_DOMAIN="${SOURCE_DOMAIN:-geography}"
DOMAIN_COUNT="${DOMAIN_COUNT:-3}"
ATOMIC_SPLIT="${ATOMIC_SPLIT:-test}"
NUM="${NUM:-10}"
export API_BASE_URL API_KEY MODEL
: "${API_BASE_URL:?Please set API_BASE_URL}"
: "${API_KEY:?Please set API_KEY}"
: "${MODEL:?Please set MODEL}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
V2_ROOT="${V2_ROOT:-${SCRIPT_DIR}/outputs}"
INPUT_ROOT="${INPUT_ROOT:-${V2_ROOT}/0_extract_key_facts}"
OUTPUT_ROOT="${OUTPUT_ROOT:-${V2_ROOT}/1_generate_fusion_plans}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PYTHON_BIN" "$SCRIPT_DIR/1_generate_fusion_plans.py" \
  --input "$INPUT_ROOT/$SOURCE_DOMAIN/$ATOMIC_SPLIT.jsonl" \
  --output "$OUTPUT_ROOT/$SOURCE_DOMAIN/${ATOMIC_SPLIT}_domain_count_${DOMAIN_COUNT}.jsonl" \
  --domain-count "$DOMAIN_COUNT" --num "$NUM" "$@"
