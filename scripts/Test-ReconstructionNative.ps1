param([string]$Device='127.0.0.1:5555', [string]$Evidence='docs/evidence/reconstruction-contract',
      [string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$ndk=Join-Path $DevEcoHome 'sdk/default/openharmony/native'
$hms=Join-Path $DevEcoHome 'sdk/default/hms/native/sysroot/usr/include'
$clang=Join-Path $ndk 'llvm/bin/clang++.exe'
$hdc=Join-Path $DevEcoHome 'sdk/default/openharmony/toolchains/hdc.exe'
New-Item -ItemType Directory -Force $Evidence | Out-Null
$type=(& $hdc -t $Device shell param get const.product.devicetype | Out-String).Trim()
if($type -ne 'tablet'){throw 'This verification is configured for the tablet requested by the user'}
$abi=(& $hdc -t $Device shell param get const.product.cpu.abilist | Out-String).Trim()
$target=if($abi -match 'x86_64'){'x86_64-linux-ohos'}elseif($abi -match 'arm64'){'aarch64-linux-ohos'}else{throw "Unsupported test ABI: $abi"}
$binaryRoot=Join-Path $root 'artifacts/reconstruction-contract'
New-Item -ItemType Directory -Force $binaryRoot | Out-Null
$exe=Join-Path $binaryRoot 'self-reconstruction-tests'
& $clang "--target=$target" "--sysroot=$ndk/sysroot" '-std=c++17' '-O2' '-Wall' '-Wextra' '-Werror=return-type' '-static-libstdc++' "-I$hms" '-Ientry/src/main/cpp' 'entry/src/test/native/SpatialReconstructionTest.cpp' 'entry/src/main/cpp/SpatialReconstruction.cpp' '-ldl' '-o' $exe 2>&1 | Tee-Object "$Evidence/build.log"
if($LASTEXITCODE -ne 0){throw 'Native reconstruction test build failed'}
$run='self-recon-'+[Guid]::NewGuid().ToString('N')
$remote="/data/local/tmp/$run"
& $hdc -t $Device shell mkdir $remote
if($LASTEXITCODE -ne 0){throw 'Device test directory creation failed'}
& $hdc -t $Device file send $exe "$remote/tests" | Out-Null
if($LASTEXITCODE -ne 0){throw 'Device test binary transfer failed'}
& $hdc -t $Device shell chmod 700 "$remote/tests"
& $hdc -t $Device shell "$remote/tests" $remote 2>&1 | Tee-Object "$Evidence/results.json"
$result=Get-Content -LiteralPath "$Evidence/results.json" -Raw | ConvertFrom-Json
if($result.failed -ne 0 -or $result.passed -ne 23){throw 'Reconstruction contract tests failed or incomplete'}
@{device=$Device;deviceType=$type;abi=$abi;remoteEvidence=$remote;personalReconstructionValidated=$false} | ConvertTo-Json | Set-Content -LiteralPath "$Evidence/device.json" -Encoding UTF8
Write-Output '23 native contract tests passed; see runtimeProbe separately. No personal capture was used.'
