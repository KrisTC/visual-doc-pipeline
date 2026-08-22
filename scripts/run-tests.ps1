#!/usr/bin/env pwsh
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $projectRoot

uv run python -m unittest discover -s (Join-Path $projectRoot 'tests') -p 'test_*.py'
exit $LASTEXITCODE
