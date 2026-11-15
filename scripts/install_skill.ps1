param(
    [string]$SkillsDirectory = (Join-Path $env:USERPROFILE '.agents\skills')
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$source = (Resolve-Path -LiteralPath (Join-Path $repoRoot '.agents\skills\embodied-paper-reader')).Path
$skillsRoot = [IO.Path]::GetFullPath($SkillsDirectory)
$destination = Join-Path $skillsRoot 'embodied-paper-reader'

$existing = Get-Item -LiteralPath $destination -Force -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.LinkType -eq 'Junction' -and $existing.Target -and
        [IO.Path]::GetFullPath([string]@($existing.Target)[0]) -eq $source) {
        Write-Output "Already installed: $destination"
        exit 0
    }
    throw "Destination already exists; kept unchanged: $destination"
}

New-Item -ItemType Directory -Path $skillsRoot -Force | Out-Null
New-Item -ItemType Junction -Path $destination -Value $source | Out-Null
Write-Output "Installed: $destination"
