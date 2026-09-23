param(
    [Parameter(Mandatory=$true)][string]$Device,
    [string]$Evidence='artifacts/spatial-capabilities',
    [string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio'
)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$hdc=Join-Path $DevEcoHome 'sdk/default/openharmony/toolchains/hdc.exe'
$ndk=Join-Path $DevEcoHome 'sdk/default/openharmony/native'
$hms=Join-Path $DevEcoHome 'sdk/default/hms/native/sysroot/usr/include'
$clang=Join-Path $ndk 'llvm/bin/clang++.exe'
New-Item -ItemType Directory -Force $Evidence | Out-Null
$deviceInfo=[ordered]@{}
foreach($key in @('const.product.model','const.product.devicetype','const.product.cpu.abilist',
    'const.ohos.apiversion','const.ohos.releasetype','const.product.software.version')) {
    $value=(& $hdc -t $Device shell param get $key | Out-String).Trim()
    if($LASTEXITCODE -ne 0 -or $value -match '^\[Fail\]'){throw "Cannot query selected device: $key"}
    $deviceInfo[$key]=$value
}
# Do not persist the physical device serial number in repository evidence.
$deviceInfo | ConvertTo-Json | Set-Content -LiteralPath "$Evidence/device.json" -Encoding utf8
$abi=$deviceInfo['const.product.cpu.abilist']
$target=if($abi -match 'arm64'){'aarch64-linux-ohos'}elseif($abi -match 'x86_64'){'x86_64-linux-ohos'}else{throw "Unsupported probe ABI: $abi"}
$build=Join-Path $root "artifacts/spatial-capabilities-build/$target"
New-Item -ItemType Directory -Force $build | Out-Null
$exe=Join-Path $build 'spatial-capabilities'
& $clang "--target=$target" "--sysroot=$ndk/sysroot" '-std=c++17' '-O2' '-Wall' '-Wextra' '-Werror' '-static-libstdc++' "-I$hms" '-Ientry/src/main/cpp' 'entry/src/test/native/SpatialCapabilityProbe.cpp' '-ldl' '-ldeviceinfo_ndk.z' '-o' $exe 2>&1 | Tee-Object "$Evidence/build.log"
if($LASTEXITCODE -ne 0){throw 'Capability probe did not compile'}
$remote='/data/local/tmp/self-spatial-probe-'+[Guid]::NewGuid().ToString('N')
& $hdc -t $Device file send $exe $remote | Out-Null
if($LASTEXITCODE -ne 0){throw 'Could not transfer probe'}
try {
    & $hdc -t $Device shell chmod 700 $remote
    if($LASTEXITCODE -ne 0){throw 'Could not mark probe executable'}
    $output=& $hdc -t $Device shell $remote 2>&1
    $output | Set-Content -LiteralPath "$Evidence/runtime.log" -Encoding utf8
    if($LASTEXITCODE -ne 0){throw 'Device did not execute the probe; see runtime.log'}
    $line=@($output | Where-Object {$_ -like 'SELF_SPATIAL_CAPABILITY=*'})
    if($line.Count -ne 1){throw 'Probe did not produce one valid result; see runtime.log'}
    $report=$line[0].Substring('SELF_SPATIAL_CAPABILITY='.Length) | ConvertFrom-Json
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$Evidence/capabilities.json" -Encoding utf8
    $report | ConvertTo-Json -Depth 8
} finally {
    # Delete only this unique probe executable, never device application data.
    & $hdc -t $Device shell rm $remote | Out-Null
}
