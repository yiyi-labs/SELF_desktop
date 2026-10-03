param([string]$Device='6DP0226117002287',[string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$output=Join-Path $root 'artifacts\galaxy-review'
$hdc=Join-Path $DevEcoHome 'sdk\default\openharmony\toolchains\hdc.exe'
New-Item -ItemType Directory -Force $output | Out-Null
function Layout {
  & $hdc -t $Device shell uitest dumpLayout -p /data/local/tmp/self-galaxy-journey.json -b com.self.mirror | Out-Null
  & $hdc -t $Device file recv /data/local/tmp/self-galaxy-journey.json (Join-Path $output 'native-current.json') | Out-Null
  return Get-Content -LiteralPath (Join-Path $output 'native-current.json') -Raw
}
function Click([string]$id) {
  $raw=Layout
  for($settle=0;$settle -lt 8 -and $raw.Contains('"id":"sky-transition-blocker"');$settle++){
    Start-Sleep -Milliseconds 400
    $raw=Layout
  }
  if($raw.Contains('"id":"sky-transition-blocker"')){throw 'Galaxy transition did not settle'}
  $at=$raw.IndexOf(('"id":"'+$id+'"'),[StringComparison]::Ordinal)
  if($at -lt 0){throw "Missing galaxy control: $id"}
  $prefix=$raw.Substring([Math]::Max(0,$at-800),[Math]::Min(800,$at))
  $boxes=[regex]::Matches($prefix,'"bounds":"\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
  if(!$boxes.Count){throw "Missing bounds: $id"}
  $box=$boxes[$boxes.Count-1]
  $x=[int](([int]$box.Groups[1].Value+[int]$box.Groups[3].Value)/2)
  $y=[int](([int]$box.Groups[2].Value+[int]$box.Groups[4].Value)/2)
  Write-Output "Galaxy action: $id ($x, $y)"
  & $hdc -t $Device shell uitest uiInput click $x $y | Out-Null
}
function Shot([string]$name){
  & $hdc -t $Device shell snapshot_display -f /data/local/tmp/self-galaxy-journey.jpeg | Out-Null
  $transfer=& $hdc -t $Device file recv /data/local/tmp/self-galaxy-journey.jpeg (Join-Path $output ($name+'.jpeg'))
  if(($transfer -join '') -notmatch 'FileTransfer finish'){throw "Screenshot transfer failed: $name"}
}
function Require([string]$id){if(!(Layout).Contains('"id":"'+$id+'"')){throw "Galaxy journey did not reach $id"}}
$initialPid=(& $hdc -t $Device shell pidof com.self.mirror).Trim()
if(!$initialPid){throw 'SELF is not running'}
Require 'open-star-sky-origin'
Click 'open-star-sky-origin'
Start-Sleep -Milliseconds 3200
Require 'galaxy-next'
Shot 'native-galaxy'
Click 'galaxy-next'
Start-Sleep -Milliseconds 1600
Shot 'native-next'
Click 'galaxy-list-toggle'
$list=Layout
$entry=[regex]::Match($list,'"id":"star-([a-f0-9]{32})"')
if(!$entry.Success){throw 'History list is empty'}
Click ('star-'+$entry.Groups[1].Value)
Start-Sleep -Milliseconds 6500
Require 'galaxy-caption'
$captionLayout=Layout
$openAt=$captionLayout.IndexOf('"id":"open-star-full"')
$selectedName=[regex]::Match($captionLayout.Substring($openAt,[Math]::Min(1200,$captionLayout.Length-$openAt)),'"text":"走近 · ([^"]+)"').Groups[1].Value
if($selectedName -and $selectedName -notmatch '^(未命名的星辰|我的星辰[\s\d]*|\d+)$'){
  $captionAt=$captionLayout.IndexOf('"id":"galaxy-caption"')
  $caption=$captionLayout.Substring($captionAt,[Math]::Min(1500,$captionLayout.Length-$captionAt))
  if(!$caption.Contains($selectedName.Substring(0,[Math]::Min(12,$selectedName.Length)))){throw 'Settled memory caption does not match its name'}
}
Shot 'native-caption'
Click 'open-star-full'
Click 'cancel-star-travel'
Start-Sleep -Milliseconds 2000
Require 'open-star-full'
Click 'open-star-full'
Shot 'native-approach'
$arrived=$false
for($attempt=0;$attempt -lt 12;$attempt++){
  Start-Sleep -Milliseconds 900
  if((Layout).Contains('"id":"return-origin"')){$arrived=$true;break}
}
if(!$arrived){throw 'Full memory did not arrive'}
Shot 'native-arrival'
Click 'open-star-sky'
Start-Sleep -Milliseconds 2500
Require 'open-star-full'
Click 'return-origin-sky'
Start-Sleep -Milliseconds 1900
Require 'open-star-sky-origin'
Shot 'native-return'
$finalPid=(& $hdc -t $Device shell pidof com.self.mirror).Trim()
if($initialPid -ne $finalPid){throw 'Process restarted during galaxy journey'}
@{passed=$true;device=$Device;processPreserved=$true;checks=@('enter','next','history index','settled memory caption','cancel travel','load full memory','return to stars','return home')} |
  ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $output 'native-report.json') -Encoding utf8
Write-Output 'Galaxy journey passed on the connected device.'
