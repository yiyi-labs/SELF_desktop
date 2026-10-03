param([string]$Serial = '')

$ErrorActionPreference = 'Stop'
$taskName = 'SELF Reconstruction Link'
$watcher = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'Watch-ReconstructionDevice.ps1')).Path
if ($Serial -and $Serial -notmatch '^[A-Za-z0-9._-]+$') { throw 'Invalid device serial.' }

# Preserve the current device selection when switching this machine to manual mode.
$existing = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue
if ($existing) {
  if (($existing.Actions.Arguments -join ' ') -notlike "*$watcher*") {
    throw 'The existing task belongs to another checkout; it was not changed.'
  }
  if (!$Serial -and ($existing.Actions.Arguments -join ' ') -match '(?:^|\s)-Serial\s+([A-Za-z0-9._-]+)(?:\s|$)') {
    $Serial = $Matches[1]
  }
  $projectRoot = Split-Path -Parent $PSScriptRoot
  $backup = Join-Path $projectRoot 'artifacts/reconstruction-task-before-manual.xml'
  if (!(Test-Path -LiteralPath $backup)) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
    Export-ScheduledTask -TaskName $taskName -TaskPath '\' | Set-Content -LiteralPath $backup -Encoding Unicode
  }
}

$arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $watcher + '"'
if ($Serial) { $arguments += ' -Serial ' + $Serial }
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$powershell = Join-Path ([Environment]::GetFolderPath('System')) 'WindowsPowerShell/v1.0/powershell.exe'
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
  -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
# Deliberately omit logon/boot triggers and automatic task restarts.
$definition = New-ScheduledTask -Action $action -Principal $principal -Settings $settings
Register-ScheduledTask -TaskName $taskName -TaskPath '\' -InputObject $definition -Force | Out-Null

$configured = Get-ScheduledTask -TaskName $taskName -TaskPath '\'
if (@($configured.Triggers | Where-Object { $null -ne $_ }).Count -ne 0 -or $configured.Settings.StartWhenAvailable -or $configured.Settings.RestartCount) {
  throw 'Manual startup configuration could not be verified.'
}
Write-Output 'SELF startup is manual. Windows sign-in will not start it. Double-click Start-SELF.cmd to start.'
