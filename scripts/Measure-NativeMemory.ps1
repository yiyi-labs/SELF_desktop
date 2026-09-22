param([string]$Device='127.0.0.1:5555',[int]$Samples=62,[string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio')
$hdc=Join-Path $DevEcoHome 'sdk/default/openharmony/toolchains/hdc.exe'
$records=@()
for($i=0;$i -lt $Samples;$i++){
 $appPid=((& $hdc -t $Device shell pidof com.self.mirror) -join '').Trim()
 if($appPid -match '^\d+$'){
  $status=& $hdc -t $Device shell cat ('/proc/'+$appPid+'/status')
  $records+=@{time=(Get-Date).ToString('o');pid=$appPid;memory=@($status | Select-String '^VmRSS:|^VmHWM:|^Threads:') | ForEach-Object {$_.Line}}
  $records | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $PSScriptRoot '../docs/evidence/native-es3/stress-memory.json')
 }
 Start-Sleep -Seconds 10
}
