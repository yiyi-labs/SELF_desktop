<#
.SYNOPSIS
  SELF 电脑端一键启动（Windows API + WSL GPU 重建 worker）。
.DESCRIPTION
  双击 Start-SELF.cmd 即可（它以 ExecutionPolicy Bypass 调用本文件）；
  也可在终端运行：powershell -ExecutionPolicy Bypass -File Start-SELF.ps1
  已经在运行时不会重复创建 worker，直接提示后退出。
#>
param(
  [int]$Port = 8787
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$title = if ($Host.UI.RawUI) { $Host.UI.RawUI.WindowTitle } else { $null }
try { $Host.UI.RawUI.WindowTitle = 'SELF 重建服务' } catch {}

# 已在运行则不重复启动（避免叠多个 worker/API）。
$probe = $null
try {
  $probe = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/reconstruction/health" -TimeoutSec 3
} catch {}
if ($probe -and $probe.status -eq 'ready') {
  Write-Host "SELF 服务已经在运行（engine=$($probe.engine)），无需重复启动。" -ForegroundColor Green
  Write-Host "停止服务：关闭上一次启动它的窗口（或结束其 python/uvicorn 进程）。"
  exit 0
}

$server = Join-Path $projectRoot 'scripts\Start-ReconstructionServer.ps1'
if (-not (Test-Path -LiteralPath $server)) { throw "找不到 $server" }
Write-Host "正在启动 SELF 重建服务（Windows API $Port + WSL GPU worker）……" -ForegroundColor Cyan
Write-Host "就绪判据：http://127.0.0.1:$Port/v1/reconstruction/health 返回 engine=ready（worker 预检约 2~3 分钟）。"
Write-Host "停止方式：关闭本窗口或 Ctrl+C（会同时停止 WSL worker）。"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $server -Port $Port
exit $LASTEXITCODE
