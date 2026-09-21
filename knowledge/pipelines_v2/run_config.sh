#!/usr/bin/env bash
# Shared configuration for run_012.sh, run_embedding_retrieve.sh, and run_4.sh.
# Edit these values here, or set the corresponding environment variables.
V2_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
V2_ROOT="${V2_ROOT:-${V2_SCRIPT_DIR}/outputs}"
ATOMIC_ROOT="${ATOMIC_ROOT:-${V2_SCRIPT_DIR}/../atomic}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
EMBEDDING_PYTHON_BIN="${EMBEDDING_PYTHON_BIN:-${PYTHON_BIN}}"
API_BASE_URL="${API_BASE_URL:-}"
API_KEY="${API_KEY:-}"
MODEL="${MODEL:-}"
export API_BASE_URL API_KEY MODEL

# The unified workflow annotates and retrieves the complete test corpora.
V2_SPLIT=test
V2_DOMAINS=(medical legal financial mathematics computer_science geography chemistry)
V2_DOMAIN_COUNTS=(2 3 4)  # Total domains INCLUDING the source, not proposal counts.
NUM="${NUM:-10}"        # Step 1 source samples per group; use all for the entire file.

# Separate from the original train vector store. Corpus and queries use this same store.
EMBEDDING_ROOT="${EMBEDDING_ROOT:-${V2_SCRIPT_DIR}/../embeddings/v2-test-Qwen3-Embedding-8B}"
EMBEDDING_MODEL="${EMBEDDING_MODEL:-Qwen/Qwen3-Embedding-8B}"
EMBEDDING_DEVICE="${EMBEDDING_DEVICE:-auto}"
EMBEDDING_DTYPE="${EMBEDDING_DTYPE:-auto}"
EMBEDDING_BATCH_SIZE="${EMBEDDING_BATCH_SIZE:-8}"
TOP_K="${TOP_K:-10}"
CANDIDATE_LIMIT="${CANDIDATE_LIMIT:-20}"

# Optional stage-specific flags. Do not override input/output/domain/split settings here.
STEP_0_ARGS=()             # e.g. (--max-tokens 4096 --timeout 180)
STEP_1_ARGS=()
STEP_2_ARGS=()
EMBEDDING_ARGS=()          # e.g. (--local-files-only)
RETRIEVAL_ARGS=()
STEP_4_ARGS=()

v2_arguments() {
  V2_WRITE_ARGS=()
  for arg in "$@"; do
    case "$arg" in
      --overwrite) V2_WRITE_ARGS=(--overwrite) ;;
      *) printf 'Unknown argument: %s; use --overwrite or edit run_config.sh.\n' "$arg" >&2; return 2 ;;
    esac
  done
}

v2_api_config() {
  : "${API_BASE_URL:?Please configure API_BASE_URL in run_config.sh or your environment}"
  : "${API_KEY:?Please configure API_KEY in run_config.sh or your environment}"
  : "${MODEL:?Please configure MODEL in run_config.sh or your environment}"
}

v2_input() {
  [[ -f "$1" ]] || { printf 'Missing input: %s\n' "$1" >&2; return 1; }
}

v2_output() {
  if [[ -e "$1" && ${#V2_WRITE_ARGS[@]} -eq 0 ]]; then
    printf 'Output exists: %s; pass --overwrite to restart this group of stages.\n' "$1" >&2
    return 1
  fi
}

v2_group_path() {
  # stage directory, source domain, total domain count
  printf '%s/%s/%s/%s_domain_count_%s.jsonl' "$V2_ROOT" "$1" "$2" "$V2_SPLIT" "$3"
}
