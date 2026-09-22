param([string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$node=Join-Path $DevEcoHome 'tools\node\node.exe'
$hdc=Join-Path $DevEcoHome 'sdk\default\openharmony\toolchains\hdc.exe'
$emulator=Join-Path $DevEcoHome 'tools\emulator\Emulator.exe'
foreach($p in @($node,$hdc,$emulator)){if(!(Test-Path -LiteralPath $p)){throw ('Missing tool: '+$p)}}
$report=@{checkedAt=[DateTime]::UtcNow.ToString('o');devecoHome=$DevEcoHome;deveco=(Get-Content -LiteralPath (Join-Path $DevEcoHome 'product-info.json') -Raw | ConvertFrom-Json);sdk=(Get-Content -LiteralPath (Join-Path $DevEcoHome 'sdk\default\sdk-pkg.json') -Raw | ConvertFrom-Json);node=(& $node --version);hdc=(& $hdc -v);devices=(& $hdc list targets);emulatorVersion=(Get-Item -LiteralPath $emulator).VersionInfo.FileVersion}
$report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $root 'docs\evidence\environment.json') -Encoding UTF8
Write-Output ($report | Select-Object checkedAt,devecoHome,node,hdc,devices,emulatorVersion | Format-List | Out-String)
