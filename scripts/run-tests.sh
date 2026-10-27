#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${project_root}"
exec "${project_root}/run.sh" "${project_root}/scripts/run_tests.py" "$@"
