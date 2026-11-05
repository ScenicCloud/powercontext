#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python -m sdd_context init --reset
python -m sdd_context demo
