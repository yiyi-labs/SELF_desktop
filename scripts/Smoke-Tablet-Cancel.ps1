param([string]$Device = '6DP0226117002287', [switch]$KeepScreenshots)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$hdc = 'C:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe'
$jobsRoot = Join-Path $root 'backend\.data\reconstruction'
$line=Get-Content (Join-Path $root 'backend\.env') | Where-Object {$_ -match '^SELF_BACKEND_TOKEN='} | Select-Object -First 1
$token=$line.Substring($line.IndexOf('=')+1).Trim().Trim('"').Trim("'")
$headers=@{Authorization=('Bearer '+$token)}
$layoutLocal = Join-Path $env:TEMP 'self-cancel-layout.json'
$layoutRemote = '/data/local/tmp/self-cancel-layout.json'

function Read-Layout {
  & $hdc -t $Device shell uitest dumpLayout -p $layoutRemote -b com.self.mirror | Out-Null
  if($LASTEXITCODE -ne 0){throw 'SELF layout unavailable'}
  & $hdc -t $Device file recv $layoutRemote $layoutLocal | Out-Null
  if($LASTEXITCODE -ne 0){throw 'SELF layout transfer failed'}
  Get-Content -LiteralPath $layoutLocal -Raw
}
function Find-Node([string]$layout,[string]$id){
  $at=$layout.IndexOf(('"id":"'+$id+'"'),[StringComparison]::Ordinal)
  if($at -lt 0){return $null}
  $prefix=$layout.Substring([Math]::Max(0,$at-800),[Math]::Min(800,$at))
  $matches=[regex]::Matches($prefix,'"bounds":"\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
  if($matches.Count -eq 0){return $null}
  $matches[$matches.Count-1]
}
function Click-Id([string]$id){
  $bounds=$null
  $deadline=(Get-Date).AddSeconds(8)
  do {
    $bounds=Find-Node (Read-Layout) $id
    if($bounds){break}
    Start-Sleep -Milliseconds 200
  } while((Get-Date) -lt $deadline)
  if(-not $bounds){throw "Missing UI control: $id"}
  $x=[int](([int]$bounds.Groups[1].Value+[int]$bounds.Groups[3].Value)/2)
  $y=[int](([int]$bounds.Groups[2].Value+[int]$bounds.Groups[4].Value)/2)
  & $hdc -t $Device shell uitest uiInput click $x $y | Out-Null
  if($LASTEXITCODE -ne 0){throw "Tap failed: $id"}
}

$before=@(Get-ChildItem -LiteralPath $jobsRoot -Directory | Where-Object {$_.Name -match '^[a-f0-9]{32}$'} | ForEach-Object Name)
Click-Id 'open-settings'
Click-Id 'open-captures'
$layout=Read-Layout
$modelIds=@([regex]::Matches($layout,'"id":"(model-capture-[0-9]+\.mp4)"') | ForEach-Object {$_.Groups[1].Value})
if($modelIds.Count -eq 0){throw 'No existing private capture available for cancel test'}
$modelId=$modelIds[0]
Click-Id $modelId
$forming=$false
$jobId=''
$deadline=(Get-Date).AddSeconds(25)
do {
  Start-Sleep -Milliseconds 500
  $layout=Read-Layout
  $forming=[bool](Find-Node $layout 'cancel-reconstruction')
  $new=@(Get-ChildItem -LiteralPath $jobsRoot -Directory | Where-Object {$_.Name -match '^[a-f0-9]{32}$' -and $before -notcontains $_.Name} | ForEach-Object Name)
  if($new.Count -gt 0){$jobId=$new[0];break}
} while((Get-Date) -lt $deadline -and $forming)
if(-not $forming){throw 'Modeling transition did not appear'}
if($KeepScreenshots){
  for($frame=0;$frame -lt 3;$frame++){
    $remote="/data/local/tmp/self-forming-20260925-$frame.jpeg"
    & $hdc -t $Device shell snapshot_display -f $remote | Out-Null
    & $hdc -t $Device file recv $remote (Join-Path $root "artifacts\self-forming-20260925-$frame.jpeg") | Out-Null
    Start-Sleep -Milliseconds 350
  }
}
Click-Id 'cancel-reconstruction'
$idle=$false
$state='no_job_created'
$deadline=(Get-Date).AddSeconds(40)
do {
  Start-Sleep -Milliseconds 600
  $layout=Read-Layout
  $idle=[bool](Find-Node $layout 'begin-capture')
  if($jobId){
    $job=Invoke-RestMethod -Uri "http://127.0.0.1:8787/v1/reconstruction/jobs/$jobId" -Headers $headers
    $state=$job.state
  }
} while((Get-Date) -lt $deadline -and (!$idle -or ($jobId -and $state -ne 'cancelled')))
$result=@{device=$Device;checkedAt=(Get-Date).ToString('o');
          formingVisible=$forming;returnedHome=$idle;remoteJobCreated=[bool]$jobId;
          remoteState=$state;pcCaptureRemoved='not_checked_private_directory'}
$out=Join-Path $root 'docs\evidence\tablet-cancel-20260925.json'
$result | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $out -Encoding utf8
Write-Output ($result | ConvertTo-Json -Compress)
if(-not $idle -or ($jobId -and $state -ne 'cancelled')){throw 'Tablet cancellation smoke failed'}
if($jobId){
  Invoke-RestMethod -Method Delete -Uri "http://127.0.0.1:8787/v1/reconstruction/jobs/$jobId" -Headers $headers | Out-Null
}
