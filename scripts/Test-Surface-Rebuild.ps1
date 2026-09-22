param([string]$Device='127.0.0.1:5555',[int]$Rebuilds=10,[string]$DevEcoHome='C:\Program Files\Huawei\DevEco Studio')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$hdc=Join-Path $DevEcoHome 'sdk/default/openharmony/toolchains/hdc.exe'
& ./scripts/Start-NativeProbe.ps1 -Device $Device -DevEcoHome $DevEcoHome
function Find-Button($node){
 if($node.attributes.text -eq '重建表面' -and $node.attributes.enabled -eq 'true'){return $node.attributes.bounds}
 foreach($child in $node.children){$found=Find-Button $child;if($found){return $found}}
 return $null
}
$memory=@()
for($cycle=0;$cycle -le $Rebuilds;$cycle++){
 $bounds=$null
 for($attempt=0;$attempt -lt 25;$attempt++){
  Start-Sleep -Seconds 1
  & $hdc -t $Device shell uitest dumpLayout -b com.self.mirror -p /data/local/tmp/self-surface-layout.json | Out-Null
  & $hdc -t $Device file recv /data/local/tmp/self-surface-layout.json docs/evidence/native-es3/surface-layout.json | Out-Null
  $bounds=Find-Button (Get-Content docs/evidence/native-es3/surface-layout.json -Raw | ConvertFrom-Json)
  if($bounds){break}
 }
 if(!$bounds){throw 'Surface probe did not finish; retain logs and inspect emulator'}
 $appPid=((& $hdc -t $Device shell pidof com.self.mirror) -join '').Trim()
 $status=& $hdc -t $Device shell cat ('/proc/'+$appPid+'/status')
 $memory+=@{cycle=$cycle;pid=$appPid;memory=@($status | Select-String '^VmRSS:|^VmHWM:|^Threads:') | ForEach-Object {$_.Line}}
 if($cycle -lt $Rebuilds){$xy=[regex]::Matches($bounds,'\d+') | ForEach-Object {[int]$_.Value};$x=[int](($xy[0]+$xy[2])/2);$y=[int](($xy[1]+$xy[3])/2);& $hdc -t $Device shell uitest uiInput click $x $y | Out-Null}
}
$memory | ConvertTo-Json -Depth 5 | Set-Content docs/evidence/native-es3/surface-memory.json
$lines=@(& $hdc -t $Device shell hilog -x -T JSAPP | Where-Object {$_ -match ('\s'+$appPid+'\s') -and $_ -match 'SELF_'})
$lines | Set-Content docs/evidence/native-es3/surface-runtime.log
if(($lines | Select-String 'SELF_ES_FAIL|"type":"ERROR"').Count -gt 0){throw 'Native surface recreation reported a runtime failure'}
if(($lines | Select-String 'SELF_ES_PROBE_FINISHED').Count -lt ($Rebuilds+1)){throw 'Not all recreated surfaces completed the native probe'}
Write-Output ('Actual SurfaceHolder destruction/recreation completed '+$Rebuilds+' times in the same app process.')
