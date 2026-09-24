param(
  [string]$Device = '6DP0226117002287',
  [string]$DevEcoHome = 'C:\Program Files\Huawei\DevEco Studio'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$hdc = Join-Path $DevEcoHome 'sdk\default\openharmony\toolchains\hdc.exe'
$tempLayout = Join-Path $env:TEMP 'self-ui-smoke-layout.json'
$deviceLayout = '/data/local/tmp/self-ui-smoke-layout.json'
function Read-Layout {
  & $hdc -t $Device shell uitest dumpLayout -p $deviceLayout -b com.self.mirror | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect SELF layout' }
  & $hdc -t $Device file recv $deviceLayout $tempLayout | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Unable to transfer SELF layout' }
  # On some commercial tablet builds, uitest writes UI text in a legacy
  # encoding while retaining ASCII ids/bounds. Match only those stable fields.
  return Get-Content -LiteralPath $tempLayout -Raw
}
function Find-Node([string]$layout, [string]$id) {
  $at = $layout.IndexOf(('"id":"' + $id + '"'), [StringComparison]::Ordinal)
  if ($at -lt 0) { return $null }
  $prefix = $layout.Substring([Math]::Max(0,$at - 800), [Math]::Min(800,$at))
  $bounds = [regex]::Matches($prefix, '"bounds":"\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
  if ($bounds.Count -eq 0) { return $null }
  return $bounds[$bounds.Count - 1]
}
function Click-Id([string]$id) {
  $node = Find-Node (Read-Layout) $id
  if (-not $node) { throw "Missing UI control: $id" }
  $x = [int](([int]$node.Groups[1].Value + [int]$node.Groups[3].Value) / 2)
  $y = [int](([int]$node.Groups[2].Value + [int]$node.Groups[4].Value) / 2)
  & $hdc -t $Device shell uitest uiInput click $x $y | Out-Null
  Start-Sleep -Milliseconds 650
}
function Back {
  & $hdc -t $Device shell uitest uiInput keyEvent Back | Out-Null
  Start-Sleep -Milliseconds 450
}
$initialPid = (& $hdc -t $Device shell pidof com.self.mirror).Trim()
if (-not $initialPid) { throw 'SELF is not running' }
$results = @()
foreach ($case in @(
  @{ control='open-settings'; expected='detail-panel' },
  @{ control='open-ambience'; expected='detail-panel' },
  @{ control='home-note'; expected='detail-panel' },
  @{ control='home-works'; expected='detail-panel' },
  @{ control='begin-capture'; expected='camera-fullscreen' }
)) {
  Click-Id $case.control
  $layout = Read-Layout
  $pidNow = (& $hdc -t $Device shell pidof com.self.mirror).Trim()
  $visible = [bool](Find-Node $layout $case.expected)
  $results += @{ control=$case.control; expected=$case.expected; visible=$visible; processPreserved=($pidNow -eq $initialPid) }
  if (-not $visible -or $pidNow -ne $initialPid) { throw "UI regression: $($case.control)" }
  Back
}
$result = @{ device=$Device; initialPid=$initialPid; checkedAt=(Get-Date).ToString('o'); steps=$results }
$out = Join-Path $root 'docs\evidence\home-ui-smoke-20260924.json'
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $out -Encoding utf8
Write-Output "SELF home UI smoke passed: $out"
