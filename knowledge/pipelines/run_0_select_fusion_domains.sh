#!/usr/bin/env bash
set -euo pipefail

# Configure these three values before running, or export them in your shell.
API_BASE_URL="${API_BASE_URL:-}"  # e.g. https://your-provider/v1
API_KEY="${API_KEY:-}"            # API key; use EMPTY for an unauthenticated local API
MODEL="${MODEL:-}"                # Model served by your API
DOMAIN_COUNTS=(2 3 4) # Total domains INCLUDING the source; run all three settings
export API_BASE_URL API_KEY MODEL
: "${API_BASE_URL:?Please set API_BASE_URL}"
: "${API_KEY:?Please set API_KEY}"
: "${MODEL:?Please set MODEL}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_ROOT="${DATA_ROOT:-${SCRIPT_DIR}/../atomic}"
OUTPUT_ROOT="${OUTPUT_ROOT:-${SCRIPT_DIR}/outputs/0_select_fusion_domains}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Existing results are protected. Pass --overwrite explicitly to rerun all 21 jobs.
for DOMAIN_COUNT in "${DOMAIN_COUNTS[@]}"; do
  # 1. 医学
  "$PYTHON_BIN" "$SCRIPT_DIR/0_select_fusion_domains.py" "$@" \
    --input "$DATA_ROOT/medical/test.jsonl" --source-domain medical \
    --output "$OUTPUT_ROOT/medical_domain_count_${DOMAIN_COUNT}.jsonl" --domain-count "$DOMAIN_COUNT" --num 10

  # 2. 法律
  "$PYTHON_BIN" "$SCRIPT_DIR/0_select_fusion_domains.py" "$@" \
    --input "$DATA_ROOT/legal/test.jsonl" --source-domain legal \
    --output "$OUTPUT_ROOT/legal_domain_count_${DOMAIN_COUNT}.jsonl" --domain-count "$DOMAIN_COUNT" --num 10

  # 3. 金融
  "$PYTHON_BIN" "$SCRIPT_DIR/0_select_fusion_domains.py" "$@" \
    --input "$DATA_ROOT/financial/test.jsonl" --source-domain financial \
    --output "$OUTPUT_ROOT/financial_domain_count_${DOMAIN_COUNT}.jsonl" --domain-count "$DOMAIN_COUNT" --num 10

  # 4. 数学
  "$PYTHON_BIN" "$SCRIPT_DIR/0_select_fusion_domains.py" "$@" \
    --input "$DATA_ROOT/mathematics/test.jsonl" --source-domain mathematics \
    --output "$OUTPUT_ROOT/mathematics_domain_count_${DOMAIN_COUNT}.jsonl" --domain-count "$DOMAIN_COUNT" --num 10

  # 5. 计算机科学
  "$PYTHON_BIN" "$SCRIPT_DIR/0_select_fusion_domains.py" "$@" \
    --input "$DATA_ROOT/computer_science/test.jsonl" --source-domain computer_science \
    --output "$OUTPUT_ROOT/computer_science_domain_count_${DOMAIN_COUNT}.jsonl" --domain-count "$DOMAIN_COUNT" --num 10

  # 6. 地理
  "$PYTHON_BIN" "$SCRIPT_DIR/0_select_fusion_domains.py" "$@" \
    --input "$DATA_ROOT/geography/test.jsonl" --source-domain geography \
    --output "$OUTPUT_ROOT/geography_domain_count_${DOMAIN_COUNT}.jsonl" --domain-count "$DOMAIN_COUNT" --num 10

  # 7. 化学
  "$PYTHON_BIN" "$SCRIPT_DIR/0_select_fusion_domains.py" "$@" \
    --input "$DATA_ROOT/chemistry/test.jsonl" --source-domain chemistry \
    --output "$OUTPUT_ROOT/chemistry_domain_count_${DOMAIN_COUNT}.jsonl" --domain-count "$DOMAIN_COUNT" --num 10
done
