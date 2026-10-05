#!/usr/bin/env bash
set -euo pipefail
LLM5_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LLM5_PYTHON="${LLM5_PYTHON:-python3}"
LLM5_ACTION="${1:-prepare}"
if [[ $# -gt 0 ]]; then shift; fi
case "${LLM5_ACTION}" in
  prepare)
    "${LLM5_PYTHON}" -X utf8 "${LLM5_DIR}/LLM5_run.py" --smoke-one \
      --output-dir "${LLM5_DIR}/LLM5_outputs/LLM5_preview" "$@" ;;
  smoke)
    "${LLM5_PYTHON}" -X utf8 "${LLM5_DIR}/LLM5_run.py" --smoke-one --execute \
      --output-dir "${LLM5_DIR}/LLM5_outputs/LLM5_smoke" "$@" ;;
  test)
    "${LLM5_PYTHON}" -X utf8 -m unittest discover -s "${LLM5_DIR}/LLM5_tests" -p 'LLM5_test*.py' -v "$@" ;;
  *) echo 'Usage: bash LLM5_run_example.sh [prepare|smoke|test] [arguments]'; exit 2 ;;
esac
