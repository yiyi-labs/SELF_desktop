param([string]$Device='127.0.0.1:5555',
      [string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio',
      [string]$Evidence='docs/evidence/interaction-camera/camera-environment.json')
$ErrorActionPreference='Stop'
$emulatorProcess=Get-CimInstance Win32_Process -Filter "name='Emulator.exe'" | Where-Object {$_.CommandLine -like '*MatePad Pro 13*'}
if(!$emulatorProcess){throw 'Start the existing MatePad Pro 13 emulator first. This script never resets user data.'}
$imageRoot=Join-Path $env:LOCALAPPDATA 'Huawei/Sdk/system-image/HarmonyOS-7.0.0/tablet_x86'
$featureText=Get-Content -LiteralPath (Join-Path $imageRoot 'features.ini') -Raw
$hostCameras=@(Get-CimInstance Win32_PnPEntity | Where-Object {$_.PNPClass -in @('Camera','Image')} | Select-Object Name,Status)
$consent=Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam' -ErrorAction SilentlyContinue
$hdc=Join-Path $DevEcoHome 'sdk/default/openharmony/toolchains/hdc.exe'
$deviceType=((& $hdc -t $Device shell param get const.product.devicetype) -join '').Trim()
if($deviceType -ne 'tablet'){throw 'The selected hdc target is not a tablet; select the currently open tablet explicitly.'}
$result=[ordered]@{checkedAt=(Get-Date -Format o);device=$Device;deviceType=$deviceType;instance='MatePad Pro 13';
  cameraFeature=($featureText -match 'camera.feature=on');frontBack=($featureText -match 'camera.front.back.enable=on');
  windowsCameraConsent=$consent.Value;hostCameras=$hostCameras;
  sdkCameraDeclaration=Test-Path (Join-Path $DevEcoHome 'sdk/default/openharmony/ets/api/@ohos.multimedia.camera.d.ts');
  configurationChanged=$false;reason='Existing official image already enables host cameras; application Camera Kit preview probe supplies runtime evidence.'}
New-Item -ItemType Directory -Force (Split-Path $Evidence) | Out-Null
$result | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 $Evidence
$result | ConvertTo-Json -Depth 5
if(!$result.cameraFeature -or !$result.frontBack){throw 'Camera feature is disabled in this image. Do not fabricate camera data.'}
