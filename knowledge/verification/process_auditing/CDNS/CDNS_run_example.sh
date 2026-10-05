#!/usr/bin/env bash
# 默认只准备 21 个 easy 样本；infer 仍需 --execute 才会联网。
set -euo pipefail
CDNS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CDNS_PYTHON="${CDNS_PYTHON:-python3}"
CDNS_ACTION="${1:-prepare}"
if [[ $# -gt 0 ]]; then shift; fi
case "${CDNS_ACTION}" in
  prepare)
    "${CDNS_PYTHON}" -X utf8 "${CDNS_DIR}/CDNS_prepare.py" \
      --difficulty easy --per-group 1 \
      --output-dir "${CDNS_DIR}/CDNS_outputs/CDNS_example" "$@"
    ;;
  dry-run|infer)
    "${CDNS_PYTHON}" -X utf8 "${CDNS_DIR}/CDNS_infer.py" \
      --input-dir "${CDNS_DIR}/CDNS_outputs/CDNS_example" "$@"
    ;;
  score)
    "${CDNS_PYTHON}" -X utf8 "${CDNS_DIR}/CDNS_score.py" \
      --input-dir "${CDNS_DIR}/CDNS_outputs/CDNS_example" \
      --predictions-file "${CDNS_DIR}/CDNS_outputs/CDNS_predictions.jsonl" \
      --output-dir "${CDNS_DIR}/CDNS_outputs/CDNS_scores" "$@"
    ;;
  validate)
    "${CDNS_PYTHON}" -X utf8 "${CDNS_DIR}/CDNS_validate.py" \
      --output-dir "${CDNS_DIR}/CDNS_outputs/CDNS_validation" "$@"
    ;;
  test)
    "${CDNS_PYTHON}" -X utf8 -m unittest discover \
      -s "${CDNS_DIR}/CDNS_tests" -p 'CDNS_test*.py' -v "$@"
    ;;
  *)
    echo '用法：bash CDNS_run_example.sh [prepare|dry-run|infer|score|validate|test] [参数]'
    exit 2
    ;;
esac
