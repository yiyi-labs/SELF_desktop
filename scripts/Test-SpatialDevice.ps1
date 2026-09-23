param(
    [Parameter(Mandatory=$true)][string]$Device,
    [string]$Evidence=('artifacts/spatial-device-'+(Get-Date -Format 'yyyyMMdd-HHmmss')),
    [switch]$Build,
    [string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio'
)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$hdc=Join-Path $DevEcoHome 'sdk/default/openharmony/toolchains/hdc.exe'
New-Item -ItemType Directory -Force $Evidence | Out-Null
if($Build){
    & (Join-Path $PSScriptRoot 'Test-Native.ps1') -Device $Device -BuildOnly -Evidence "$Evidence/build" -DevEcoHome $DevEcoHome
}
$targets=@((& $hdc list targets) | ForEach-Object {$_.Trim()})
if($Device -notin $targets){throw 'Selected device is not connected'}
$deviceInfo=[ordered]@{}
foreach($key in @('const.product.model','const.product.devicetype','const.product.cpu.abilist',
    'const.ohos.apiversion','const.ohos.releasetype','const.product.software.version')){
    $value=(& $hdc -t $Device shell param get $key | Out-String).Trim()
    if($LASTEXITCODE -ne 0 -or $value -match '^\[Fail\]'){throw "Cannot query selected device: $key"}
    $deviceInfo[$key]=$value
}
# Never put the physical serial, signing material or user photos in evidence.
$deviceInfo | ConvertTo-Json | Set-Content -LiteralPath "$Evidence/device.json" -Encoding utf8
$packages=@{
    app='entry/build/default/outputs/default/entry-default-signed.hap'
    test='entry/build/default/outputs/ohosTest/entry-ohosTest-signed.hap'
}
foreach($name in @('app','test')){
    $package=$packages[$name]
    if(!(Test-Path -LiteralPath $package)){throw "Missing signed $name HAP; configure DevEco signing and run with -Build"}
    $result=& $hdc -t $Device install -r $package 2>&1
    $result | Set-Content -LiteralPath "$Evidence/$name-install.log" -Encoding utf8
    if(($result -join "`n") -notmatch 'install bundle successfully'){throw "Signed $name installation failed; see evidence"}
}
$remote='/data/app/el2/100/base/com.self.mirror/haps/entry_test/files/'
function Receive-ProbeFile([string]$name){
    $destination=Join-Path $Evidence $name
    $result=& $hdc -t $Device file recv ($remote+$name) $destination 2>&1
    if(($result -join "`n") -notmatch 'FileTransfer finish'){throw "Could not retrieve $name"}
}
try{
    & $hdc -t $Device shell aa force-stop com.self.mirror | Out-Null
    $deviceStart=(& $hdc -t $Device shell date +%s | Out-String).Trim()
    if($deviceStart -notmatch '^\d{10,}$'){throw 'Cannot read device time to reject stale probe evidence'}
    $result=& $hdc -t $Device shell aa test -b com.self.mirror -m entry_test -s unittest OpenHarmonyTestRunner -s class SELFNativeSpatialProbe -s timeout 90000 2>&1
    $result | Set-Content -LiteralPath "$Evidence/results.log" -Encoding utf8
    Receive-ProbeFile 'gs-sdk-probe.json'
    $log=$result -join "`n"
    $frameworkPassed=$log -match 'Tests run: 1, Failure: 0, Error: 0, Pass: 1, Ignore: 0'
    $report=Get-Content -LiteralPath "$Evidence/gs-sdk-probe.json" -Raw | ConvertFrom-Json
    # HDC can exit 0 on crashes. A failed test may still contain useful fresh
    # stage evidence; do not collect images from a previous run after a crash.
    $deviceEnd=(& $hdc -t $Device shell date +%s | Out-String).Trim()
    $fresh=$deviceEnd -match '^\d{10,}$' -and $report.recordedAt -ge ([long]$deviceStart*1000) -and $report.recordedAt -lt (([long]$deviceEnd+1)*1000)
    [ordered]@{reportFresh=$fresh;frameworkPassed=$frameworkPassed} | ConvertTo-Json |
        Set-Content -LiteralPath "$Evidence/freshness.json" -Encoding utf8
    if(!$fresh){throw 'Retrieved probe report is stale; do not count it as a result of this run'}
    if($report.snapshotBefore){Receive-ProbeFile 'gs-before.png'}
    if($report.snapshotAfter){Receive-ProbeFile 'gs-after.png'}
    if($report.snapshotControl){Receive-ProbeFile 'gs-control.png'}
    if($report.saveCall){Receive-ProbeFile 'gs-probe-edited.ply'}
    $reconstruction=$report.reconstruction | ConvertFrom-Json
    [ordered]@{
        diagnosticCompleted=$frameworkPassed
        phase=$report.phase
        reconstructionSupportStatus=$reconstruction.status
        gsNodeLoaded=$report.nodeLoaded
        exportCallSucceeded=$report.saveCall
        personalReconstructionValidated=$report.personalReconstructionValidated
        note='Synthetic SDK probe only. Pixel, occlusion and persistent-surface verification are separate gates.'
    } | ConvertTo-Json | Set-Content -LiteralPath "$Evidence/summary.json" -Encoding utf8
    Get-Content -LiteralPath "$Evidence/summary.json"
    if(!$frameworkPassed){throw 'Probe did not pass. Fresh partial evidence was saved; inspect results.log and summary.json.'}
}finally{
    # Preserve application data and return to the normal entry; do not uninstall.
    # A timed-out native Promise can outlive its test page; release the probe process.
    & $hdc -t $Device shell aa force-stop com.self.mirror | Out-Null
    & $hdc -t $Device shell aa start -a EntryAbility -b com.self.mirror 2>&1 |
        Set-Content -LiteralPath "$Evidence/restore-app.log" -Encoding utf8
}
