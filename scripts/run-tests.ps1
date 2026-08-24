#!/usr/bin/env pwsh
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $projectRoot

& (Join-Path $PSScriptRoot 'run.ps1') python -m unittest discover -s (Join-Path $projectRoot 'tests') -p 'test_*.py'
exit $LASTEXITCODE
