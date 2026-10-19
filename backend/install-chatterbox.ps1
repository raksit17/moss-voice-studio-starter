# Install the English Chatterbox-Turbo worker using Python 3.14, without changing the MOSS API venv.
param([switch]$Cpu)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

& py -3.14 --version
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.14 not found. Install it or check 'py -0p'."
}

if (-not (Test-Path ".venv-chatterbox\Scripts\python.exe")) {
    & py -3.14 -m venv .venv-chatterbox
    if ($LASTEXITCODE -ne 0) { throw "Unable to create Chatterbox Python 3.14 virtual environment" }
}

$python = Join-Path $PSScriptRoot ".venv-chatterbox\Scripts\python.exe"
$version = & $python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($version -ne "3.14") {
    throw "Existing .venv-chatterbox uses Python $version. Recreate only that venv using Python 3.14; do not delete your MOSS .venv."
}

$argsList = @("scripts/install_chatterbox.py")
if ($Cpu) { $argsList += "--cpu" }
& $python @argsList
if ($LASTEXITCODE -ne 0) { throw "Chatterbox installation failed; inspect pip output above." }

& $python -c "import torch; from chatterbox.tts_turbo import ChatterboxTurboTTS; print('Chatterbox Turbo import: OK'); print('PyTorch:', torch.__version__); print('CUDA available:', torch.cuda.is_available())"
if ($LASTEXITCODE -ne 0) { throw "Chatterbox import check failed; inspect errors above." }
Write-Host "Chatterbox-Turbo installed. Use Model Manager > Load / Warm Turbo." -ForegroundColor Green
