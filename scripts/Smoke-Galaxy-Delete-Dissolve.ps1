# Requires an explicitly prepared disposable fixture. Never selects an original memory for deletion.
param([string]$Device='6DP0226117002287',[string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio',[string]$Fixture='87ac91df3b694196a2af8814a1ce8ed6')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$output=Join-Path $root 'artifacts\galaxy-review'
$hdc=Join-Path $DevEcoHome 'sdk\default\openharmony\toolchains\hdc.exe'
$private='/data/app/el2/100/base/com.self.mirror/haps/entry/files'
$models=$private+'/models'
$target=$models+'/'+$fixture
if($fixture -notmatch '^[a-f0-9]{32}$' -or !$target.StartsWith($models+'/')){throw 'Unsafe fixture path'}
function Nodes($node){if($node.attributes.id){$node.attributes};foreach($child in $node.children){Nodes $child}}
function Layout {
  & $hdc -t $Device shell uitest dumpLayout -p /data/local/tmp/self-delete-dissolve.json -b com.self.mirror | Out-Null
  & $hdc -t $Device file recv /data/local/tmp/self-delete-dissolve.json (Join-Path $output 'delete-dissolve-current.json') | Out-Null
  return @(Nodes (Get-Content -LiteralPath (Join-Path $output 'delete-dissolve-current.json') -Raw | ConvertFrom-Json))
}
function Find([string]$id){Layout | Where-Object {$_.id -eq $id} | Select-Object -First 1}
function Coordinates([string]$id){
  $node=Find $id;if(!$node){throw "Missing deletion control: $id"}
  $b=[regex]::Match($node.bounds,'\[(\d+),(\d+)\]\[(\d+),(\d+)\]')
  if(!$b.Success){throw "Missing bounds: $id"}
  return @([int](([int]$b.Groups[1].Value+[int]$b.Groups[3].Value)/2),[int](([int]$b.Groups[2].Value+[int]$b.Groups[4].Value)/2))
}
function Click([string]$id){$xy=Coordinates $id;& $hdc -t $Device shell uitest uiInput click $xy[0] $xy[1] | Out-Null}
function Shot([string]$name){
  & $hdc -t $Device shell snapshot_display -f ("/data/local/tmp/"+$name+'.jpeg') | Out-Null
  & $hdc -t $Device file recv ("/data/local/tmp/"+$name+'.jpeg') (Join-Path $output ($name+'.jpeg')) | Out-Null
}
if(Find 'return-origin-sky'){Click 'return-origin-sky';Start-Sleep -Milliseconds 1800}
$baseline=@(& $hdc -t $Device shell ls $models | ForEach-Object {$_.Trim()} | Where-Object {$_ -match '^[a-f0-9]{32}$' -and $_ -ne $fixture})
$known=@('portrait.gaussian.ply','portrait.view.json','portrait.preview.png','portrait.preview.gaussian.ply','portrait.scene-v3.gaussian.ply','portrait.glb')
$testFiles=@(& $hdc -t $Device shell ls $target | ForEach-Object {$_.Trim()})
foreach($name in $known){if($testFiles -notcontains $name){throw 'Disposable fixture files missing'}}
Click 'open-star-sky-origin';Start-Sleep -Milliseconds 2600
if(!(Find 'galaxy-list-close')){Click 'galaxy-list-toggle';Start-Sleep -Milliseconds 700}
if(!(Find ('delete-star-'+$fixture))){throw 'Disposable deletion fixture was not indexed'}
Click ('delete-star-'+$fixture);Start-Sleep -Milliseconds 500
$before=Layout
$lower=$before | Where-Object {$_.id -match '^star-[a-f0-9]{32}$' -and $_.id -ne ('star-'+$fixture)} | Select-Object -First 1
Shot 'native-dissolve-before'
$xy=Coordinates 'confirm-delete-star'
# Capture on-device while the click runs; host command latency must not skip the short animation.
$sequence="uitest uiInput click $($xy[0]) $($xy[1]) >/data/local/tmp/self-delete-click.log 2>&1 & sleep 0.2; snapshot_display -f /data/local/tmp/native-dissolve-moving-1.jpeg; sleep 0.2; snapshot_display -f /data/local/tmp/native-dissolve-moving-2.jpeg; sleep 0.2; snapshot_display -f /data/local/tmp/native-dissolve-moving-3.jpeg; wait"
& $hdc -t $Device shell "sh -c '$sequence'" | Out-Null
foreach($n in 1..3){
  & $hdc -t $Device file recv ("/data/local/tmp/native-dissolve-moving-$n.jpeg") (Join-Path $output ("native-dissolve-moving-$n.jpeg")) | Out-Null
}
Start-Sleep -Milliseconds 1200
$after=Layout
if($after.id -contains ('star-'+$fixture) -or $after.id -contains 'star-delete-confirmation'){throw 'Deleted fixture or confirmation remains visible'}
$remaining=@(& $hdc -t $Device shell ls $models | ForEach-Object {$_.Trim()} | Where-Object {$_ -match '^[a-f0-9]{32}$'})
if($remaining -contains $fixture){throw 'Disposable local model directory was not actually deleted'}
foreach($original in $baseline){if($remaining -notcontains $original){throw 'An original model directory changed'}}
if($lower){
  $settled=$after | Where-Object {$_.id -eq $lower.id} | Select-Object -First 1
  if(!$settled){throw 'A lower history row disappeared'}
  $topBefore=[int]([regex]::Match($lower.bounds,'\[\d+,(\d+)\]').Groups[1].Value)
  $topAfter=[int]([regex]::Match($settled.bounds,'\[\d+,(\d+)\]').Groups[1].Value)
  if($topAfter -ge $topBefore){throw 'Lower history rows did not rise after deletion'}
}
Shot 'native-dissolve-settled'
$metrics=@(& $hdc -t $Device shell cat ($private+'/galaxy-dust-test-stats.txt')) -join "`n"
$match=[regex]::Match($metrics,'frames=(\d+) mean=(\d+) max=(\d+)ms')
if(!$match.Success -or [int]$match.Groups[1].Value -lt 30){throw ('Dissolution did not render enough frames: '+$metrics)}
$metrics | Set-Content -LiteralPath (Join-Path $output 'native-raster-performance.log') -Encoding utf8
@{passed=$true;device=$Device;fixtureId=$fixture;localFilesDeleted=$known;originalMemoriesDeleted=0;
  animationFrames=[int]$match.Groups[1].Value;meanPaintMs=[int]$match.Groups[2].Value;maxPaintMs=[int]$match.Groups[3].Value;
  checks=@('whole row and confirmation dissolve','lower row rises after dissolution','six local assets and empty directory physically removed','original model directories preserved')} |
  ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $output 'native-dissolve-report.json') -Encoding utf8
Click 'galaxy-list-close';Start-Sleep -Milliseconds 500
Write-Output 'Disposable memory deleted locally; original memories preserved; lower history rose.'
