#!/usr/bin/env bash
# Shared configuration for run_0.sh through run_4.sh and run_all.sh.
V4_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
V4_ROOT="${V4_ROOT:-${V4_SCRIPT_DIR}/outputs}"
ATOMIC_ROOT="${ATOMIC_ROOT:-${V4_SCRIPT_DIR}/../atomic}"
if [[ -z ${PYTHON_BIN:-} ]]; then
  if [[ -x "$V4_SCRIPT_DIR/.env/bin/python" ]]; then
    PYTHON_BIN="$V4_SCRIPT_DIR/.env/bin/python"
  elif [[ -x /mnt/data1/wangyatong/anaconda3/envs/crossx/bin/python ]]; then
    PYTHON_BIN=/mnt/data1/wangyatong/anaconda3/envs/crossx/bin/python
  else
    PYTHON_BIN=python3
  fi
fi
EMBEDDING_PYTHON_BIN="${EMBEDDING_PYTHON_BIN:-$PYTHON_BIN}"
API_BASE_URL="${API_BASE_URL:-}"
API_KEY="${API_KEY:-}"
MODEL="${MODEL:-}"
export API_BASE_URL API_KEY MODEL

V4_SPLIT=test
V4_DOMAINS=(medical legal financial mathematics computer_science geography chemistry)
V4_DOMAIN_COUNTS=(2 3 4)  # Includes the source domain.
NUM="${NUM:-100}"          # Step 1 source samples per group; use all for the entire file.

EMBEDDING_ROOT="${EMBEDDING_ROOT:-${V4_SCRIPT_DIR}/../embeddings/v4-test-Qwen3-Embedding-8B}"
EMBEDDING_MODEL="${EMBEDDING_MODEL:-Qwen/Qwen3-Embedding-8B}"
GPU_ID="${GPU_ID:-0}"
EMBEDDING_DEVICE="${EMBEDDING_DEVICE:-auto}"
EMBEDDING_DTYPE="${EMBEDDING_DTYPE:-auto}"
EMBEDDING_BATCH_SIZE="${EMBEDDING_BATCH_SIZE:-8}"
TOP_K="${TOP_K:-10}"
CANDIDATE_LIMIT="${CANDIDATE_LIMIT:-10}"

# Optional stage-specific flags. Input/output/domain settings belong to the scripts.
STEP_0_ARGS=()
STEP_1_ARGS=()
STEP_2_ARGS=()
EMBEDDING_ARGS=()
RETRIEVAL_ARGS=()
STEP_4_ARGS=()

v4_arguments() {
  V4_WRITE_ARGS=()
  for arg in "$@"; do
    case "$arg" in
      --overwrite) V4_WRITE_ARGS=(--overwrite) ;;
      *) printf 'Unknown argument: %s; use --overwrite or edit run_config.sh.\n' "$arg" >&2; return 2 ;;
    esac
  done
}

v4_api_config() {
  : "${API_BASE_URL:?Please configure API_BASE_URL in run_config.sh or your environment}"
  : "${API_KEY:?Please configure API_KEY in run_config.sh or your environment}"
  : "${MODEL:?Please configure MODEL in run_config.sh or your environment}"
}

v4_num_args() {
  V4_NUM_ARGS=()
  if [[ "$NUM" != all ]]; then
    [[ "$NUM" =~ ^[1-9][0-9]*$ ]] || { printf 'NUM must be a positive integer or all.\n' >&2; return 2; }
    V4_NUM_ARGS=(--num "$NUM")
  fi
}

v4_input() {
  [[ -f "$1" ]] || { printf 'Missing input: %s\n' "$1" >&2; return 1; }
}

v4_output() {
  if [[ -e "$1" && ${#V4_WRITE_ARGS[@]} -eq 0 ]]; then
    printf 'Output exists: %s; pass --overwrite to restart this group of stages.\n' "$1" >&2
    return 1
  fi
}

v4_group_path() {
  printf '%s/%s/%s/%s_domain_count_%s.jsonl' "$V4_ROOT" "$1" "$2" "$V4_SPLIT" "$3"
}
