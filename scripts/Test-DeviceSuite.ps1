param([Parameter(Mandatory=$true)][string]$Device,
      [Parameter(Mandatory=$true)][ValidateSet('SELFNativePolicy','SELFNativeApi26UI','SELFNativeExperience','SELFNativeModelLive','SELFNativeProductUI','SELFNativeCamera','SELFNativeCameraPipeline','SELFNativeSpatialProbe')][string]$Suite,
      [Parameter(Mandatory=$true)][int]$ExpectedTests,
      [Parameter(Mandatory=$true)][string]$Evidence,
      [string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
New-Item -ItemType Directory -Force $Evidence | Out-Null
$hdc=Join-Path $DevEcoHome 'sdk/default/openharmony/toolchains/hdc.exe'
# Build both artifacts with Test-Native.ps1 -BuildOnly before invoking.
# Explicit SELFNativeModelLive / SELFNativeProductUI make a paid call using the public sample.
& (Join-Path $PSScriptRoot 'Install-Emulator.ps1') -Device $Device -DevEcoHome $DevEcoHome
& $hdc -t $Device install -r entry/build/default/outputs/ohosTest/entry-ohosTest-unsigned.hap
if($LASTEXITCODE -ne 0){throw 'Test package install failed'}
& $hdc -t $Device shell aa force-stop com.self.mirror
& $hdc -t $Device shell aa test -b com.self.mirror -m entry_test -s unittest OpenHarmonyTestRunner -s class $Suite -s timeout 90000 2>&1 | Tee-Object "$Evidence/results.log"
$log=Get-Content "$Evidence/results.log" -Raw
if($LASTEXITCODE -ne 0 -or $log -notmatch "Tests run: $ExpectedTests, Failure: 0, Error: 0, Pass: $ExpectedTests, Ignore: 0"){
 throw "Suite failed or did not finish; inspect $Evidence/results.log"
}
if($Suite -eq 'SELFNativeProductUI'){
 foreach($name in @('product-ui-bounds.json','product-ui-closed.png','product-ui-open.png','product-ui-facts.png','face-after-product-ui.png')){
  & $hdc -t $Device file recv "/data/app/el2/100/base/com.self.mirror/haps/entry/files/$name" "$Evidence/$name" | Out-Null
  if($LASTEXITCODE -ne 0){throw "Could not collect product UI evidence: $name"}
 }
 & backend/.venv/Scripts/python.exe scripts/check-product-ui.py $Evidence
 if($LASTEXITCODE -ne 0){throw 'Product UI visual validation failed'}
}
