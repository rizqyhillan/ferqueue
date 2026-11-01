[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet('setup-data', 'setup-inference', 'prepare', 'clean-dataset', 'predict', 'check', 'test', 'import-model', 'train', 'export', 'evaluate')]
    [string]$Action,
    [string]$Config = 'configs/training.json',
    [Alias('Input')][string]$Images = 'data/inference',
    [string]$Output = 'outputs/predictions',
    [string]$Archive = 'outputs/ssd-model.zip',
    [string]$Python,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

function Get-BasePython {
    if ($Python) {
        & $Python -c 'import sys; assert (3, 10) <= sys.version_info[:2] <= (3, 12) and sys.maxsize > 2**32'
        if ($LASTEXITCODE -ne 0) { throw 'Gunakan Python 3.10-3.12 64-bit; Python 3.11 disarankan.' }
        return $Python
    }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $candidate = & $launcher.Source -3.11 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $candidate) { return ($candidate | Select-Object -Last 1) }
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notlike '*WindowsApps*') {
        & $command.Source -c 'import sys; assert (3, 10) <= sys.version_info[:2] <= (3, 12) and sys.maxsize > 2**32'
        if ($LASTEXITCODE -eq 0) { return $command.Source }
    }
    throw 'Pasang Python 3.11 64-bit dari python.org, atau gunakan -Python dengan path lengkap python.exe.'
}

Push-Location $repoRoot
$previousPythonPath = $env:PYTHONPATH
try {
    if ($Action -in @('train', 'export', 'evaluate')) {
        throw 'Training/evaluasi dilakukan di laptop NVIDIA melalui Ubuntu WSL2: bash scripts/cv.sh train (lihat docs/TRAINING_GPU_WINDOWS.md).'
    }
    $inference = $Action -in @('setup-inference', 'predict', 'check')
    $environment = if ($inference) { '.venv-inference' } else { '.venv-data' }
    $pythonExe = Join-Path $repoRoot "$environment\Scripts\python.exe"
    if ($Action -in @('setup-data', 'setup-inference')) {
        if (-not (Test-Path -LiteralPath $pythonExe)) {
            $basePython = Get-BasePython
            if ($inference) {
                & $basePython -c 'import sys; assert sys.version_info[:2] == (3, 11)'
                if ($LASTEXITCODE -ne 0) { throw 'Prediksi TensorFlow ini memerlukan Python 3.11 64-bit.' }
            }
            & $basePython -m venv $environment
            if ($LASTEXITCODE -ne 0) { throw 'Pembuatan environment Python gagal.' }
        }
        $requirements = if ($inference) { 'apps/computer-vision/requirements-inference.txt' } else { 'apps/computer-vision/requirements-data.txt' }
        & $pythonExe -m pip install -r $requirements
        if ($LASTEXITCODE -ne 0) { throw 'Instalasi kebutuhan Python gagal. Periksa koneksi dan versi Python.' }
        Write-Host "Environment $environment siap."
        return
    }
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        $setup = if ($inference) { 'setup-inference' } else { 'setup-data' }
        throw "Environment belum ada. Jalankan .\scripts\cv.ps1 $setup terlebih dahulu."
    }
    $env:PYTHONPATH = Join-Path $repoRoot 'apps\computer-vision\src'
    if ($previousPythonPath) { $env:PYTHONPATH += [IO.Path]::PathSeparator + $previousPythonPath }
    $cliAction = if ($Action -eq 'check') { 'check-inference' } else { $Action }
    $cliArgs = @($cliAction, '--config', $Config)
    if ($DryRun) { $cliArgs += '--dry-run' }
    if ($Action -eq 'predict') { $cliArgs += @('--input', $Images, '--output', $Output) }
    if ($Action -eq 'import-model') { $cliArgs += @('--archive', $Archive) }
    & $pythonExe -m ferqueue_cv @cliArgs
    if ($LASTEXITCODE -ne 0) { throw "Perintah '$Action' gagal (exit $LASTEXITCODE). Periksa pesan di atas." }
} finally {
    $env:PYTHONPATH = $previousPythonPath
    Pop-Location
}
