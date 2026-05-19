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
         dist/ytspot/                - one-folder portable build (input for Inno Setup)
         dist/ytspot-portable.zip    - portable ZIP for direct distribution
         dist/SHA256SUMS.txt         - SHA-256 checksums for the ZIP
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
        $MissingList = ($MissingFfmpegFiles -join $NewLine)
        $Message = "Required bundled FFmpeg files are missing:$NewLine$MissingList$NewLine"
        $Message += "Stage an LGPL FFmpeg build in packaging\ffmpeg\ or rerun without -RequireBundledFfmpeg."
        throw $Message
    }

    Write-Host "    Found ffmpeg.exe and ffprobe.exe."
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

$DistDir = Join-Path $RepoRoot 'dist\ytspot'
if (-not (Test-Path $DistDir)) {
    throw "Expected $DistDir to exist after PyInstaller run."
}

# Portable ZIP.
$ZipName = "ytspot-$AppVersion-windows-portable.zip"
$ZipPath = Join-Path $RepoRoot "dist\$ZipName"
Write-Host "==> Creating portable ZIP: $ZipName" -ForegroundColor Cyan
Compress-Archive -Path "$DistDir\*" -DestinationPath $ZipPath -Force

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
