param([string]$Device='6DP0226117002287',[string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$output=Join-Path $root 'artifacts\galaxy-review'
$hdc=Join-Path $DevEcoHome 'sdk\default\openharmony\toolchains\hdc.exe'
function Layout {
  & $hdc -t $Device shell uitest dumpLayout -p /data/local/tmp/self-galaxy-delete.json -b com.self.mirror | Out-Null
  & $hdc -t $Device file recv /data/local/tmp/self-galaxy-delete.json (Join-Path $output 'delete-current.json') | Out-Null
  return Get-Content -LiteralPath (Join-Path $output 'delete-current.json') -Raw | ConvertFrom-Json
}
function Nodes($node) {
  if($node.attributes.id){$node.attributes}
  foreach($child in $node.children){Nodes $child}
}
function Find([string]$id) {Nodes (Layout) | Where-Object {$_.id -eq $id} | Select-Object -First 1}
function Click([string]$id) {
  $node=Find $id
  if(!$node){throw "Missing galaxy control: $id"}
  $box=[regex]::Match($node.bounds,'\[(\d+),(\d+)\]\[(\d+),(\d+)\]')
  if(!$box.Success){throw "Missing bounds: $id"}
  $x=[int](([int]$box.Groups[1].Value+[int]$box.Groups[3].Value)/2)
  $y=[int](([int]$box.Groups[2].Value+[int]$box.Groups[4].Value)/2)
  & $hdc -t $Device shell uitest uiInput click $x $y | Out-Null
}
function Shot([string]$name) {
  & $hdc -t $Device shell snapshot_display -f /data/local/tmp/self-galaxy-delete.jpeg | Out-Null
  & $hdc -t $Device file recv /data/local/tmp/self-galaxy-delete.jpeg (Join-Path $output ($name+'.jpeg')) | Out-Null
}
$nodes=@(Nodes (Layout))
if($nodes.id -contains 'open-star-sky-origin'){Click 'open-star-sky-origin';Start-Sleep -Milliseconds 3000}
elseif($nodes.id -contains 'open-star-sky'){Click 'open-star-sky';Start-Sleep -Milliseconds 3000}
if(!(Find 'galaxy-list-close')){Click 'galaxy-list-toggle';Start-Sleep -Milliseconds 800}
$nodes=@(Nodes (Layout));$delete=$nodes | Where-Object {$_.id -match '^delete-star-[a-f0-9]{32}$'} | Select-Object -First 1
if(!$delete){throw 'Delete action is absent from the expanded history list'}
$before=@($nodes | Where-Object {$_.id -match '^star-[a-f0-9]{32}$'}).Count
Shot 'native-delete-list'
Click $delete.id;Start-Sleep -Milliseconds 700
if(!(Find 'confirm-delete-star') -or !(Find 'cancel-delete-star')){throw 'Inline delete confirmation did not open'}
Shot 'native-delete-confirm'
# Do not delete a user's real memory during smoke verification.
Click 'cancel-delete-star';Start-Sleep -Milliseconds 500
$nodes=@(Nodes (Layout))
if($nodes.id -contains 'confirm-delete-star'){throw 'Keep did not dismiss the confirmation'}
$after=@($nodes | Where-Object {$_.id -match '^star-[a-f0-9]{32}$'}).Count
if($before -ne $after -or !($nodes.id -contains $delete.id)){throw 'Keep changed the history list'}
Shot 'native-delete-kept'
Click 'galaxy-list-close';Start-Sleep -Milliseconds 600
$nodes=@(Nodes (Layout))
if(@($nodes | Where-Object {$_.id -match '^delete-star-|^confirm-delete-star$|^cancel-delete-star$'}).Count){throw 'A delete action remains on the stars canvas'}
@{passed=$true;device=$Device;realMemoriesDeleted=0;checks=@('delete icons in expanded list','inline named confirmation','keep preserves history','delete controls hidden when list closes')} |
  ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $output 'native-delete-report.json') -Encoding utf8
Write-Output 'Delete entry and cancellation passed on the connected tablet.'
