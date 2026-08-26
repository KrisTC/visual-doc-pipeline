#!/usr/bin/env pwsh
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$CredentialFile,
    [Parameter()]
    [string]$Location
)

$ErrorActionPreference = 'Stop'

$managedMarker = '# Managed by scripts/configure-google-cloud-translation.ps1'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$environmentFile = Join-Path $projectRoot '.env.local'
$runScript = Join-Path $PSScriptRoot 'run.ps1'

function Get-ServiceAccountConfiguration {
    param([string]$CredentialFile)

    if (-not [System.IO.Path]::IsPathFullyQualified($CredentialFile)) {
        throw 'The credential file path must be absolute.'
    }
    if (-not (Test-Path -LiteralPath $CredentialFile -PathType Leaf)) {
        throw 'The credential file does not exist.'
    }

    try {
        $credential = [System.IO.File]::ReadAllText($CredentialFile) | ConvertFrom-Json
    } catch {
        throw 'The credential file is not valid JSON.'
    }
    if ($credential.type -ne 'service_account' -or [string]::IsNullOrWhiteSpace($credential.project_id)) {
        throw 'The credential file is not a service-account credential JSON file with a project ID.'
    }

    return [pscustomobject]@{
        Path = (Resolve-Path -LiteralPath $CredentialFile).Path
        ProjectId = [string]$credential.project_id
    }
}

function Get-ManagedEnvironmentContent {
    param(
        [string]$ExistingContent,
        [string]$CredentialPath,
        [string]$ProjectId,
        [string]$Location
    )

    $newLine = if ($ExistingContent.Contains("`r`n")) { "`r`n" } else { "`n" }
    $credentialPathForDotenv = $CredentialPath.Replace('\', '/')
    $managedLines = [System.Collections.Generic.List[string]]::new()
    $managedLines.Add($managedMarker)
    $managedLines.Add(('GOOGLE_APPLICATION_CREDENTIALS="' + $credentialPathForDotenv + '"'))
    $managedLines.Add("GOOGLE_CLOUD_PROJECT=$ProjectId")
    if (-not [string]::IsNullOrWhiteSpace($Location)) {
        $managedLines.Add("GOOGLE_CLOUD_TRANSLATION_LOCATION=$Location")
    }
    $managedBlock = $managedLines -join $newLine

    $withoutPreviousSettings = [regex]::Replace(
        $ExistingContent,
        '(?im)^(?:GOOGLE_APPLICATION_CREDENTIALS|GOOGLE_CLOUD_PROJECT|GOOGLE_CLOUD_TRANSLATION_LOCATION)=[^\r\n]*(?:\r?\n)?',
        ''
    )
    $withoutPreviousSettings = [regex]::Replace(
        $withoutPreviousSettings,
        '(?m)^' + [regex]::Escape($managedMarker) + '\r?\n?',
        ''
    )
    if ([string]::IsNullOrEmpty($withoutPreviousSettings)) {
        return "$managedBlock$newLine"
    }
    $separator = if ($withoutPreviousSettings.EndsWith("`n") -or $withoutPreviousSettings.EndsWith("`r")) { '' } else { $newLine }
    return "$withoutPreviousSettings$separator$managedBlock$newLine"
}

function Invoke-GoogleCloudTranslationProbe {
    param([string]$CandidateEnvironmentFile)

    $probeCode = @(
        'from pipeline.text_replacement.models import TextReplacementRequest',
        'from pipeline.text_replacement_plugins.google_cloud_translate import GoogleCloudTranslateProvider',
        '',
        'result = GoogleCloudTranslateProvider().replace(TextReplacementRequest("translation configuration probe", False, "en", "fr"))',
        'if not result.text:',
        '    raise RuntimeError("Google Cloud Translation returned empty probe text.")',
        'print("GOOGLE_CLOUD_TRANSLATION_PROBE=ok")'
    ) -join "`n"

    $probeOutput = @(& $runScript -EnvFile $CandidateEnvironmentFile python -c $probeCode 2>&1)
    $probeText = ($probeOutput | ForEach-Object { $_.ToString() }) -join "`n"
    if ($LASTEXITCODE -ne 0 -or [regex]::Matches($probeText, '(?m)^GOOGLE_CLOUD_TRANSLATION_PROBE=ok$').Count -ne 1) {
        throw 'Google Cloud Translation credential validation failed.'
    }
}

try {
    if (-not (Test-Path -LiteralPath $runScript -PathType Leaf)) {
        throw 'The required scripts/run.ps1 wrapper was not found.'
    }

    $serviceAccount = Get-ServiceAccountConfiguration $CredentialFile
    $normalizedLocation = $Location.Trim()
    $existingContent = if (Test-Path -LiteralPath $environmentFile -PathType Leaf) {
        [System.IO.File]::ReadAllText($environmentFile)
    } else {
        ''
    }
    $candidateContent = Get-ManagedEnvironmentContent `
        $existingContent $serviceAccount.Path $serviceAccount.ProjectId $normalizedLocation
    $candidateEnvironmentFile = Join-Path $projectRoot ('.env.local.{0}.tmp' -f [guid]::NewGuid().ToString('N'))

    try {
        $utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
        [System.IO.File]::WriteAllText($candidateEnvironmentFile, $candidateContent, $utf8WithoutBom)
        Invoke-GoogleCloudTranslationProbe $candidateEnvironmentFile
        [System.IO.File]::Move($candidateEnvironmentFile, $environmentFile, $true)
        $candidateEnvironmentFile = $null
    } finally {
        if ($null -ne $candidateEnvironmentFile -and (Test-Path -LiteralPath $candidateEnvironmentFile -PathType Leaf)) {
            Remove-Item -LiteralPath $candidateEnvironmentFile -Force
        }
    }

    $endpoint = if ([string]::IsNullOrWhiteSpace($normalizedLocation)) {
        'translate.googleapis.com'
    } else {
        'translate-eu.googleapis.com'
    }
    $selectedLocation = if ([string]::IsNullOrWhiteSpace($normalizedLocation)) { 'global' } else { $normalizedLocation }
    Write-Output "Credential file: $(Split-Path -Leaf $serviceAccount.Path)"
    Write-Output "Project: $($serviceAccount.ProjectId)"
    Write-Output "Endpoint: $endpoint"
    Write-Output "Location: $selectedLocation"
    Write-Output 'Google Cloud Translation configuration succeeded.'
} catch {
    Write-Error "Google Cloud Translation configuration failed: $($_.Exception.Message)"
    exit 1
}