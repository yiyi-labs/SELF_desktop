param(
  [string]$Serial = '',
  [int]$Port = 8787,
  [int]$PollSeconds = 5,
  [switch]$NoServerStart
)

$ErrorActionPreference = 'Stop'
if ($Port -lt 1 -or $Port -gt 65535 -or $PollSeconds -lt 2) { throw 'Invalid watcher parameters.' }
$hdc = 'C:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe'
$connector = Join-Path $PSScriptRoot 'Connect-ReconstructionDevice.ps1'
$server = Join-Path $PSScriptRoot 'Start-ReconstructionServer.ps1'
if (!(Test-Path -LiteralPath $hdc)) { throw 'DevEco HDC was not found.' }
$serverProcess = $null
$lastServerStart = [datetime]::MinValue
$lastDevice = ''

function Test-LocalPort([int]$Port) {
  $socket = New-Object System.Net.Sockets.TcpClient
  try {
    $attempt = $socket.BeginConnect('127.0.0.1', $Port, $null, $null)
    if (!$attempt.AsyncWaitHandle.WaitOne(700)) { return $false }
    $socket.EndConnect($attempt)
    return $true
  } catch { return $false }
  finally { $socket.Close() }
}

while ($true) {
  try {
    if (!$NoServerStart -and !(Test-LocalPort $Port) -and
        (!$serverProcess -or $serverProcess.HasExited) -and
        ((Get-Date) - $lastServerStart).TotalSeconds -ge 45) {
      $lastServerStart = Get-Date
      $serverProcess = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $server + '"'),
        '-Port', "$Port"
      ) -PassThru -WindowStyle Hidden
      Write-Output "Started local reconstruction service at $($lastServerStart.ToString('s'))."
    }

    $devices = @(& $hdc list targets | Where-Object { $_ -and $_ -notmatch 'Offline|Empty' } | ForEach-Object { $_.Trim() })
    $target = if ($Serial) { if ($devices -contains $Serial) { $Serial } else { '' } }
              elseif ($devices.Count -eq 1) { $devices[0] } else { '' }
    if ($target) {
      $mapping = "tcp:$Port tcp:$Port"
      $existing = @(& $hdc fport ls | Where-Object {
        $_ -match "^$([regex]::Escape($target))\s+$([regex]::Escape($mapping))\s+\[Reverse\]"
      })
      if ($existing.Count -eq 0) {
        & $connector -Serial $target -Port $Port | Out-Null
        Write-Output "Restored USB reconstruction link for $target at $((Get-Date).ToString('s'))."
      }
      $lastDevice = $target
    } elseif ($lastDevice) {
      Write-Output "USB device disconnected at $((Get-Date).ToString('s'))."
      $lastDevice = ''
    }
  } catch {
    Write-Warning "Reconstruction link check failed: $($_.Exception.Message)"
  }
  Start-Sleep -Seconds $PollSeconds
}
