# 1) Interactive login and test of one pack; 2) full headless sync.
# Uses config.yaml for login credentials and output_dir.
param(
    [string]$Config = '',
    [string]$OutputDir = ''  # Legacy compatibility with Dex's old launcher.
)

$ErrorActionPreference = 'Stop'
$ScriptPath = Join-Path $PSScriptRoot 'synty_sync.py'
$VenvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not $Config) { $Config = Join-Path $PSScriptRoot 'config.yaml' }

if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) {
    Write-Host "Fichier introuvable : $ScriptPath" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Write-Host 'Python local non installe. Lancez install_synty_sync.cmd.' -ForegroundColor Red
    exit 1
}
if ($OutputDir) {
    # Keep compatibility with SyntyLocalDex/sync_and_rebuild_dex.cmd,
    # which used to pass -OutputDir. YAML must remain authoritative.
    Write-Warning '-OutputDir est obsolete et ignore : definir output_dir dans config.yaml.'
}

Write-Host "Configuration : $Config" -ForegroundColor Cyan
& $VenvPython $ScriptPath --config $Config --check-config
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Configuration invalide. Execution annulee.' -ForegroundColor Red
    exit 1
}

Write-Host 'Etape 1/2 : connexion interactive et test sur 1 package...' -ForegroundColor Cyan
& $VenvPython $ScriptPath --config $Config --limit-packages 1
$firstExitCode = $LASTEXITCODE
if ($firstExitCode -ne 0) {
    Write-Host "Premiere execution echouee (code $firstExitCode). Etape headless annulee." -ForegroundColor Red
    exit $firstExitCode
}

Write-Host 'Etape 2/2 : synchronisation complete en mode headless...' -ForegroundColor Cyan
& $VenvPython $ScriptPath --config $Config --headless
$secondExitCode = $LASTEXITCODE
if ($secondExitCode -ne 0) {
    Write-Host "Synchronisation headless echouee (code $secondExitCode)." -ForegroundColor Red
    exit $secondExitCode
}

Write-Host 'Synchronisation terminee.' -ForegroundColor Green
exit 0
