param(
  [ValidateRange(10, 600)][int]$TimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
$taskName = 'SELF Reconstruction Link'
$projectRoot = Split-Path -Parent $PSScriptRoot
$watcher = Join-Path $PSScriptRoot 'Watch-ReconstructionDevice.ps1'
$port = 8787

try {
  $task = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction Stop
  if (($task.Actions.Arguments -join ' ') -notlike "*$watcher*") {
    throw '启动任务属于另一个项目目录，未启动。'
  }
  if (@($task.Triggers | Where-Object { $null -ne $_ }).Count -ne 0 -or $task.Settings.StartWhenAvailable -or $task.Settings.RestartCount) {
    throw '当前任务仍含自动启动设置，请先运行 scripts\Set-ReconstructionManualStartup.ps1。'
  }
  if ([string]$task.State -eq 'Disabled') { throw '手动启动任务被禁用，请重新运行手动启动配置脚本。' }

  $headers = @{}
  $envFile = Join-Path $projectRoot 'backend/.env'
  if (Test-Path -LiteralPath $envFile) {
    foreach ($line in Get-Content -LiteralPath $envFile) {
      if ($line -match '^SELF_BACKEND_TOKEN=(.*)$') {
        $token = $Matches[1].Trim().Trim('"').Trim("'")
        if ($token) { $headers.Authorization = 'Bearer ' + $token }
      }
    }
  }

  $wasRunning = [string]$task.State -eq 'Running'
  if ($wasRunning) {
    Write-Host 'SELF 已开启，正在检查服务；重复点击不会重复创建工作器。'
  } else {
    Write-Host '正在开启 SELF 电脑服务和 GPU 工作器……'
    Start-ScheduledTask -TaskName $taskName -TaskPath '\'
  }

  $startedAt = Get-Date
  $startupEpoch = [DateTimeOffset]::Now.ToUnixTimeSeconds()
  $deadline = $startedAt.AddSeconds($TimeoutSeconds)
  $lastMessage = [datetime]::MinValue
  $lastFailure = ''
  $ready = $false
  while ((Get-Date) -lt $deadline) {
    $task = Get-ScheduledTask -TaskName $taskName -TaskPath '\'
    if ([string]$task.State -ne 'Running' -and ((Get-Date) - $startedAt).TotalSeconds -ge 10) {
      $info = Get-ScheduledTaskInfo -TaskName $taskName -TaskPath '\'
      throw "启动任务已退出（结果 $($info.LastTaskResult)）。"
    }
    try {
      $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 3
      $reconstruction = Invoke-RestMethod -Uri "http://127.0.0.1:$port/v1/reconstruction/health" -Headers $headers -TimeoutSec 3
      $workerState = Get-Content -LiteralPath (Join-Path $projectRoot 'backend/.data/reconstruction/worker_status.json') -Raw | ConvertFrom-Json
      $freshWorker = $wasRunning -or $workerState.updatedAt -ge $startupEpoch
      if ($health.status -eq 'ready' -and $reconstruction.status -eq 'ready' -and $reconstruction.engine -eq 'ready' -and $freshWorker) {
        $ready = $true
        break
      }
      $lastFailure = 'GPU 工作器尚未就绪。'
      if ($freshWorker -and $workerState.reason -eq 'RTX 5070 CUDA unavailable') {
        $lastFailure = '当前计算环境无法访问显卡，建模尚未就绪。'
      }
    } catch {
      # Do not display headers, credentials, HTTP bodies or personal task data.
      $lastFailure = '本机服务尚未就绪。'
    }
    if (((Get-Date) - $lastMessage).TotalSeconds -ge 10) {
      Write-Host '等待服务准备完成……'
      $lastMessage = Get-Date
    }
    Start-Sleep -Seconds 2
  }
  if (!$ready) { throw "等待启动超时。$lastFailure 日志位于 backend\.data\reconstruction。" }

  Write-Host ''
  Write-Host 'SELF 已就绪：电脑服务和 GPU 工作器均正常。' -ForegroundColor Green
  $hdc = 'C:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe'
  $serial = ''
  if (($task.Actions.Arguments -join ' ') -match '(?:^|\s)-Serial\s+([A-Za-z0-9._-]+)(?:\s|$)') { $serial = $Matches[1] }
  $targets = @(& $hdc list targets | Where-Object { $_ -and $_ -notmatch 'Offline|Empty' } | ForEach-Object { $_.Trim() })
  if (!$serial -and $targets.Count -eq 1) { $serial = $targets[0] }
  if ($serial -and $targets -contains $serial) {
    & (Join-Path $PSScriptRoot 'Connect-ReconstructionDevice.ps1') -Serial $serial -Port $port | Out-Null
    Write-Host '平板 USB 连接已就绪。'
  } else {
    Write-Host '当前未连接目标平板；连接 USB 后会自动恢复链路。'
  }
  Write-Host '可以关闭此终端窗口，服务会继续运行；重启电脑后需再次双击启动。'
  exit 0
} catch {
  Write-Host ('启动未完成：' + $_.Exception.Message) -ForegroundColor Red
  exit 1
}
