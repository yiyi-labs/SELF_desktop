param([string]$Device,[string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio')
$ErrorActionPreference='Stop'
$hdc=Join-Path $DevEcoHome 'sdk\default\openharmony\toolchains\hdc.exe'
if(!$Device){
  $devices=@(& $hdc list targets | Where-Object { $_.Trim() -and $_ -notmatch 'Empty' })
  if($devices.Count -ne 1){throw 'Specify -Device when zero or multiple targets are connected'}
  $Device=$devices[0].Trim()
}
& $hdc -t $Device shell aa force-stop com.self.mirror
if($LASTEXITCODE -ne 0){throw 'Cannot stop previous SELF instance'}
$result=& $hdc -t $Device shell aa start -a NativeProbeAbility -b com.self.mirror
$result | Write-Output
if($LASTEXITCODE -ne 0 -or ($result -join "`n") -notmatch 'start ability successfully'){throw 'Native probe did not start'}
Write-Output 'Native ES3 texture/GLB/lasso/protection/export probe started. The product UI remains EntryAbility.'
