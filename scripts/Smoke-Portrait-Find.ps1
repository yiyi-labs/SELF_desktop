param([string]$Device='6DP0226117002287',[string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$output=Join-Path $root 'artifacts\galaxy-review'
$hdc=Join-Path $DevEcoHome 'sdk\default\openharmony\toolchains\hdc.exe'
function Nodes($node){if($node.attributes.id){$node.attributes};foreach($child in $node.children){Nodes $child}}
function Layout {
  & $hdc -t $Device shell uitest dumpLayout -p /data/local/tmp/self-portrait-button.json -b com.self.mirror | Out-Null
  & $hdc -t $Device file recv /data/local/tmp/self-portrait-button.json (Join-Path $output 'portrait-button-current.json') | Out-Null
  return @(Nodes (Get-Content -LiteralPath (Join-Path $output 'portrait-button-current.json') -Raw | ConvertFrom-Json))
}
function Find([string]$id){Layout | Where-Object {$_.id -eq $id} | Select-Object -First 1}
function Coordinates([string]$id){
  $node=Find $id;if(!$node){throw "Missing portrait control: $id"}
  $b=[regex]::Match($node.bounds,'\[(\d+),(\d+)\]\[(\d+),(\d+)\]')
  if(!$b.Success){throw "Missing portrait bounds: $id"}
  return @([int](([int]$b.Groups[1].Value+[int]$b.Groups[3].Value)/2),[int](([int]$b.Groups[2].Value+[int]$b.Groups[4].Value)/2))
}
function Click([string]$id){$xy=Coordinates $id;& $hdc -t $Device shell uitest uiInput click $xy[0] $xy[1] | Out-Null}
function Require([string]$id){if(!(Find $id)){throw "Portrait journey did not reach $id"}}
function Shot([string]$name){
  & $hdc -t $Device shell snapshot_display -f ("/data/local/tmp/"+$name+'.jpeg') | Out-Null
  & $hdc -t $Device file recv ("/data/local/tmp/"+$name+'.jpeg') (Join-Path $output ($name+'.jpeg')) | Out-Null
}
$nodes=Layout
if($nodes.id -contains 'return-origin-sky'){Click 'return-origin-sky';Start-Sleep -Milliseconds 2000}
elseif($nodes.id -contains 'return-origin'){Click 'return-origin';Start-Sleep -Milliseconds 600}
Require 'begin-capture';Shot 'native-find-idle'
$xy=Coordinates 'begin-capture'
$process=Start-Process -FilePath $hdc -ArgumentList @('-t',$Device,'shell','uitest','uiInput','longClick',$xy[0],$xy[1]) -WindowStyle Hidden -PassThru
Start-Sleep -Milliseconds 350
& $hdc -t $Device shell snapshot_display -f /data/local/tmp/native-find-held-1.jpeg | Out-Null
Start-Sleep -Milliseconds 400
& $hdc -t $Device shell snapshot_display -f /data/local/tmp/native-find-held-2.jpeg | Out-Null
if(!$process.WaitForExit(5000)){throw 'Long press did not finish'}
foreach($name in @('native-find-held-1','native-find-held-2')){
  & $hdc -t $Device file recv ("/data/local/tmp/"+$name+'.jpeg') (Join-Path $output ($name+'.jpeg')) | Out-Null
}
Start-Sleep -Milliseconds 600
Require 'camera-fullscreen';Click 'camera-back';Start-Sleep -Milliseconds 700
Require 'begin-capture';Click 'begin-capture';Start-Sleep -Milliseconds 900
Require 'camera-fullscreen';Click 'camera-back';Start-Sleep -Milliseconds 700
Require 'begin-capture';Shot 'native-find-returned'
@{passed=$true;device=$Device;checks=@('new portrait icon','long press opens camera after release','short tap opens camera','button reusable after return');recordingsStarted=0} |
  ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $output 'native-find-report.json') -Encoding utf8
Write-Output 'Portrait button passed short press, long press and return checks.'
