<#
.SYNOPSIS
  SELF 电脑端一键启动（Windows API + WSL GPU 重建 worker + 手机 USB 连接）。
.DESCRIPTION
  双击 Start-SELF.cmd 即可（它以 ExecutionPolicy Bypass 调用本文件）。
  - 电脑服务未运行：拉起 worker+API，等待就绪。
  - 电脑服务已运行：不重复启动，只接管手机 USB 连接保持。
  - 手机 USB 连接（HDC 反向端口转发）每次运行都会建立并周期保活；
    手机重新插拔后，若本窗口已关闭，请再双击一次。
#>
param(
  [int]$Port = 8787
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
try { $Host.UI.RawUI.WindowTitle = 'SELF 重建服务' } catch {}

$hdcPath = 'C:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe'
function Connect-Device([int]$Port) {
  if (-not (Test-Path -LiteralPath $script:hdcPath)) { return $null }
  $devices = @(& $script:hdcPath list targets 2>$null | Where-Object { $_ -and $_ -notmatch 'Offline|\[Empty\]' })
  if ($devices.Count -ne 1) { return $null }
  $serial = $devices[0].Trim()
  if ($serial -notmatch '^[A-Za-z0-9._-]+$') { return $null }
  $mapping = "tcp:$Port tcp:$Port"
  $existing = @(& $script:hdcPath fport ls 2>$null | Where-Object { $_ -match "^$serial\s+$([regex]::Escape($mapping))" })
  if ($existing.Count -eq 0) {
    $result = & $script:hdcPath -t $serial rport "tcp:$Port" "tcp:$Port" 2>&1
    if ($LASTEXITCODE -ne 0 -or ($result -join ' ') -notmatch 'OK') { return $null }
  }
  return $serial
}

# ---- 第一步：电脑服务 ----
$probe = $null
try { $probe = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/reconstruction/health" -TimeoutSec 3 } catch {}
$alreadyRunning = ($probe -and $probe.status -eq 'ready')

if ($alreadyRunning) {
  Write-Host "电脑服务已在运行（engine=$($probe.engine)），不重复启动。" -ForegroundColor Green
} else {
  $server = Join-Path $projectRoot 'scripts\Start-ReconstructionServer.ps1'
  if (-not (Test-Path -LiteralPath $server)) { throw "找不到 $server" }
  Write-Host "正在启动 SELF 重建服务（Windows API $Port + WSL GPU worker）……" -ForegroundColor Cyan
  Write-Host "（worker 预检约 2~3 分钟）"
  Start-Process -FilePath 'powershell.exe' -ArgumentList @(
      '-NoProfile','-ExecutionPolicy','Bypass','-File', $server, '-Port', "$Port") `
      -PassThru -WindowStyle Minimized | Out-Null
  $ready = $false
  for ($i = 0; $i -lt 60 -and -not $ready; $i++) {
    Start-Sleep -Seconds 5
    try {
      $probe = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/reconstruction/health" -TimeoutSec 3
      if ($probe.status -eq 'ready' -and $probe.engine -eq 'ready') { $ready = $true }
    } catch { $probe = $null }
    if ($i % 4 -eq 0) { Write-Host "  等待服务就绪……（engine=$($probe.engine)）" }
  }
  if ($ready) { Write-Host "电脑服务就绪（engine=ready）。服务窗口已最小化，可在任务栏找到。" -ForegroundColor Green }
  else { Write-Host "服务未在预期时间内就绪，请截图反馈；进程保持运行以便诊断。" -ForegroundColor Yellow }
}

# ---- 第二步：手机 USB 连接（建立 + 保活） ----
Write-Host ""
Write-Host "正在连接手机（USB 反向端口转发 $Port）……" -ForegroundColor Cyan
$serial = Connect-Device $Port
if ($serial) { Write-Host "手机已连接：$serial -> 电脑 $Port，鸿蒙端现在可以直接使用。" -ForegroundColor Green }
else {
  Write-Host "尚未检测到唯一在线手机。请确认 USB 已插好、手机已允许 USB 调试。" -ForegroundColor Yellow
  Write-Host "保持本窗口开着，插入手机后会自动连接。"
}

Write-Host ""
Write-Host "==== 状态保持中（每 15 秒刷新；关闭本窗口只停止连接保持，不影响服务）====" -ForegroundColor Cyan
while ($true) {
  Start-Sleep -Seconds 15
  try { $probe = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/reconstruction/health" -TimeoutSec 3 } catch { $probe = $null }
  $serial = Connect-Device $Port
  $svc = if ($probe -and $probe.status -eq 'ready') { "服务就绪(engine=$($probe.engine))" } else { "服务不可达" }
  $dev = if ($serial) { "手机已连接($serial)" } else { "等待手机接入……" }
  Write-Host ("[{0}] {1} | {2}" -f (Get-Date -Format 'HH:mm:ss'), $svc, $dev)
}
