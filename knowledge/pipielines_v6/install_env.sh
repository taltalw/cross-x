#!/usr/bin/env bash
# Install the v5 runtime into a local conda prefix without changing crossx.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="$SCRIPT_DIR/.env"

if command -v conda >/dev/null 2>&1; then
  CONDA_BIN="$(command -v conda)"
elif [[ -x /mnt/data1/wangyatong/anaconda3/bin/conda ]]; then
  CONDA_BIN=/mnt/data1/wangyatong/anaconda3/bin/conda
else
  printf 'Conda is required to install the crossx environment.\n' >&2
  exit 1
fi

if [[ ! -x "$ENV_DIR/bin/python" ]]; then
  "$CONDA_BIN" create --yes --prefix "$ENV_DIR" python=3.10 pip
fi
"$CONDA_BIN" run --prefix "$ENV_DIR" python -m pip install \
  --disable-pip-version-check -r "$SCRIPT_DIR/requirements-crossx.txt"
"$ENV_DIR/bin/python" -c 'import numpy, torch, transformers, safetensors, packaging; print("crossx v5 runtime ready")'
