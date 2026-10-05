#!/usr/bin/env bash
# 调用者分别提供 J1/J2/J3_API_BASE_URL、*_API_KEY、*_MODEL，不在脚本中保存密钥。
set -euo pipefail
LLM5_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LLM5_PYTHON="${LLM5_PYTHON:-${PYTHON_BIN:-python3}}"
exec "${LLM5_PYTHON}" -u -X utf8 "${LLM5_DIR}/LLM5_batch.py" "$@"
