param(
    [string]$SkillsDirectory = (Join-Path $env:USERPROFILE '.agents\skills'),
    [switch]$InstallDependencies,
    [string]$PythonExecutable = 'python'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
foreach ($required in @('.agents\skills\embodied-paper-reader\SKILL.md', 'docs\acceptance.md', 'scripts\paper_workflow.py', 'scripts\zotero_sync.py', 'requirements.txt')) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $required) -PathType Leaf)) {
        throw "Complete repository required; missing: $required"
    }
}
$source = (Resolve-Path -LiteralPath (Join-Path $repoRoot '.agents\skills\embodied-paper-reader')).Path
$skillsRoot = [IO.Path]::GetFullPath($SkillsDirectory)
$destination = Join-Path $skillsRoot 'embodied-paper-reader'
$alreadyInstalled = $false

$existing = Get-Item -LiteralPath $destination -Force -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.LinkType -eq 'Junction' -and $existing.Target -and
        [IO.Path]::GetFullPath([string]@($existing.Target)[0]) -eq $source) {
        $alreadyInstalled = $true
    }
    else {
        throw "Destination already exists; kept unchanged: $destination"
    }
}

if ($InstallDependencies) {
    & $PythonExecutable -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 'Python 3.10+ required')"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ is required; no Skill link was created.' }
    & $PythonExecutable -m pip install -r (Join-Path $repoRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; see INSTALL.md for package source options.' }
    & $PythonExecutable -c "import bs4, filelock, pymupdf, requests; from keyring.backends.Windows import WinVaultKeyring"
    if ($LASTEXITCODE -ne 0) { throw 'Dependency import check failed; no Skill link was created.' }
    Write-Output 'Python dependencies verified.'
}

if (-not $alreadyInstalled) {
    New-Item -ItemType Directory -Path $skillsRoot -Force | Out-Null
    New-Item -ItemType Junction -Path $destination -Value $source | Out-Null
}
$resolvedSkill = (Get-Item -LiteralPath $destination -Force).Target
if ([IO.Path]::GetFullPath([string]@($resolvedSkill)[0]) -ne $source) {
    throw 'Installed Skill link does not point to this repository.'
}
Write-Output "Skill link verified: $destination"
Write-Output 'Use embodied-paper-reader on your next turn. Zotero connectivity and write authorization are checked separately.'
