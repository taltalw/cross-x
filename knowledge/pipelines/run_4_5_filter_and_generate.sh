#!/usr/bin/env bash
set -euo pipefail

# Configure once here; run steps 4 and 5 for results_5.5 only.
API_BASE_URL_5_5="${API_BASE_URL_5_5:-}"
API_KEY_5_5="${API_KEY_5_5:-}"
MODEL_5_5="${MODEL_5_5:-}"
export API_BASE_URL_5_5 API_KEY_5_5 MODEL_5_5
: "${API_BASE_URL_5_5:?Please set API_BASE_URL_5_5}"
: "${API_KEY_5_5:?Please set API_KEY_5_5}"
: "${MODEL_5_5:?Please set MODEL_5_5}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
KNOWLEDGE_ROOT="${KNOWLEDGE_ROOT:-${SCRIPT_DIR}/..}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
RESULT_GROUP_SELECTION="results_5.5"
export KNOWLEDGE_ROOT PYTHON_BIN RESULT_GROUP_SELECTION

# Optional step-specific arguments, for example:
# FILTER_ARGS=(--batch-size 5 --max-materials 3)
# GENERATE_ARGS=(--max-tokens 8192)
FILTER_ARGS=()
GENERATE_ARGS=()
# Command-line arguments such as --overwrite are forwarded to BOTH steps.

printf '[4/5] Filtering knowledge for results_5.5...\n'
bash "$SCRIPT_DIR/run_4_filter_knowledge.sh" "$@" "${FILTER_ARGS[@]}"

# set -e prevents generation if filtering fails.
printf '[5/5] Generating fusion samples for results_5.5...\n'
bash "$SCRIPT_DIR/run_5_generate_fusion_samples.sh" "$@" "${GENERATE_ARGS[@]}"

printf 'Knowledge filtering and fusion sample generation completed.\n'
