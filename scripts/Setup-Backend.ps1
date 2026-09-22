param([string]$Python='python')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if(!(Test-Path backend/.venv/Scripts/python.exe)){& $Python -m venv backend/.venv;if($LASTEXITCODE -ne 0){throw 'Python 3.12 or later is required'}}
& backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.lock.txt
if($LASTEXITCODE -ne 0){throw 'Backend dependency installation failed'}
Write-Output 'Create backend/.env from .env.example and configure the key locally. This script never prints or overwrites it.'
