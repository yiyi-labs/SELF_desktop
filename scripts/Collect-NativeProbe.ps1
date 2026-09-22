param([Parameter(Mandatory=$true)][string]$Device,[Parameter(Mandatory=$true)][string]$Evidence,
      [string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$hdc=Join-Path $DevEcoHome 'sdk/default/openharmony/toolchains/hdc.exe'
New-Item -ItemType Directory -Force $Evidence | Out-Null
$lines=& $hdc -t $Device shell hilog -x -T JSAPP
$pidLine=$lines | Select-String 'SELF_FEATHER_PROBE' | Select-Object -Last 1
if(!$pidLine){throw 'Run Start-NativeProbe.ps1 with the current build first'}
# Android/host/browser outputs cannot satisfy this collector: only hdc app files.
$lines | Select-String 'SELF_ES_|SELF_EXIF|SELF_RECON_SUPPORT|SELF_FEATHER|SELF_V2|SELF_NETWORKKIT|SELF_PRODUCT_PROBE|PRODUCT_TEXTURE' | ForEach-Object {$_.Line} | Set-Content "$Evidence/probe.log" -Encoding UTF8
$names=@('native-probe.png','native-face.png','native-edit.png','native-repeat.png','native-side.png',
 'protected-blocked.png','protected-exception.png','protected-later.png','snapshot-clean.png','snapshot-marked.png',
 'after-invalid-glb.png','native-photo.png','native-selection.mask','photo-selection.mask','odd-stride.png',
 'v2-edit.png','v2-repeat.png','v2-blocked.png','legacy-photo-base.png','legacy-photo-layers.png')+(1..8 | ForEach-Object {"orientation-$_.png"})
$names+='face-after-products.png'
foreach($style in @('red-jar','black-jar','white-pump','black-tube','white-set','white-ampoule')){foreach($state in @('closed','moving','open','side')){$names+="product-$style-$state.png"}}
foreach($name in $names){
 & $hdc -t $Device file recv "/data/app/el2/100/base/com.self.mirror/haps/entry/files/$name" "$Evidence/$name" | Out-Null
 if($LASTEXITCODE -ne 0 -or !(Test-Path "$Evidence/$name")){throw "Could not collect $name"}
}
& backend/.venv/Scripts/python.exe scripts/check-native-pixels.py $Evidence
if($LASTEXITCODE -ne 0){throw 'Native pixel validation failed'}
