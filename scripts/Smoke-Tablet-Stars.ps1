param(
  [string]$Device = '6DP0226117002287',
  [string]$DevEcoHome = 'C:\Program Files\Huawei\DevEco Studio'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$hdc = Join-Path $DevEcoHome 'sdk\default\openharmony\toolchains\hdc.exe'
$deviceLayout = '/data/local/tmp/self-star-layout.json'
$hostLayout = Join-Path $env:TEMP 'self-star-layout.json'
function Layout {
  & $hdc -t $Device shell uitest dumpLayout -p $deviceLayout -b com.self.mirror | Out-Null
  & $hdc -t $Device file recv $deviceLayout $hostLayout | Out-Null
  return Get-Content -LiteralPath $hostLayout -Raw
}
function Click([string]$id) {
  $raw = Layout
  $at = $raw.IndexOf(('"id":"' + $id + '"'), [StringComparison]::Ordinal)
  if ($at -lt 0) { throw "Control missing: $id" }
  $prefix = $raw.Substring([Math]::Max(0,$at-800),[Math]::Min(800,$at))
  $bounds = [regex]::Matches($prefix,'"bounds":"\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
  if ($bounds.Count -eq 0) { throw "Bounds missing: $id" }
  $node = $bounds[$bounds.Count-1]
  $x = [int](([int]$node.Groups[1].Value+[int]$node.Groups[3].Value)/2)
  $y = [int](([int]$node.Groups[2].Value+[int]$node.Groups[4].Value)/2)
  & $hdc -t $Device shell uitest uiInput click $x $y | Out-Null
  Start-Sleep -Milliseconds 800
}
$pidBefore = (& $hdc -t $Device shell pidof com.self.mirror).Trim()
if (-not $pidBefore) { throw 'SELF is not running' }
if ((Layout).Contains('"id":"return-origin-sky"')) { Click 'return-origin-sky' }
Click 'open-star-sky-origin'
$sky = Layout
$dialVisible = $sky.Contains('"id":"galaxy-next"') -and $sky.Contains('"id":"galaxy-list-toggle"')
if (-not $dialVisible) { throw 'Galaxy navigation did not enter the star sky' }
Click 'galaxy-next'
Click 'galaxy-list-toggle'
$expanded = Layout
$star = [regex]::Match($expanded,'"id":"star-([a-f0-9]{32})"')
if (-not $star.Success) { throw 'Expanded galaxy index did not contain historical models' }
$jobId = $star.Groups[1].Value
Click ('star-'+$jobId)
Start-Sleep -Seconds 4
$previewLogs = (& $hdc -t $Device shell hilog -x | Out-String)
$previewViewerReady = $previewLogs -match 'SELF_GALAXY_UNIVERSE_READY'
$previewPath = "/data/app/el2/100/base/com.self.mirror/haps/entry/files/models/$jobId/portrait.scene-v3.gaussian.ply"
$previewStat = (& $hdc -t $Device shell "ls -l $previewPath" | Out-String)
$previewSaved = $previewStat -match 'portrait\.scene-v3\.gaussian\.ply'
if (-not $previewSaved) { throw 'Whole-scene 3D preview was not downloaded to app-private storage' }
Click 'open-star-full'
Start-Sleep -Seconds 3
$full = Layout
$fullControls = $full.Contains('"id":"return-origin"') -and $full.Contains('"id":"open-star-sky"')
if (-not $fullControls) { throw 'Full model did not retain navigation controls' }
Click 'return-origin'
$origin = Layout
if (-not $origin.Contains('"id":"open-star-sky-origin"')) { throw 'Could not return to particle origin' }
Click 'open-settings'
$settings = Layout
$penToggle = $settings.Contains('"id":"stylus-hints-toggle"')
if (-not $penToggle) { throw 'Pen and touch preference missing' }
Click 'replay-intro'
$intro = Layout
$introVisible = $intro.Contains('"id":"skip-intro"')
if (-not $introVisible) { throw 'First-run story replay did not open' }
Click 'skip-intro'
$pidAfter = (& $hdc -t $Device shell pidof com.self.mirror).Trim()
$result = @{
  device = $Device
  checkedAt = (Get-Date).ToString('o')
  historicalJobId = $jobId
  previewDownloaded = $previewSaved
  dialVisible = $dialVisible
  expandedHistory = $star.Success
  previewViewerReadyLog = $previewViewerReady
  fullModelControls = $fullControls
  originRestored = $origin.Contains('"id":"open-star-sky-origin"')
  penPreferenceVisible = $penToggle
  introReplayVisible = $introVisible
  processPreserved = ($pidBefore -eq $pidAfter)
}
$path = Join-Path $root ('docs\evidence\tablet-stars-' + (Get-Date -Format 'yyyyMMdd') + '.json')
$result | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $path -Encoding utf8
if (-not $result.processPreserved) { throw 'SELF process restarted during star journey' }
Write-Output "SELF star journey smoke recorded: $path"
