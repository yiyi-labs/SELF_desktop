param([Parameter(Mandatory=$true)][string]$Folder,[Parameter(Mandatory=$true)][string]$ToolDirectory,[int]$Seconds=360)
$ErrorActionPreference='Stop'
$taskFolder=(Resolve-Path -LiteralPath $Folder).Path
$toolFolder=(Resolve-Path -LiteralPath $ToolDirectory).Path
if((Test-Path -LiteralPath (Join-Path $taskFolder 'execution.json')) -or (Test-Path -LiteralPath (Join-Path $taskFolder 'scene.mvs')) -or (Test-Path -LiteralPath (Join-Path $taskFolder 'dense.ply'))){throw 'Existing result: use a new run directory'}
$records=@()
function Invoke-OwnedTool([string]$name,[string[]]$values,[int]$budget){
    $exe=Join-Path $toolFolder $name
    if(!(Test-Path -LiteralPath $exe)){throw 'Pinned executable missing'}
    $quoted=@($values | ForEach-Object {if($_.Contains('"')){throw 'Invalid argument quote'}; '"'+$_+'"'})
    $clock=[Diagnostics.Stopwatch]::StartNew()
    $p=Start-Process -FilePath $exe -ArgumentList $quoted -WorkingDirectory $taskFolder -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskFolder ($name+'.stdout.txt')) -RedirectStandardError (Join-Path $taskFolder ($name+'.stderr.txt'))
    $timedOut=$false
    while(!$p.WaitForExit(1000)){if($clock.Elapsed.TotalSeconds -gt $budget){$timedOut=$true;$p.Kill();$p.WaitForExit();break}}
    $p.Refresh();$code=$p.ExitCode;$p.Dispose()
    return [pscustomobject]@{tool=$name;arguments=$values;exitCode=$code;timedOut=$timedOut;seconds=$clock.Elapsed.TotalSeconds;exeHash=(Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLower()}
}
$importArgs=@('--working-folder',$taskFolder,'--input-file',(Join-Path $taskFolder 'colmap'),'--image-folder',(Join-Path $taskFolder 'colmap/images'),'--output-file',(Join-Path $taskFolder 'scene.mvs'),'--max-threads','4','--normalize','0')
$first=Invoke-OwnedTool 'InterfaceCOLMAP.exe' $importArgs 60;$records+=,$first
if($first.exitCode -eq 0 -and !$first.timedOut){
    $denseArgs=@('--working-folder',$taskFolder,'--input-file',(Join-Path $taskFolder 'scene.mvs'),'--output-file',(Join-Path $taskFolder 'dense.mvs'),'--max-threads','4','--resolution-level','1','--max-resolution','1920','--min-resolution','640','--number-views','3','--number-views-fuse','3','--ignore-mask-label','0','--iters','3','--geometric-iters','2','--estimate-normals','2','--estimate-colors','2','--estimate-roi','0','--crop-to-roi','0','--tower-mode','0','--normalize-coordinates','0','--remove-dmaps','0')
    $records+=,(Invoke-OwnedTool 'DensifyPointCloud.exe' $denseArgs $Seconds)
}
$result=[pscustomobject]@{records=$records;denseExists=(Test-Path -LiteralPath (Join-Path $taskFolder 'dense.ply'));published=$false;installationChanged=$false}
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $taskFolder 'execution.json') -Encoding utf8
$result | ConvertTo-Json -Depth 10

