param()
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$artifactRoot=Join-Path $projectRoot 'artifacts'
if((Get-Content (Join-Path $projectRoot 'backend/.env.example') -Raw) -match '(?m)^DEEPSEEK_API_KEY=\S+') {throw 'The distributable env example must not contain a key'}
New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
$hap=Join-Path $projectRoot 'entry\build\default\outputs\default\entry-default-unsigned.hap'
if(!(Test-Path -LiteralPath $hap)){throw 'Build-Hap.ps1 must succeed before packaging'}
Copy-Item -LiteralPath $hap -Destination (Join-Path $artifactRoot 'SELF-debug-unsigned.hap')
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$hapArchive=[System.IO.Compression.ZipFile]::OpenRead($hap)
$verifiedRawFiles=0
try{
  $nativeAbis=@('arm64-v8a','x86_64')
  foreach($abi in $nativeAbis){if(!$hapArchive.GetEntry('libs/'+$abi+'/libself_native.so')){throw ('Native library missing: '+$abi)}}
  foreach($entry in $hapArchive.Entries){
    if(!$entry.FullName.StartsWith('resources/rawfile/') -or $entry.FullName.EndsWith('/')){continue}
    $sourcePath=Join-Path $projectRoot ('entry/src/main/'+$entry.FullName)
    if(!(Test-Path -LiteralPath $sourcePath)){throw ('Packaged source missing: '+$entry.FullName)}
    $entryStream=$entry.Open();$hash=[System.Security.Cryptography.SHA256]::Create()
    try{$packagedHash=[BitConverter]::ToString($hash.ComputeHash($entryStream)).Replace('-','')}finally{$entryStream.Dispose();$hash.Dispose()}
    if($packagedHash -ne (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash){throw ('Stale packaged resource: '+$entry.FullName)}
    $verifiedRawFiles++
  }
}finally{$hapArchive.Dispose()}
if($verifiedRawFiles -lt 8){throw 'Required packaged resources were not found'}
$archivePath=Join-Path $artifactRoot 'SELF-source-and-evidence.zip'
$stream=[System.IO.File]::Open($archivePath,[System.IO.FileMode]::Create)
$archive=[System.IO.Compression.ZipArchive]::new($stream,[System.IO.Compression.ZipArchiveMode]::Create)
$included=[System.Collections.Generic.List[string]]::new()
function Add-SourceDirectory([string]$directory){
  foreach($item in Get-ChildItem -LiteralPath $directory -Force){
    if($item.PSIsContainer){
      if($item.Name -in @('node_modules','oh_modules','.hvigor','.npm-cache','.git','.idea','.preview','.cxx','.browser-profile','artifacts','build','dist','.test','signing','.codex','.agents','.venv','__pycache__','.pytest_cache')){continue}
      Add-SourceDirectory $item.FullName
    }else{
      if(($item.Name.StartsWith('.env') -and $item.Name -ne '.env.example') -or $item.Name -eq 'local.properties' -or $item.Extension -eq '.tmp' -or $item.Name -eq 'huawei-download-page.html'){continue}
      $entryName=$item.FullName.Substring($projectRoot.Length+1).Replace('\','/')
      [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive,$item.FullName,$entryName,[System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
      $included.Add($entryName)
    }
  }
}
try{Add-SourceDirectory $projectRoot}finally{$archive.Dispose();$stream.Dispose()}
$records=@('SELF-debug-unsigned.hap','SELF-source-and-evidence.zip') | ForEach-Object {
  $file=Get-Item -LiteralPath (Join-Path $artifactRoot $_)
  [ordered]@{file=$file.Name;bytes=$file.Length;sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
}
[ordered]@{createdAt=(Get-Date).ToString('o');sourceCommit=(& git -C $projectRoot rev-parse HEAD);status='Native ES3 debug unsigned. Latest tests use the API26 tablet only; see docs/interaction-camera-validation.md. Host camera preview passed, MP4 recording failed because the emulator exposes no video encoder. Personal reconstruction, real-device recording and calibrated cosmetics remain unverified.';nativeAbis=$nativeAbis;packagedRawFilesVerified=$verifiedRawFiles;sourceFiles=$included.Count;files=$records} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $artifactRoot 'delivery-manifest.json') -Encoding UTF8
Write-Output ('Packaged '+$included.Count+' source, asset and evidence files into '+$artifactRoot)
