#!/usr/bin/env bash
set -euo pipefail
uv sync --locked --group dev --python 3.12
uv run python -c 'import nmr_companion, numpy, scipy, nmrglue'
