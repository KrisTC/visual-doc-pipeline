#!/usr/bin/env pwsh
[CmdletBinding()]
param(
    [Parameter()]
    [string]$CudaRoot,
    [Parameter()]
    [string]$CudnnBinDirectory
)

$ErrorActionPreference = 'Stop'

$cudaMajorVersion = 12
$cudnnMajorVersion = 9
$requiredCudaDlls = @('cudart64_12.dll')
$requiredCudnnDlls = @('cudnn64_9.dll')
$managedPathMarker = '# Managed by scripts/configure-paddle-cuda-environment.ps1'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$envFile = Join-Path $projectRoot '.env.local'
$runScript = Join-Path $PSScriptRoot 'run.ps1'

function Get-ExistingDirectory {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) {
        return $null
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Get-UniquePaths {
    param([string[]]$Candidates)

    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($candidate in $Candidates) {
        $existingDirectory = Get-ExistingDirectory $candidate
        if ($null -ne $existingDirectory -and $seen.Add($existingDirectory)) {
            $existingDirectory
        }
    }
}

function Test-RequiredDlls {
    param(
        [string]$Directory,
        [string[]]$RequiredDlls
    )

    foreach ($dll in $RequiredDlls) {
        if (-not (Test-Path -LiteralPath (Join-Path $Directory $dll) -PathType Leaf)) {
            return $false
        }
    }
    return $true
}

function Get-VersionFromDirectoryName {
    param(
        [string]$Name,
        [int]$MajorVersion,
        [bool]$HasVersionPrefix
    )

    $prefix = if ($HasVersionPrefix) { 'v' } else { '' }
    $match = [regex]::Match($Name, "^$prefix$MajorVersion\.(\d+)(?:\.(\d+))?$")
    if (-not $match.Success) {
        return $null
    }
    $minorVersion = [int]$match.Groups[1].Value
    $patchVersion = if ($match.Groups[2].Success) { [int]$match.Groups[2].Value } else { 0 }
    return [version]::new($MajorVersion, $minorVersion, $patchVersion)
}

function Get-CudaRootCandidates {
    param([string]$RequestedCudaRoot)

    $candidates = [System.Collections.Generic.List[string]]::new()
    foreach ($candidate in @($RequestedCudaRoot, $env:CUDA_PATH)) {
        if (-not [string]::IsNullOrWhiteSpace($candidate)) {
            $candidates.Add($candidate)
        }
    }
    foreach ($cudaPathVariable in Get-ChildItem Env: | Where-Object { $_.Name -match '^CUDA_PATH_V12_' }) {
        $candidates.Add($cudaPathVariable.Value)
    }

    $standardCudaRoot = 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA'
    if (Test-Path -LiteralPath $standardCudaRoot -PathType Container) {
        foreach ($versionDirectory in Get-ChildItem -LiteralPath $standardCudaRoot -Directory -Filter 'v12.*') {
            $candidates.Add($versionDirectory.FullName)
        }
    }

    foreach ($candidate in Get-UniquePaths $candidates.ToArray()) {
        $version = Get-VersionFromDirectoryName (Split-Path -Leaf $candidate) $cudaMajorVersion $true
        if ($null -ne $version) {
            [pscustomobject]@{
                Directory = $candidate
                Version = $version
            }
        }
    }
}

function Resolve-CudaBinDirectory {
    param([string]$RequestedCudaRoot)

    foreach ($candidate in Get-CudaRootCandidates $RequestedCudaRoot | Sort-Object -Property Version -Descending) {
        $binDirectory = Get-ExistingDirectory (Join-Path $candidate.Directory 'bin')
        if ($null -ne $binDirectory -and (Test-RequiredDlls $binDirectory $requiredCudaDlls)) {
            return $binDirectory
        }
    }

    throw "CUDA Toolkit 12.x with $($requiredCudaDlls -join ', ') was not found. Install a CUDA 12.x Toolkit or set CUDA_PATH_V12_<minor>."
}

function Get-CudnnCandidates {
    param(
        [string]$RequestedCudnnBinDirectory
    )

    $roots = [System.Collections.Generic.List[string]]::new()
    foreach ($candidate in @($RequestedCudnnBinDirectory, $env:CUDNN_PATH, $env:CUDNN_PATH_V9, 'C:\Program Files\NVIDIA\CUDNN')) {
        if (-not [string]::IsNullOrWhiteSpace($candidate)) {
            $roots.Add($candidate)
        }
    }

    $candidates = [System.Collections.Generic.List[object]]::new()
    foreach ($root in Get-UniquePaths $roots.ToArray()) {
        foreach ($candidate in Get-ChildItem -LiteralPath $root -Directory -Recurse -Depth 4 -ErrorAction SilentlyContinue) {
            if ($candidate.Name -ne 'x64' -or -not (Test-RequiredDlls $candidate.FullName $requiredCudnnDlls)) {
                continue
            }
            $runtimeVersion = Get-VersionFromDirectoryName (Split-Path -Leaf (Split-Path -Parent $candidate.FullName)) $cudaMajorVersion $false
            $cudnnVersionDirectory = Split-Path -Leaf (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $candidate.FullName)))
            $cudnnVersion = Get-VersionFromDirectoryName $cudnnVersionDirectory $cudnnMajorVersion $true
            if ($null -ne $runtimeVersion -and $null -ne $cudnnVersion) {
                $candidates.Add([pscustomobject]@{
                    Directory = $candidate.FullName
                    CudnnVersion = $cudnnVersion
                    RuntimeVersion = $runtimeVersion
                })
            }
        }
    }

    return $candidates | Sort-Object -Property CudnnVersion, RuntimeVersion -Descending
}

function Resolve-CudnnBinDirectory {
    param([string]$RequestedCudnnBinDirectory)

    foreach ($candidate in Get-CudnnCandidates $RequestedCudnnBinDirectory) {
        return $candidate.Directory
    }

    throw "cuDNN 9.x Windows x64 runtime with $($requiredCudnnDlls -join ', ') was not found. Install cuDNN 9.x for CUDA 12.x or set CUDNN_PATH."
}

function Get-ManagedEnvironmentContent {
    param(
        [string]$ExistingContent,
        [string]$PathValue
    )

    $pathMatches = [regex]::Matches($ExistingContent, '(?im)^PATH=[^\r\n]*')
    $markerPattern = '(?m)^' + [regex]::Escape($managedPathMarker) + '\r?$'
    $markerMatches = [regex]::Matches($ExistingContent, $markerPattern)
    if ($pathMatches.Count -gt 1 -or $markerMatches.Count -gt 1) {
        throw 'The .env.local file has duplicate managed PATH entries. Remove the duplicates before rerunning setup.'
    }

    $newLine = if ($ExistingContent.Contains("`r`n")) { "`r`n" } else { "`n" }
        $managedBlock = "${managedPathMarker}${newLine}PATH=$PathValue"

        if ($markerMatches.Count -eq 0) {
            if ($pathMatches.Count -ne 0) {
                throw 'The .env.local PATH entry is not managed by this script. Rename or remove it before rerunning setup.'
            }
            if ([string]::IsNullOrEmpty($ExistingContent)) {
                return "$managedBlock$newLine"
            }
            $separator = if ($ExistingContent.EndsWith("`n") -or $ExistingContent.EndsWith("`r")) { '' } else { $newLine }
            return "${ExistingContent}${separator}${managedBlock}${newLine}"
        }

        if ($pathMatches.Count -ne 1) {
            throw 'The managed .env.local PATH entry is malformed. Restore the managed marker and PATH line before rerunning setup.'
        }
        $managedBlockPattern = '(?m)^' + [regex]::Escape($managedPathMarker) + '\r?\nPATH=[^\r\n]*'
        if (-not [regex]::IsMatch($ExistingContent, $managedBlockPattern)) {
            throw 'The managed .env.local PATH entry is malformed. Restore the managed marker and PATH line before rerunning setup.'
        }
        return [regex]::Replace($ExistingContent, $managedBlockPattern, $managedBlock, 1)
    }

    function Invoke-PaddleProbe {
        param([string]$CandidateEnvFile)

        $probeCode = @(
            'import json',
            'import paddle',
            '',
            'compiled_with_cuda = paddle.is_compiled_with_cuda()',
            'device_count = paddle.device.cuda.device_count() if compiled_with_cuda else 0',
            'print("PADDLE_GPU_PROBE=" + json.dumps({',
            '    "compiled_with_cuda": compiled_with_cuda,',
            '    "device_count": device_count,',
            '}))'
        ) -join "`n"

        $probeOutput = @(& $runScript -EnvFile $CandidateEnvFile python -c $probeCode 2>&1)
        $probeText = ($probeOutput | ForEach-Object { $_.ToString() }) -join "`n"
        if ($LASTEXITCODE -ne 0) {
            throw "PaddlePaddle CUDA loading failed in the generated environment. Check the NVIDIA driver and required runtime DLLs. Paddle output: $probeText"
        }

        $probeMatches = [regex]::Matches($probeText, '(?m)^PADDLE_GPU_PROBE=(.+)$')
        if ($probeMatches.Count -ne 1) {
            throw 'PaddlePaddle CUDA probe did not return a valid result.'
        }
        try {
            $probe = $probeMatches[0].Groups[1].Value | ConvertFrom-Json
        } catch {
            throw 'PaddlePaddle CUDA probe returned invalid data.'
        }
        if (-not $probe.compiled_with_cuda) {
            throw 'The installed PaddlePaddle distribution does not report CUDA compilation support.'
        }
        if ([int]$probe.device_count -lt 1) {
            throw 'PaddlePaddle cannot detect an available CUDA device. Check the NVIDIA driver and GPU visibility.'
        }
        return [int]$probe.device_count
    }

    try {
        if (-not (Test-Path -LiteralPath $runScript -PathType Leaf)) {
            throw 'The required scripts/run.ps1 wrapper was not found.'
        }

        $cudaBinDirectory = Resolve-CudaBinDirectory $CudaRoot
        $cudnnBinDirectory = Resolve-CudnnBinDirectory $CudnnBinDirectory
        $cudaPathForDotenv = $cudaBinDirectory -replace '\\', '/'
        $cudnnPathForDotenv = $cudnnBinDirectory -replace '\\', '/'
        $pathValue = '"{0};{1};${{PATH}}"' -f $cudaPathForDotenv, $cudnnPathForDotenv
        $existingContent = if (Test-Path -LiteralPath $envFile -PathType Leaf) {
            [System.IO.File]::ReadAllText($envFile)
        } else {
            ''
        }
        $candidateContent = Get-ManagedEnvironmentContent $existingContent $pathValue
        $candidateEnvFile = Join-Path $projectRoot ('.env.local.{0}.tmp' -f [guid]::NewGuid().ToString('N'))

        try {
            $utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
            [System.IO.File]::WriteAllText($candidateEnvFile, $candidateContent, $utf8WithoutBom)
            $deviceCount = Invoke-PaddleProbe $candidateEnvFile
            [System.IO.File]::Move($candidateEnvFile, $envFile, $true)
            $candidateEnvFile = $null
        } finally {
            if ($null -ne $candidateEnvFile -and (Test-Path -LiteralPath $candidateEnvFile -PathType Leaf)) {
                Remove-Item -LiteralPath $candidateEnvFile -Force
            }
        }

        Write-Output "CUDA Toolkit: $(Split-Path -Parent $cudaBinDirectory)"
        Write-Output "cuDNN runtime: $cudnnBinDirectory"
        Write-Output "Visible CUDA devices: $deviceCount"
    } catch {
        Write-Error "Paddle CUDA environment setup failed: $($_.Exception.Message)"
        exit 1
    }