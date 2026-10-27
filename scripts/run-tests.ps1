#!/usr/bin/env pwsh
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $projectRoot

& (Join-Path $projectRoot 'run.ps1') (Join-Path $projectRoot 'scripts\run_tests.py') @args
exit $LASTEXITCODE
