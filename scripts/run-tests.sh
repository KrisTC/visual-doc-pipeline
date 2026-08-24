#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${project_root}"
exec "${project_root}/scripts/run.sh" python -m unittest discover \
    -s "${project_root}/tests" \
    -p 'test_*.py'
