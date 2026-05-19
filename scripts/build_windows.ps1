<#
.SYNOPSIS
    Build the YTSpot Downloader Windows release (portable ZIP + Inno Setup input folder).

.DESCRIPTION
    1. Verifies python is on PATH.
    2. (Optional) requires ffmpeg.exe and ffprobe.exe to already be staged
       in packaging/ffmpeg/ when -RequireBundledFfmpeg is set.
    3. Regenerates packaging/version_info.txt from version.py.
    4. Runs PyInstaller against packaging/ytspot.spec.
    5. Produces:
         dist/ytspot/                               - one-folder portable build (input for Inno Setup)
         dist/ytspot-<version>-windows-portable.zip - portable ZIP for direct distribution
         dist/SHA256SUMS.txt                        - SHA-256 checksums for the ZIP
    6. Prints a short summary with sizes and exact next-step commands.

.PARAMETER RequireBundledFfmpeg
    Fail the build unless packaging/ffmpeg/ contains both ffmpeg.exe and
    ffprobe.exe before running PyInstaller. This script does not download
    FFmpeg automatically.

.PARAMETER SkipTests
    Skip the unit-test run that normally happens before packaging.

.EXAMPLE
    pwsh scripts/build_windows.ps1
    Builds with whatever is already in packaging/ffmpeg/ (or no FFmpeg at all).

.EXAMPLE
    pwsh scripts/build_windows.ps1 -RequireBundledFfmpeg
    Requires staged FFmpeg binaries, then builds.

.NOTES
    Run from the repository root or from the scripts/ folder; the
    script normalises the working directory either way.
#>

[CmdletBinding()]
param(
    [switch]$RequireBundledFfmpeg,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'

function Get-BuildRelatedProcesses {
    param(
        [Parameter(Mandatory = $true)]
        [int]$RootProcessId,

        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $all = @(Get-CimInstance Win32_Process)
    $descendantIds = New-Object 'System.Collections.Generic.HashSet[int]'
    $queue = New-Object 'System.Collections.Generic.Queue[int]'
    $queue.Enqueue($RootProcessId)

    while ($queue.Count -gt 0) {
        $parentId = $queue.Dequeue()
        foreach ($proc in $all | Where-Object { [int]$_.ParentProcessId -eq $parentId }) {
            $processId = [int]$proc.ProcessId
            if ($descendantIds.Add($processId)) {
                $queue.Enqueue($processId)
            }
        }
    }

    $targets = @()
    foreach ($proc in $all) {
        $processId = [int]$proc.ProcessId
        if ($processId -eq $PID) {
            continue
        }

        $name = ([string]$proc.Name).ToLowerInvariant()
        $cmd = [string]$proc.CommandLine
        $isDescendant = $descendantIds.Contains($processId)
        $isRepoRelated = $cmd -and $cmd.Contains($RepoRoot)
        $isBuildTool = $name -in @('node.exe', 'playwright.exe', 'pyinstaller.exe') -or (
            $name -in @('python.exe', 'python3.exe', 'py.exe') -and
            $cmd -match '(?i)pyinstaller|playwright'
        )

        if ($isBuildTool -and ($isDescendant -or $isRepoRelated)) {
            $targets += $proc
        }
    }

    return $targets
}

function Stop-BuildRelatedProcesses {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $targets = @(Get-BuildRelatedProcesses -RootProcessId $PID -RepoRoot $RepoRoot)
    foreach ($proc in $targets) {
        $processId = [int]$proc.ProcessId
        $name = [string]$proc.Name
        Write-Host "    Stopping leftover build child process: $name (PID $processId)" -ForegroundColor Yellow
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
        } catch {
            Write-Warning "Could not stop $name (PID $processId): $($_.Exception.Message)"
        }
    }
}

function Get-LockedFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    foreach ($file in Get-ChildItem -Path $Path -Recurse -File) {
        $stream = $null
        try {
            $stream = [System.IO.File]::Open(
                $file.FullName,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                [System.IO.FileShare]::Read
            )
        } catch [System.IO.IOException] {
            return $file.FullName
        } finally {
            if ($stream) {
                $stream.Dispose()
            }
        }
    }

    return $null
}

function New-PortableZip {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceDir,

        [Parameter(Mandatory = $true)]
        [string]$ZipPath,

        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $maxAttempts = 5
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        Stop-BuildRelatedProcesses -RepoRoot $RepoRoot

        $locked = Get-LockedFile -Path $SourceDir
        if ($locked) {
            Write-Warning "File is still locked before ZIP attempt ${attempt}/${maxAttempts}: $locked"
            Start-Sleep -Seconds $attempt
            continue
        }

        if (Test-Path $ZipPath) {
            Remove-Item -Force $ZipPath
        }

        try {
            [System.IO.Compression.ZipFile]::CreateFromDirectory(
                $SourceDir,
                $ZipPath,
                [System.IO.Compression.CompressionLevel]::Optimal,
                $false
            )
            return
        } catch [System.IO.IOException] {
            Write-Warning "ZIP attempt ${attempt}/${maxAttempts} failed: $($_.Exception.Message)"
            if (Test-Path $ZipPath) {
                Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue
            }
            Start-Sleep -Seconds $attempt
        }
    }

    throw "Failed to create ZIP after $maxAttempts attempts. A build or Playwright file is still locked under $SourceDir."
}

# Normalise working directory to the repo root.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

Write-Host "==> YTSpot Downloader Windows build" -ForegroundColor Cyan
Write-Host "    Repo root: $RepoRoot"

# Pre-flight: Python on PATH.
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    throw "python is not on PATH. Install Python 3.10+ and re-run."
}
$pyVer = (& python --version) -replace '^Python\s+', ''
Write-Host "    Python: $pyVer ($($py.Source))"

# Read the canonical version so we can name the output ZIP correctly.
$AppVersion = (& python -c "from version import __version__; print(__version__)").Trim()
Write-Host "    App version: $AppVersion"

# Optional: require staged FFmpeg binaries.
$FfmpegDir = Join-Path $RepoRoot 'packaging\ffmpeg'

if ($RequireBundledFfmpeg) {
    Write-Host "==> Requiring bundled FFmpeg from $FfmpegDir" -ForegroundColor Cyan
    $RequiredFfmpegFiles = @('ffmpeg.exe', 'ffprobe.exe')
    $MissingFfmpegFiles = @()

    foreach ($name in $RequiredFfmpegFiles) {
        $path = Join-Path $FfmpegDir $name
        if (-not (Test-Path -Path $path -PathType Leaf)) {
            $MissingFfmpegFiles += $path
        }
    }

    if ($MissingFfmpegFiles.Count -gt 0) {
        $NewLine = [Environment]::NewLine
        $MissingList = (($MissingFfmpegFiles | ForEach-Object { "  - $_" }) -join $NewLine)
        $Message = "Required bundled FFmpeg files are missing:$NewLine$MissingList$NewLine$NewLine"
        $Message += "Place LGPL-licensed Windows FFmpeg binaries exactly here:$NewLine"
        $Message += "  $FfmpegDir\ffmpeg.exe$NewLine"
        $Message += "  $FfmpegDir\ffprobe.exe$NewLine$NewLine"
        $Message += "This script does not auto-download FFmpeg because the release must not accidentally bundle a GPL build."
        throw $Message
    }

    Write-Host "    Found ffmpeg.exe and ffprobe.exe."
    Write-Host "    Build will fail if PyInstaller does not copy both next to ytspot.exe."
} else {
    if (Test-Path (Join-Path $FfmpegDir 'ffmpeg.exe')) {
        Write-Host "    Bundling FFmpeg from $FfmpegDir"
    } else {
        Write-Host "    No FFmpeg in $FfmpegDir - building without bundled FFmpeg." -ForegroundColor Yellow
        Write-Host "    Users will need ffmpeg on their PATH or installed system-wide."
    }
}

# Run unit tests unless explicitly skipped.
if (-not $SkipTests) {
    Write-Host "==> Running unit tests" -ForegroundColor Cyan
    $env:QT_QPA_PLATFORM = 'offscreen'
    & python -m pytest tests/ -q --tb=line
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests failed. Fix them or re-run with -SkipTests to bypass."
    }
}

# Ensure build deps are present.
Write-Host "==> Installing build dependencies" -ForegroundColor Cyan
& python -m pip install --upgrade pip pyinstaller | Out-Null
& python -m pip install -r requirements.txt | Out-Null

# Regenerate VS_VERSIONINFO from version.py.
Write-Host "==> Regenerating version_info.txt" -ForegroundColor Cyan
& python packaging\generate_version_info.py

# Clean previous build outputs.
Write-Host "==> Cleaning previous build/ and dist/" -ForegroundColor Cyan
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist)  { Remove-Item -Recurse -Force dist }

# PyInstaller.
Write-Host "==> Running PyInstaller" -ForegroundColor Cyan
& python -m PyInstaller --noconfirm --clean packaging\ytspot.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed. See output above."
}
Stop-BuildRelatedProcesses -RepoRoot $RepoRoot

$DistDir = Join-Path $RepoRoot 'dist\ytspot'
if (-not (Test-Path $DistDir)) {
    throw "Expected $DistDir to exist after PyInstaller run."
}

if ($RequireBundledFfmpeg) {
    $MissingDistFfmpeg = @()
    foreach ($name in @('ffmpeg.exe', 'ffprobe.exe')) {
        $path = Join-Path $DistDir $name
        if (-not (Test-Path -Path $path -PathType Leaf)) {
            $MissingDistFfmpeg += $path
        }
    }

    if ($MissingDistFfmpeg.Count -gt 0) {
        $NewLine = [Environment]::NewLine
        $MissingList = (($MissingDistFfmpeg | ForEach-Object { "  - $_" }) -join $NewLine)
        throw "PyInstaller did not copy the required bundled FFmpeg files next to ytspot.exe:$NewLine$MissingList"
    }

    Write-Host "    Bundled FFmpeg confirmed in dist\ytspot\ next to ytspot.exe."
}

# Portable ZIP.
$ZipName = "ytspot-$AppVersion-windows-portable.zip"
$ZipPath = Join-Path $RepoRoot "dist\$ZipName"
Write-Host "==> Creating portable ZIP: $ZipName" -ForegroundColor Cyan
New-PortableZip -SourceDir $DistDir -ZipPath $ZipPath -RepoRoot $RepoRoot

# SHA-256 checksums.
$ChecksumPath = Join-Path $RepoRoot 'dist\SHA256SUMS.txt'
Write-Host "==> Writing SHA-256 checksums" -ForegroundColor Cyan
$hashes = @()
foreach ($f in Get-ChildItem -Path (Join-Path $RepoRoot 'dist') -File `
                              -Filter 'ytspot-*' ) {
    $h = (Get-FileHash $f.FullName -Algorithm SHA256).Hash.ToLower()
    $hashes += "$h  $($f.Name)"
}
$hashes | Set-Content -Path $ChecksumPath -Encoding utf8

# Summary.
$DistSizeMB = [math]::Round(((Get-ChildItem -Recurse $DistDir | Measure-Object Length -Sum).Sum / 1MB), 1)
$ZipSizeMB  = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)

Write-Host ""
Write-Host "==> Build complete" -ForegroundColor Green
Write-Host "    App version : $AppVersion"
Write-Host "    Portable    : $DistDir"
Write-Host "                  $($DistSizeMB) MB on disk"
Write-Host "    ZIP         : $ZipPath"
Write-Host "                  $($ZipSizeMB) MB"
Write-Host "    Checksums   : $ChecksumPath"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  Smoke-test     : & '$DistDir\ytspot.exe'"
Write-Host "  CLI smoke      : & '$DistDir\ytspot-cli.exe' --version"
Write-Host "  Inno installer : iscc packaging\ytspot.iss"
Write-Host ""
