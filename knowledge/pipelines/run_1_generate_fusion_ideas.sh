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
INPUT_ROOT="${INPUT_ROOT:-${SCRIPT_DIR}/outputs/0_select_fusion_domains}"
OUTPUT_ROOT="${OUTPUT_ROOT:-${SCRIPT_DIR}/outputs/1_generate_fusion_ideas}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Process all proposals; pass --overwrite explicitly to replace existing results.
# 1. Medical
"$PYTHON_BIN" "$SCRIPT_DIR/1_generate_fusion_ideas.py" \
  --input "$INPUT_ROOT/medical.jsonl" --output "$OUTPUT_ROOT/1_medical.jsonl" "$@"

# 2. Legal
"$PYTHON_BIN" "$SCRIPT_DIR/1_generate_fusion_ideas.py" \
  --input "$INPUT_ROOT/legal.jsonl" --output "$OUTPUT_ROOT/1_legal.jsonl" "$@"

# 3. Financial
"$PYTHON_BIN" "$SCRIPT_DIR/1_generate_fusion_ideas.py" \
  --input "$INPUT_ROOT/financial.jsonl" --output "$OUTPUT_ROOT/1_financial.jsonl" "$@"

# 4. Mathematics
"$PYTHON_BIN" "$SCRIPT_DIR/1_generate_fusion_ideas.py" \
  --input "$INPUT_ROOT/mathematics.jsonl" --output "$OUTPUT_ROOT/1_mathematics.jsonl" "$@"

# 5. Computer science
"$PYTHON_BIN" "$SCRIPT_DIR/1_generate_fusion_ideas.py" \
  --input "$INPUT_ROOT/computer_science.jsonl" --output "$OUTPUT_ROOT/1_computer_science.jsonl" "$@"

# 6. Geography
"$PYTHON_BIN" "$SCRIPT_DIR/1_generate_fusion_ideas.py" \
  --input "$INPUT_ROOT/geography.jsonl" --output "$OUTPUT_ROOT/1_geography.jsonl" "$@"

# 7. Chemistry
"$PYTHON_BIN" "$SCRIPT_DIR/1_generate_fusion_ideas.py" \
  --input "$INPUT_ROOT/chemistry.jsonl" --output "$OUTPUT_ROOT/1_chemistry.jsonl" "$@"
