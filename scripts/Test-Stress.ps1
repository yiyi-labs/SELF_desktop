param([string]$Device='127.0.0.1:5555',[string]$Evidence='docs/evidence/overhaul',[string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$hdc=Join-Path $DevEcoHome 'sdk/default/openharmony/toolchains/hdc.exe'
New-Item -ItemType Directory -Force $Evidence | Out-Null
# Explicit real DeepSeek call on the public sample, then local undo/redo.
# Test-Native.ps1 builds and installs the test module first. No uninstall or data reset.
& $hdc -t $Device shell aa test -b com.self.mirror -m entry_test -s unittest OpenHarmonyTestRunner -s class SELFNativeStress -s timeout 720000 2>&1 | Tee-Object "$Evidence/stress-results.log"
$result=Get-Content "$Evidence/stress-results.log" -Raw
if($LASTEXITCODE -ne 0 -or $result -notmatch 'Tests run: 1, Failure: 0, Error: 0, Pass: 1, Ignore: 0'){throw 'Continuous native UI test did not pass; inspect actual report'}
