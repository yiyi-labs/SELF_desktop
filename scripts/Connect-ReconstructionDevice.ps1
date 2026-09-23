param(
  [string]$Serial = '',
  [int]$Port = 8787
)

$ErrorActionPreference = 'Stop'
if ($Port -lt 1 -or $Port -gt 65535) { throw 'Invalid local service port.' }
$hdc = 'C:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe'
if (-not (Test-Path -LiteralPath $hdc)) { throw 'DevEco HDC was not found at the configured SDK location.' }
$devices = @(& $hdc list targets | Where-Object { $_ -and $_ -notmatch 'Offline|Empty' })
if (-not $Serial) {
  if ($devices.Count -ne 1) { throw 'Specify -Serial when zero or multiple devices are connected.' }
  $Serial = $devices[0].Trim()
}
if ($Serial -notmatch '^[A-Za-z0-9._-]+$' -or $devices -notcontains $Serial) {
  throw 'Selected device is not online.'
}
$mapping = "tcp:$Port tcp:$Port"
$existing = @(& $hdc fport ls | Where-Object { $_ -match "^$([regex]::Escape($Serial))\s+$([regex]::Escape($mapping))\s+\[Reverse\]" })
if ($existing.Count -eq 0) {
  $result = & $hdc -t $Serial rport "tcp:$Port" "tcp:$Port" 2>&1
  if ($LASTEXITCODE -ne 0 -or ($result -join ' ') -notmatch 'OK') { throw "Could not connect the device to the local service: $result" }
}
Write-Output "Device $Serial can reach the local reconstruction service through USB on port $Port."
