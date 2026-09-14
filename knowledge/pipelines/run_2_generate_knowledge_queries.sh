#!/usr/bin/env bash
set -euo pipefail

# gpt_5.5: set values here or export these variables before running.
API_BASE_URL_5_5="${API_BASE_URL_5_5:-}"
API_KEY_5_5="${API_KEY_5_5:-}"
MODEL_5_5="${MODEL_5_5:-}"
# gpt_6: independent endpoint, credentials, and model.
API_BASE_URL_6="${API_BASE_URL_6:-}"
API_KEY_6="${API_KEY_6:-}"
MODEL_6="${MODEL_6:-}"

: "${API_BASE_URL_5_5:?Please set API_BASE_URL_5_5}"
: "${API_KEY_5_5:?Please set API_KEY_5_5}"
: "${MODEL_5_5:?Please set MODEL_5_5}"
: "${API_BASE_URL_6:?Please set API_BASE_URL_6}"
: "${API_KEY_6:?Please set API_KEY_6}"
: "${MODEL_6:?Please set MODEL_6}"

# Reject shared overrides that would bypass the group-specific configuration.
for ARG in "$@"; do
  case "$ARG" in
    --api-base-url*|--api-key*|--model*)
      printf 'Use the group-specific API/model variables instead of %s\n' "${ARG%%=*}" >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
KNOWLEDGE_ROOT="${KNOWLEDGE_ROOT:-${SCRIPT_DIR}/..}"
RESULT_GROUPS=(results_5.5 results_6)
PYTHON_BIN="${PYTHON_BIN:-python3}"
shopt -s nullglob dotglob
for RESULT_GROUP in "${RESULT_GROUPS[@]}"; do
  case "$RESULT_GROUP" in
    results_5.5)
      API_BASE_URL="$API_BASE_URL_5_5"
      API_KEY="$API_KEY_5_5"
      MODEL="$MODEL_5_5"
      ;;
    results_6)
      API_BASE_URL="$API_BASE_URL_6"
      API_KEY="$API_KEY_6"
      MODEL="$MODEL_6"
      ;;
  esac
  INPUT_ROOT="$KNOWLEDGE_ROOT/$RESULT_GROUP/1_generate_fusion_ideas"
  OUTPUT_ROOT="$KNOWLEDGE_ROOT/$RESULT_GROUP/2_generate_knowledge_queries"
  [[ -d "$INPUT_ROOT" ]] || { printf 'Input directory does not exist: %s\n' "$INPUT_ROOT" >&2; exit 1; }
  INPUT_FILES=("$INPUT_ROOT"/*.jsonl)
  PROCESSED_FILES=0
  for INPUT_FILE in "${INPUT_FILES[@]}"; do
    [[ -f "$INPUT_FILE" ]] || continue
    NAME="${INPUT_FILE##*/}"
    API_BASE_URL="$API_BASE_URL" API_KEY="$API_KEY" MODEL="$MODEL" \
      "$PYTHON_BIN" "$SCRIPT_DIR/2_generate_knowledge_queries.py" "$@" \
      --input "$INPUT_FILE" --output "$OUTPUT_ROOT/2_${NAME}"
    PROCESSED_FILES=$((PROCESSED_FILES + 1))
  done
  if (( PROCESSED_FILES == 0 )); then
    printf 'No JSONL files found in: %s\n' "$INPUT_ROOT" >&2
    exit 1
  fi
done
