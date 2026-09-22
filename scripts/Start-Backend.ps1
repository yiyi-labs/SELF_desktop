param([int]$Port=8787)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$python=Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'
if(!(Test-Path -LiteralPath $python)){throw 'Create backend/.venv and install backend/requirements.lock.txt first.'}
$env:SELF_DEV_LOOPBACK='1'
Set-Location -LiteralPath (Join-Path $projectRoot 'backend')
& $python -m uvicorn app:app --host 127.0.0.1 --port $Port --no-access-log
