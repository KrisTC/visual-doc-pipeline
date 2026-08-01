#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${project_root}/.venv/bin/python" -m unittest discover \
    -s "${project_root}/tests" \
    -p 'test_*.py'
