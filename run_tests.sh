#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v pytest &>/dev/null; then
    echo "pytest not found — install with: pip install pytest" >&2
    exit 1
fi

pytest "$@"
