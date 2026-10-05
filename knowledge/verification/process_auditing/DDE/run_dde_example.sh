#!/usr/bin/env bash
set -euo pipefail

# 使用绝对路径定位输入，从任意工作目录调用均可。
AUDIT_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
"${PYTHON_BIN:-python3}" -X utf8 "${AUDIT_SCRIPT_DIR}/domain_distribution_entropy.py" \
  --input "${AUDIT_SCRIPT_DIR}/../../../pipielines_v4/outputs/1_generate_fusion_plans" \
  --output "${AUDIT_SCRIPT_DIR}/DDE_outputs/dde_v4" \
  "$@"
