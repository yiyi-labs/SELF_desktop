param([string]$Device='127.0.0.1:5555',[string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$hdc=Join-Path $DevEcoHome 'sdk/default/openharmony/toolchains/hdc.exe'
# Test-Native.ps1 builds and installs the test module first. No uninstall or data reset.
& $hdc -t $Device shell aa test -b com.self.mirror -m entry_test -s unittest OpenHarmonyTestRunner -s class SELFNativeStress -s timeout 720000 2>&1 | Tee-Object docs/evidence/native-es3/stress-results.log
$result=Get-Content docs/evidence/native-es3/stress-results.log -Raw
if($LASTEXITCODE -ne 0 -or $result -notmatch 'Tests run: 1, Failure: 0, Error: 0, Pass: 1, Ignore: 0'){throw 'Continuous native UI test did not pass; inspect actual report'}
