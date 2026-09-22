param([string]$Device,[string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$node=Join-Path $DevEcoHome 'tools\node\node.exe'
$hdc=Join-Path $DevEcoHome 'sdk\default\openharmony\toolchains\hdc.exe'
$hvigor=Join-Path $DevEcoHome 'tools\hvigor\bin\hvigorw.js'
$env:DEVECO_SDK_HOME=Join-Path $DevEcoHome 'sdk'
$env:JAVA_HOME=Join-Path $DevEcoHome 'jbr'
$env:OHOS_BASE_SDK_HOME=Join-Path $DevEcoHome 'sdk\default\openharmony'
$savedComSpec=$env:ComSpec
$env:ComSpec=Join-Path (Get-Location) 'artifacts/self-build-cmd.exe'
try {
& $node $hvigor --mode module -p product=default -p module=entry@ohosTest -p buildMode=debug assembleHap --no-daemon 2>&1 | Tee-Object -FilePath docs/evidence/native-es3/hypium-build.log
if($LASTEXITCODE -ne 0){throw 'Native test build failed'}
} finally { $env:ComSpec=$savedComSpec }
$targets=@((& $hdc list targets) | Where-Object {$_ -and $_ -ne '[Empty]'} | ForEach-Object {$_.Trim()})
if(!$Device){if($targets.Count -ne 1){throw 'Specify -Device'};$Device=$targets[0]}
if($Device -notin $targets){throw 'Selected device is not connected'}
& $hdc -t $Device install -r entry/build/default/outputs/ohosTest/entry-ohosTest-unsigned.hap
if($LASTEXITCODE -ne 0){throw 'Test package install failed'}
& $hdc -t $Device shell aa test -b com.self.mirror -m entry_test -s unittest OpenHarmonyTestRunner -s notClass SELFNativeStress -s timeout 60000 2>&1 | Tee-Object -FilePath docs/evidence/native-es3/hypium-results.log
if($LASTEXITCODE -ne 0){throw 'Native test command failed'}
$log=Get-Content -LiteralPath docs/evidence/native-es3/hypium-results.log -Raw
if($log -notmatch 'Tests run: 12, Failure: 0, Error: 0, Pass: 12, Ignore: 0' -or $log -notmatch 'TestFinished-ResultCode: 0'){throw 'Inspect hypium-results.log; success must be confirmed from the framework report'}


