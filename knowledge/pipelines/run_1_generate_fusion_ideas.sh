#!/usr/bin/env bash
set -euo pipefail

# Set these values here or export them before running.
API_BASE_URL="${API_BASE_URL:-}"  # e.g. https://your-provider/v1
API_KEY="${API_KEY:-}"            # Use EMPTY for an unauthenticated local API
MODEL="${MODEL:-}"
export API_BASE_URL API_KEY MODEL
: "${API_BASE_URL:?Please set API_BASE_URL}"
: "${API_KEY:?Please set API_KEY}"
: "${MODEL:?Please set MODEL}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INPUT_ROOT="${INPUT_ROOT:-${SCRIPT_DIR}/../results/0_select_fusion_domains}"
OUTPUT_ROOT="${OUTPUT_ROOT:-${SCRIPT_DIR}/outputs/1_generate_fusion_ideas}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Process each JSONL file; pass --overwrite explicitly to replace existing results.
if [[ ! -d "$INPUT_ROOT" ]]; then
  printf 'Input directory does not exist: %s\n' "$INPUT_ROOT" >&2
  exit 1
fi

shopt -s nullglob dotglob
INPUT_FILES=("$INPUT_ROOT"/*.jsonl)
PROCESSED_FILES=0
for INPUT_FILE in "${INPUT_FILES[@]}"; do
  [[ -f "$INPUT_FILE" ]] || continue
  INPUT_NAME="${INPUT_FILE##*/}"
  "$PYTHON_BIN" "$SCRIPT_DIR/1_generate_fusion_ideas.py" "$@" \
    --input "$INPUT_FILE" --output "$OUTPUT_ROOT/1_${INPUT_NAME}"
  PROCESSED_FILES=$((PROCESSED_FILES + 1))
done

if (( PROCESSED_FILES == 0 )); then
  printf 'No JSONL files found in: %s\n' "$INPUT_ROOT" >&2
  exit 1
fi
