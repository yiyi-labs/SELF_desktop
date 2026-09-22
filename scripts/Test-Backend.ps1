param([switch]$Live)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
& backend/.venv/Scripts/python.exe -m unittest discover -s backend -p 'test_*.py' -v
if($LASTEXITCODE -ne 0){throw 'Backend unit/HTTP tests failed'}
if($Live){& backend/.venv/Scripts/python.exe backend/test_live.py;if($LASTEXITCODE -ne 0){throw 'Real model probe failed or unverified; inspect docs/evidence/deepseek/live-results.json'}}
