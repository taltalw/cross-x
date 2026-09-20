#!/usr/bin/env bash
set -euo pipefail

# Configure these three values before running, or export them in your shell.
API_BASE_URL="${API_BASE_URL:-}"  # e.g. https://your-provider/v1
API_KEY="${API_KEY:-}"            # API key; use EMPTY for an unauthenticated local API
MODEL="${MODEL:-}"                # Model served by your API
ATOMIC_SPLIT="${ATOMIC_SPLIT:-test}"
NUM="${NUM:-10}"                  # Number of samples per domain
export API_BASE_URL API_KEY MODEL
: "${API_BASE_URL:?Please set API_BASE_URL}"
: "${API_KEY:?Please set API_KEY}"
: "${MODEL:?Please set MODEL}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_ROOT="${DATA_ROOT:-${SCRIPT_DIR}/../atomic}"
OUTPUT_ROOT="${OUTPUT_ROOT:-${SCRIPT_DIR}/outputs/0_extract_key_facts}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Existing results are protected. Pass --overwrite explicitly to rerun all jobs.
"$PYTHON_BIN" "$SCRIPT_DIR/0_extract_key_facts.py" "$@" \
  --input "$DATA_ROOT/medical/$ATOMIC_SPLIT.jsonl" --source-domain medical \
  --output "$OUTPUT_ROOT/medical/$ATOMIC_SPLIT.jsonl" --num "$NUM"

"$PYTHON_BIN" "$SCRIPT_DIR/0_extract_key_facts.py" "$@" \
  --input "$DATA_ROOT/legal/$ATOMIC_SPLIT.jsonl" --source-domain legal \
  --output "$OUTPUT_ROOT/legal/$ATOMIC_SPLIT.jsonl" --num "$NUM"

"$PYTHON_BIN" "$SCRIPT_DIR/0_extract_key_facts.py" "$@" \
  --input "$DATA_ROOT/financial/$ATOMIC_SPLIT.jsonl" --source-domain financial \
  --output "$OUTPUT_ROOT/financial/$ATOMIC_SPLIT.jsonl" --num "$NUM"

"$PYTHON_BIN" "$SCRIPT_DIR/0_extract_key_facts.py" "$@" \
  --input "$DATA_ROOT/mathematics/$ATOMIC_SPLIT.jsonl" --source-domain mathematics \
  --output "$OUTPUT_ROOT/mathematics/$ATOMIC_SPLIT.jsonl" --num "$NUM"

"$PYTHON_BIN" "$SCRIPT_DIR/0_extract_key_facts.py" "$@" \
  --input "$DATA_ROOT/computer_science/$ATOMIC_SPLIT.jsonl" --source-domain computer_science \
  --output "$OUTPUT_ROOT/computer_science/$ATOMIC_SPLIT.jsonl" --num "$NUM"

"$PYTHON_BIN" "$SCRIPT_DIR/0_extract_key_facts.py" "$@" \
  --input "$DATA_ROOT/geography/$ATOMIC_SPLIT.jsonl" --source-domain geography \
  --output "$OUTPUT_ROOT/geography/$ATOMIC_SPLIT.jsonl" --num "$NUM"

"$PYTHON_BIN" "$SCRIPT_DIR/0_extract_key_facts.py" "$@" \
  --input "$DATA_ROOT/chemistry/$ATOMIC_SPLIT.jsonl" --source-domain chemistry \
  --output "$OUTPUT_ROOT/chemistry/$ATOMIC_SPLIT.jsonl" --num "$NUM"
