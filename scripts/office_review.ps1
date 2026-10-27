#Requires -Version 5.1
<#
.SYNOPSIS
Compare translated Office documents with their sources side by side.

.DESCRIPTION
Lists translated .pptx, .docx, and .xlsx files below a development revision directory
that have a .diagnostics.json sidecar, then opens the selected file and its source
read-only. PowerPoint uses slide sync; Word and Excel are tiled side by side
without sync. Development tool only; requires Microsoft Office.

.PARAMETER RevisionPath
Revision directory produced by development_folder_replacement.py.

.EXAMPLE
.\scripts\office_review.ps1 -RevisionPath outputs\evaluations\dirdev\<source>\<pair>\v1
#>
param(
    [Parameter(Mandatory)]
    [string]$RevisionPath
)

$ErrorActionPreference = "Stop"

function Initialize-WindowNative {
    if ("WindowNative" -as [type]) {
        return
    }

    Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class WindowNative {
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    public static extern bool MoveWindow(IntPtr hWnd, int x, int y, int width, int height, bool repaint);
}
"@
}

function Set-SideBySideLayout {
    param(
        [Parameter(Mandatory)]
        [IntPtr]$LeftHandle,
        [Parameter(Mandatory)]
        [IntPtr]$RightHandle
    )

    Initialize-WindowNative
    Add-Type -AssemblyName System.Windows.Forms

    $area = [Windows.Forms.Screen]::FromHandle($LeftHandle).WorkingArea
    $half = [int]($area.Width / 2)

    # SW_RESTORE = 9, so maximized windows can be moved
    [WindowNative]::ShowWindow($LeftHandle, 9) | Out-Null
    [WindowNative]::ShowWindow($RightHandle, 9) | Out-Null
    [WindowNative]::MoveWindow($LeftHandle, $area.Left, $area.Top, $half, $area.Height, $true) | Out-Null
    [WindowNative]::MoveWindow($RightHandle, $area.Left + $half, $area.Top, $area.Width - $half, $area.Height, $true) | Out-Null
    [WindowNative]::SetForegroundWindow($RightHandle) | Out-Null
}

function Compare-Presentation {
    param(
        [Parameter(Mandatory)]
        [string]$TranslatedPath
    )

    $translated = (Resolve-Path -LiteralPath $TranslatedPath -ErrorAction Stop).Path
    $metadataPath = "$translated.diagnostics.json"
    if (-not (Test-Path -LiteralPath $metadataPath)) {
        throw "Diagnostics sidecar not found: $metadataPath"
    }

    $metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
    $source = $metadata.source_absolute_path
    if (-not $source -or -not (Test-Path -LiteralPath $source)) {
        throw "Source presentation not found: $source"
    }

    # PowerPoint COM fails to open paths containing forward slashes
    $source = [IO.Path]::GetFullPath($source)

    Write-Host "Source:     $source"
    Write-Host "Translated: $translated"

    try {
        $ppt = [Runtime.InteropServices.Marshal]::GetActiveObject("PowerPoint.Application")
    }
    catch {
        $ppt = New-Object -ComObject PowerPoint.Application
    }
    $ppt.Visible = -1

    # Open both presentations read-only, without title window
    $original = $ppt.Presentations.Open($source, -1, 0, -1)
    $translation = $ppt.Presentations.Open($translated, -1, 0, -1)

    $leftWindow = $original.Windows.Item(1)
    $rightWindow = $translation.Windows.Item(1)

    # ppViewSlide = 1, no thumbnails
    $leftWindow.ViewType = 1
    $rightWindow.ViewType = 1

    $ppt.Windows.Arrange(1)

    $left = [Math]::Min([double]$leftWindow.Left, [double]$rightWindow.Left)
    $top = [Math]::Min([double]$leftWindow.Top, [double]$rightWindow.Top)
    $width = [double]$leftWindow.Width + [double]$rightWindow.Width
    $height = [Math]::Max([double]$leftWindow.Height, [double]$rightWindow.Height)
    $halfWidth = $width / 2

    foreach ($window in @($leftWindow, $rightWindow)) {
        $window.WindowState = 1  # ppWindowNormal
        $window.Width = $halfWidth
        $window.Height = $height
        $window.Top = $top
    }
    $leftWindow.Left = $left
    $rightWindow.Left = $left + $halfWidth

    Initialize-WindowNative

    $leftWindow.Activate()
    [WindowNative]::SetForegroundWindow(
        (Get-Process -Name POWERPNT | Select-Object -First 1).MainWindowHandle
    ) | Out-Null

    Write-Host "Original left, translation right."
    Write-Host "Slide sync active. Close either presentation to exit."

    # Re-read windows so stale references from before arranging are not used
    $leftWindow = $original.Windows.Item(1)
    $rightWindow = $translation.Windows.Item(1)
    $lastLeft = [int]$leftWindow.View.Slide.SlideIndex
    $lastRight = [int]$rightWindow.View.Slide.SlideIndex

    try {
        while ($true) {
            Start-Sleep -Milliseconds 200

            $openWindows = @{}
            foreach ($window in $ppt.Windows) {
                $openWindows[[int]$window.HWND] = $true
            }
            $leftOpen = $openWindows.ContainsKey([int]$leftWindow.HWND)
            $rightOpen = $openWindows.ContainsKey([int]$rightWindow.HWND)

            if (-not $leftOpen -or -not $rightOpen) {
                $answer = Read-Host "Presentation closed. Stop comparison? [Y/n]"
                if ($answer -eq "" -or $answer -match "^[Yy]") {
                    break
                }
                continue
            }

            # View is null while a modal dialog (e.g. Save As) is open
            if ($null -eq $leftWindow.View -or $null -eq $rightWindow.View) {
                continue
            }

            $left = [int]$leftWindow.View.Slide.SlideIndex
            $right = [int]$rightWindow.View.Slide.SlideIndex

            if ($left -ne $lastLeft) {
                if ($left -le $translation.Slides.Count) {
                    $rightWindow.View.GotoSlide($left)
                    $right = $left
                }
            }
            elseif ($right -ne $lastRight) {
                if ($right -le $original.Slides.Count) {
                    $leftWindow.View.GotoSlide($right)
                    $left = $right
                }
            }

            $lastLeft = $left
            $lastRight = $right
        }
    }
    catch {
        Write-Host "Comparison interrupted: $($_.Exception.Message)"
    }
    finally {
        # Close only the two presentations opened here
        foreach ($presentation in @($original, $translation)) {
            try {
                $presentation.Close()
            }
            catch {
                # Already closed
            }
        }
        Write-Host "Comparison finished."
    }
}

function Get-SourcePath {
    param(
        [Parameter(Mandatory)]
        [string]$TranslatedPath
    )

    $metadataPath = "$TranslatedPath.diagnostics.json"
    if (-not (Test-Path -LiteralPath $metadataPath)) {
        throw "Diagnostics sidecar not found: $metadataPath"
    }

    $source = (Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json).source_absolute_path
    if (-not $source -or -not (Test-Path -LiteralPath $source)) {
        throw "Source document not found: $source"
    }

    # PowerPoint and Word COM fail to open paths containing forward slashes
    return [IO.Path]::GetFullPath($source)
}

function Get-OfficeApplication {
    param(
        [Parameter(Mandatory)]
        [string]$ProgId
    )

    try {
        $app = [Runtime.InteropServices.Marshal]::GetActiveObject($ProgId)
    }
    catch {
        $app = New-Object -ComObject $ProgId
    }
    $app.Visible = $true
    return $app
}

function Compare-Word {
    param(
        [Parameter(Mandatory)]
        [string]$TranslatedPath
    )

    $translated = (Resolve-Path -LiteralPath $TranslatedPath -ErrorAction Stop).Path
    $source = Get-SourcePath -TranslatedPath $translated
    Write-Host "Source:     $source"
    Write-Host "Translated: $translated"

    $word = Get-OfficeApplication -ProgId "Word.Application"
    $null = $word.Documents.Open($source, $false, $true)
    $originalWindow = $word.ActiveWindow
    $null = $word.Documents.Open($translated, $false, $true)
    $translationWindow = $word.ActiveWindow

    Set-SideBySideLayout -LeftHandle ([IntPtr][long]$originalWindow.Hwnd) -RightHandle ([IntPtr][long]$translationWindow.Hwnd)
    Write-Host "Original left, translation right. Documents stay open."
}

function Compare-Excel {
    param(
        [Parameter(Mandatory)]
        [string]$TranslatedPath,
        [Parameter(Mandatory)]
        [string]$RevisionDirectory,
        [Parameter(Mandatory)]
        [int]$Index
    )

    $translated = (Resolve-Path -LiteralPath $TranslatedPath -ErrorAction Stop).Path
    $source = Get-SourcePath -TranslatedPath $translated
    Write-Host "Source:     $source"
    Write-Host "Translated: $translated"

    # Excel cannot open two workbooks with the same file name, so open a numbered copy
    $sourceToOpen = $source
    if ([IO.Path]::GetFileName($source) -eq [IO.Path]::GetFileName($translated)) {
        $copyDirectory = Join-Path $RevisionDirectory "tmp_diff"
        $sourceToOpen = Join-Path $copyDirectory "$Index.xlsx"
        New-Item -ItemType Directory -Path $copyDirectory -Force | Out-Null
        try {
            Copy-Item -LiteralPath $source -Destination $sourceToOpen -Force
        }
        catch {
            throw "Close the workbook open from $sourceToOpen, then compare again."
        }
        Write-Host "Name matches; opening copy: $sourceToOpen"
    }

    $excel = Get-OfficeApplication -ProgId "Excel.Application"
    # UpdateLinks = 0 (do not update), ReadOnly = true
    $null = $excel.Workbooks.Open($sourceToOpen, 0, $true)
    $originalWindow = $excel.ActiveWindow
    $null = $excel.Workbooks.Open($translated, 0, $true)
    $translationWindow = $excel.ActiveWindow

    Set-SideBySideLayout -LeftHandle ([IntPtr][long]$originalWindow.Hwnd) -RightHandle ([IntPtr][long]$translationWindow.Hwnd)
    Write-Host "Original left, translation right. Workbooks stay open."
}

function Compare-Document {
    param(
        [Parameter(Mandatory)]
        [string]$TranslatedPath,
        [Parameter(Mandatory)]
        [int]$Index
    )

    switch ([IO.Path]::GetExtension($TranslatedPath).ToLowerInvariant()) {
        ".pptx" { Compare-Presentation -TranslatedPath $TranslatedPath }
        ".docx" { Compare-Word -TranslatedPath $TranslatedPath }
        ".xlsx" { Compare-Excel -TranslatedPath $TranslatedPath -RevisionDirectory $revision -Index $Index }
        default { throw "Unsupported file type: $TranslatedPath" }
    }
}

$revision = (Resolve-Path -LiteralPath $RevisionPath -ErrorAction Stop).Path

while ($true) {
    $candidates = @(Get-ChildItem -LiteralPath $revision -File -Recurse |
        Where-Object {
            $_.Extension -in @(".pptx", ".docx", ".xlsx") -and
            -not $_.Name.StartsWith("~$") -and
            (Test-Path -LiteralPath "$($_.FullName).diagnostics.json")
        } |
        Sort-Object FullName)

    if ($candidates.Count -eq 0) {
        throw "No translated .pptx files with diagnostics found in $revision"
    }

    if ($candidates.Count -eq 1) {
        Compare-Document -TranslatedPath $candidates[0].FullName -Index 1
        break
    }

    for ($i = 0; $i -lt $candidates.Count; $i++) {
        Write-Host "[$($i + 1)] $($candidates[$i].FullName.Substring($revision.Length + 1))"
    }

    $choice = Read-Host "Select a number, or q to quit"
    if ($choice -eq "q") {
        break
    }

    $number = 0
    if (-not [int]::TryParse($choice, [ref]$number) -or $number -lt 1 -or $number -gt $candidates.Count) {
        Write-Host "Invalid selection."
        continue
    }

    Compare-Document -TranslatedPath $candidates[$number - 1].FullName -Index $number
}
