#!/usr/bin/env pwsh
param()

$ErrorActionPreference = 'Stop'
$PSNativeCommandArgumentPassing = 'Standard'

$projectRoot = (Resolve-Path $PSScriptRoot).Path
Set-Location $projectRoot
$managedPathMarker = '# Managed by scripts/configure-paddle-cuda-environment.ps1'

function Set-ManagedDotenvPath {
    param([string]$DotenvFile)

    $lines = [System.IO.File]::ReadAllLines($DotenvFile)
    for ($index = 0; $index -lt $lines.Length - 1; $index += 1) {
        if ($lines[$index] -ne $managedPathMarker -or -not $lines[$index + 1].StartsWith('PATH=')) {
            continue
        }

        $pathValue = $lines[$index + 1].Substring(5)
        if ($pathValue.Length -ge 2 -and $pathValue.StartsWith('"') -and $pathValue.EndsWith('"')) {
            $pathValue = $pathValue.Substring(1, $pathValue.Length - 2)
        }
        if ($pathValue.Contains('${PATH}')) {
            $env:PATH = $pathValue.Replace('${PATH}', $env:PATH)
        }
        return
    }
}

$remainingArguments = [System.Collections.Generic.List[string]]::new()
foreach ($argument in $args) {
    $remainingArguments.Add([string]$argument)
}

$envFile = $null
if ($remainingArguments.Count -gt 0 -and $remainingArguments[0] -in @('-EnvFile', '--env-file')) {
    if ($remainingArguments.Count -lt 2) {
        Write-Error 'run.ps1: -EnvFile requires a path.'
        exit 2
    }
    $envFile = $remainingArguments[1]
    $remainingArguments.RemoveRange(0, 2)
    if ($remainingArguments.Count -gt 0 -and $remainingArguments[0] -eq '--') {
        $remainingArguments.RemoveAt(0)
    }
}

if ($remainingArguments.Count -eq 0) {
    Write-Error 'Usage: .\\run.ps1 [-EnvFile PATH] PYTHON_ARGUMENT [PYTHON_ARGUMENT ...]'
    exit 2
}

$selectedEnvFile = $null
if ($null -ne $envFile) {
    $selectedEnvFile = (Resolve-Path -LiteralPath $envFile -ErrorAction Stop).Path
} else {
    $defaultEnvFile = Join-Path $projectRoot '.env.local'
    if (Test-Path -LiteralPath $defaultEnvFile -PathType Leaf) {
        $selectedEnvFile = $defaultEnvFile
    }
}

$uvArguments = @('run')
if ($null -ne $selectedEnvFile) {
    Set-ManagedDotenvPath $selectedEnvFile
    $uvEnvironmentFile = $selectedEnvFile -replace '\\', '/'
    $uvArguments += "--env-file=$uvEnvironmentFile"
}
$uvArguments += 'python'
$uvArguments += $remainingArguments

& uv @uvArguments
exit $LASTEXITCODE
