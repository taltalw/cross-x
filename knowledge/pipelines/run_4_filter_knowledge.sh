#!/usr/bin/env bash
set -euo pipefail

# Filtering models for the two experiment groups.
API_BASE_URL_5_5="${API_BASE_URL_5_5:-}"
API_KEY_5_5="${API_KEY_5_5:-}"
MODEL_5_5="${MODEL_5_5:-}"
API_BASE_URL_6="${API_BASE_URL_6:-}"
API_KEY_6="${API_KEY_6:-}"
MODEL_6="${MODEL_6:-}"
for ARG in "$@"; do
  case "$ARG" in
    --api-base*|--api-key*|--model*)
      printf 'Configure the group-specific variables instead of %s\n' "${ARG%%=*}" >&2
      exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
KNOWLEDGE_ROOT="${KNOWLEDGE_ROOT:-${SCRIPT_DIR}/..}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
read -r -a RESULT_GROUPS <<< "${RESULT_GROUP_SELECTION:-results_5.5 results_6}"
# Validate only the selected groups before running either one.
for SELECTED_GROUP in "${RESULT_GROUPS[@]}"; do
  case "$SELECTED_GROUP" in
    results_5.5)
      : "${API_BASE_URL_5_5:?Please set API_BASE_URL_5_5}"
      : "${API_KEY_5_5:?Please set API_KEY_5_5}"
      : "${MODEL_5_5:?Please set MODEL_5_5}" ;;
    results_6)
      : "${API_BASE_URL_6:?Please set API_BASE_URL_6}"
      : "${API_KEY_6:?Please set API_KEY_6}"
      : "${MODEL_6:?Please set MODEL_6}" ;;
    *) printf 'Unknown result group: %s\n' "$SELECTED_GROUP" >&2; exit 1 ;;
  esac
done
shopt -s nullglob dotglob
for RESULT_GROUP in "${RESULT_GROUPS[@]}"; do
  case "$RESULT_GROUP" in
    results_5.5) API_BASE_URL="$API_BASE_URL_5_5"; API_KEY="$API_KEY_5_5"; MODEL="$MODEL_5_5" ;;
    results_6) API_BASE_URL="$API_BASE_URL_6"; API_KEY="$API_KEY_6"; MODEL="$MODEL_6" ;;
  esac
  INPUT_ROOT="$KNOWLEDGE_ROOT/$RESULT_GROUP/3_retrieve_knowledge"
  OUTPUT_ROOT="$KNOWLEDGE_ROOT/$RESULT_GROUP/4_filter_knowledge"
  INPUT_FILES=()
  for INPUT_FILE in "$INPUT_ROOT"/*.jsonl; do
    [[ -f "$INPUT_FILE" ]] && INPUT_FILES+=("$INPUT_FILE")
  done
  if (( ${#INPUT_FILES[@]} == 0 )); then
    printf 'No JSONL files found in: %s\n' "$INPUT_ROOT" >&2
    exit 1
  fi
  API_BASE_URL="$API_BASE_URL" API_KEY="$API_KEY" MODEL="$MODEL" \
    "$PYTHON_BIN" "$SCRIPT_DIR/4_filter_knowledge.py" "$@" \
    --cache "$KNOWLEDGE_ROOT/cache/filter/judgments.sqlite3" \
    --input "${INPUT_FILES[@]}" --output-root "$OUTPUT_ROOT"
done
