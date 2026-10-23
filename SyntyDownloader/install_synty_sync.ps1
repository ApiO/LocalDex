# Synty Sync installer for Windows 11 / Windows PowerShell 5.1+
# Runs without administrator rights when winget supports per-user installation.
# Launch via install_synty_sync.cmd to avoid permanently changing execution policy.

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectDir = $PSScriptRoot
$ScriptPath = Join-Path $ProjectDir 'synty_sync.py'
$RequirementsPath = Join-Path $ProjectDir 'synty_requirements.txt'
$VenvDir = Join-Path $ProjectDir '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'

function Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Commande echouee ($LASTEXITCODE) : $Executable $($Arguments -join ' ')"
    }
}

function Test-Python([string]$Executable, [string[]]$Prefix = @()) {
    if (-not $Executable -or -not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return $null
    }
    try {
        # We require Python >= 3.10 because synty_sync.py uses 3.10 type syntax.
        $output = & $Executable @Prefix -c 'import sys; assert sys.version_info >= (3, 10); print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $output) {
            $resolved = [string]($output | Select-Object -Last 1)
            if (Test-Path -LiteralPath $resolved -PathType Leaf) {
                return $resolved
            }
        }
    }
    catch {
        # Ignore unusable interpreters and continue discovery.
    }
    return $null
}

function Find-Python {
    $launcher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in @('-3.13', '-3')) {
            $found = Test-Python -Executable $launcher.Source -Prefix @($version)
            if ($found) { return $found }
        }
    }

    $roots = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
        (Join-Path $env:ProgramFiles 'Python'),
        $env:ProgramFiles
    )
    if (${env:ProgramFiles(x86)}) { $roots += ${env:ProgramFiles(x86)} }

    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
        $patterns = @(
            (Join-Path $root 'Python3*\python.exe'),
            (Join-Path $root 'Python*\python.exe')
        )
        foreach ($pattern in $patterns) {
            foreach ($file in (Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)) {
                $found = Test-Python -Executable $file.FullName
                if ($found) { return $found }
            }
        }
    }

    $python = Get-Command 'python.exe' -ErrorAction SilentlyContinue
    if ($python) {
        $found = Test-Python -Executable $python.Source
        if ($found) { return $found }
    }
    return $null
}

try {
    Step 'Verification des fichiers Synty Sync'
    if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) {
        throw "Fichier introuvable : $ScriptPath. Extraire tout le ZIP avant l'installation."
    }

    # A per-process Bypass is provided by the .cmd launcher. We do not use
    # Set-ExecutionPolicy for CurrentUser or LocalMachine, so no lasting change.
    Write-Host 'ExecutionPolicy : aucune modification permanente.'

    Step 'Recherche de Python 3.10 ou plus recent'
    $python = Find-Python

    if (-not $python) {
        Step 'Installation de Python 3.13 pour cet utilisateur (winget)'
        $winget = Get-Command 'winget.exe' -ErrorAction SilentlyContinue
        if (-not $winget) {
            throw "Python introuvable et winget indisponible. Installer App Installer depuis Microsoft, puis relancer cet installateur."
        }

        & $winget.Source install --id Python.Python.3.13 --exact --source winget --scope user --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "winget a retourne le code $LASTEXITCODE. Nouvelle verification de Python..."
        }

        # Refresh PATH for this PowerShell process after a new user install.
        $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
        $env:Path = "$machinePath;$userPath"
        $python = Find-Python
        if (-not $python) {
            throw 'Python est toujours introuvable. Fermer et rouvrir la session Windows, puis relancer install_synty_sync.cmd.'
        }
    }

    Write-Host "Python utilise : $python" -ForegroundColor Green
    Invoke-Checked -Executable $python -Arguments @('--version')

    Step 'Creation ou reutilisation de l environnement Python local (.venv)'
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        Invoke-Checked -Executable $python -Arguments @('-m', 'venv', $VenvDir)
    }
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        throw "Environnement Python non cree : $VenvPython"
    }

    Step 'Installation ou mise a jour des dependances'
    Invoke-Checked -Executable $VenvPython -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip')
    if (Test-Path -LiteralPath $RequirementsPath -PathType Leaf) {
        Invoke-Checked -Executable $VenvPython -Arguments @('-m', 'pip', 'install', '-r', $RequirementsPath)
    }
    else {
        Write-Warning 'synty_requirements.txt absent : installation des dependances essentielles.'
        Invoke-Checked -Executable $VenvPython -Arguments @('-m', 'pip', 'install', 'playwright>=1.50,<2', 'beautifulsoup4>=4.12,<5', 'PyYAML>=6,<7')
    }

    Step 'Installation de Chromium pour Playwright'
    Invoke-Checked -Executable $VenvPython -Arguments @('-m', 'playwright', 'install', 'chromium')

    Step 'Verification finale'
    # Windows PowerShell 5.1 peut supprimer les guillemets internes des arguments natifs.
    # Ne pas inclure de litteral entre guillemets dans le code transmis a python -c.
    Invoke-Checked -Executable $VenvPython -Arguments @('-c', 'import bs4; import playwright; import yaml')
    Write-Host 'Dependances OK' -ForegroundColor Green
    Invoke-Checked -Executable $VenvPython -Arguments @('-m', 'py_compile', $ScriptPath)
    Invoke-Checked -Executable $VenvPython -Arguments @($ScriptPath, '--check-config')

    Write-Host "`nInstallation terminee avec succes !" -ForegroundColor Green
    Write-Host '1. Modifier config.yaml (login.email, login.password, login.customer_id, output_dir).'
    Write-Host '2. Verifier avec : .venv\Scripts\python.exe synty_sync.py --check-config'
    Write-Host '3. Double-cliquer sur run_synty_sync.cmd pour lancer la synchronisation.'
    exit 0
}
catch {
    Write-Host "`nERREUR : $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
