param([string]$Serial = '')

$ErrorActionPreference = 'Stop'
$watcher = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'Watch-ReconstructionDevice.ps1')).Path
$arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $watcher + '"'
if ($Serial) {
  if ($Serial -notmatch '^[A-Za-z0-9._-]+$') { throw 'Invalid device serial.' }
  $arguments += ' -Serial ' + $Serial
}
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
  -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
  -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName 'SELF Reconstruction Link' -Action $action -Trigger $trigger `
  -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'SELF Reconstruction Link'
Write-Output 'SELF reconstruction will reconnect automatically after Windows sign-in and USB reattachment.'
