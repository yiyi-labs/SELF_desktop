param([string]$Device,[string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$hdc=Join-Path $DevEcoHome 'sdk\default\openharmony\toolchains\hdc.exe'
$targets=@((& $hdc list targets) | Where-Object {$_ -and $_ -ne '[Empty]'} | ForEach-Object {$_.Trim()})
if(!$Device){if($targets.Count -ne 1){throw 'Specify -Device using hdc list targets.'};$Device=$targets[0]}
if($Device -notin $targets){throw 'Selected device is not connected'}
$hap=Join-Path $root 'entry\build\default\outputs\default\entry-default-unsigned.hap'
if(!(Test-Path -LiteralPath $hap)){throw 'Build-Hap.ps1 must succeed first'}
$result=& $hdc -t $Device install -r $hap
$result | Set-Content -LiteralPath (Join-Path $root 'docs\evidence\hap-install.log') -Encoding UTF8
if($LASTEXITCODE -ne 0 -or ($result -join '') -notmatch 'install bundle successfully'){throw 'Installation failed; do not claim device compatibility'}
& $hdc -t $Device shell aa force-stop com.self.mirror
& $hdc -t $Device shell aa start -a EntryAbility -b com.self.mirror
