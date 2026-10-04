#!/usr/bin/env bash
# Only step 4: read existing step-3 evidence and use isolated output/audit roots.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_config.sh"
v4_arguments "$@"
v4_api_config
v4_num_args
V4_CONCISE_ROOT="${V4_CONCISE_ROOT:-$SCRIPT_DIR/outputs_concise}"
V4_CONCISE_AUDIT_ROOT="${V4_CONCISE_AUDIT_ROOT:-$SCRIPT_DIR/outputs_concise_audit}"

# Check all group paths before the first model call, including canonical aliases.
inputs=() outputs=() audits=()
for count in "${V4_DOMAIN_COUNTS[@]}"; do
  for domain in "${V4_DOMAINS[@]}"; do
    input="$(v4_group_path 3_retrieve_key_fact_matches "$domain" "$count")"
    output="$V4_CONCISE_ROOT/4_generate_fusion_question/$domain/${V4_SPLIT}_domain_count_${count}.jsonl"
    audit="$V4_CONCISE_AUDIT_ROOT/4_generate_fusion_question/$domain/${V4_SPLIT}_domain_count_${count}.audit.jsonl"
    v4_input "$input"
    v4_output "$output"
    v4_output "$audit"
    inputs+=("$input") outputs+=("$output") audits+=("$audit")
  done
done
"$PYTHON_BIN" - "$SCRIPT_DIR" "$V4_ROOT" "$V4_CONCISE_ROOT" "$V4_CONCISE_AUDIT_ROOT" "${#inputs[@]}" "${inputs[@]}" "${outputs[@]}" "${audits[@]}" "${V4_WRITE_ARGS[@]}" <<'PY'
import importlib.util, os, sys
from pathlib import Path
root, n = Path(sys.argv[1]), int(sys.argv[5])
roots = [Path(p).resolve() for p in sys.argv[2:5]]
if len(set(roots)) != 3:
    raise SystemExit('Old input root, concise output root and audit root must be distinct')
sys.path.insert(0, str(root))
spec = importlib.util.spec_from_file_location('concise_step4', root/'4_generate_fusion_question.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
paths = [Path(p) for p in sys.argv[6:6+3*n]]
if len({p.resolve() for p in paths}) != len(paths):
    raise SystemExit('Batch input/output/audit paths must all be distinct')
for i, first in enumerate(paths):
    for second in paths[i+1:]:
        if first.exists() and second.exists() and os.path.samefile(first, second):
            raise SystemExit('Batch paths contain aliases of the same file')
for i in range(n):
    module.preflight_paths(paths[i], paths[n+i], paths[2*n+i], '--overwrite' in sys.argv[6+3*n:])
PY
for index in "${!inputs[@]}"; do
  "$PYTHON_BIN" "$SCRIPT_DIR/4_generate_fusion_question.py" \
    --input "${inputs[$index]}" --output "${outputs[$index]}" \
    --audit-output "${audits[$index]}" \
    --domain-count "${V4_DOMAIN_COUNTS[$((index / ${#V4_DOMAINS[@]}))]}" \
    --max-repairs "${MAX_REPAIRS:-1}" --seed "${SEED:-42}" \
    "${V4_NUM_ARGS[@]}" "${STEP_4_ARGS[@]}" "${V4_WRITE_ARGS[@]}"
done
