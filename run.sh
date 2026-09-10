#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
env_file=""
dependency_profile="${VISUAL_DOC_PIPELINE_UV_EXTRA:-gpu}"

if [[ "${dependency_profile}" != "cpu" && "${dependency_profile}" != "gpu" ]]; then
    printf '%s\n' 'run.sh: VISUAL_DOC_PIPELINE_UV_EXTRA must be cpu or gpu.' >&2
    exit 2
fi

if [[ "${1:-}" == "--env-file" ]]; then
    if [[ $# -lt 2 ]]; then
        printf '%s\n' 'run.sh: --env-file requires a path.' >&2
        exit 2
    fi
    env_file="$2"
    shift 2
    if [[ "${1:-}" == "--" ]]; then
        shift
    fi
elif [[ -f "${project_root}/.env.local" ]]; then
    env_file="${project_root}/.env.local"
fi

if [[ $# -eq 0 ]]; then
    printf '%s\n' 'Usage: ./run.sh [--env-file PATH --] PYTHON_ARGUMENT [PYTHON_ARGUMENT ...]' >&2
    exit 2
fi

cd "${project_root}"
if [[ -n "${env_file}" ]]; then
    exec uv run --exact --extra "${dependency_profile}" --env-file "${env_file}" python "$@"
fi
exec uv run --exact --extra "${dependency_profile}" python "$@"
