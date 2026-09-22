param([switch]$Refresh)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$out=Join-Path $root 'assets-src\LeePerrySmith-r186'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$base='https://raw.githubusercontent.com/mrdoob/three.js/r186/'
$paths=@('examples/models/gltf/LeePerrySmith/LeePerrySmith.glb','examples/models/gltf/LeePerrySmith/Map-COL.jpg','examples/models/gltf/LeePerrySmith/LeePerrySmith_License.txt','examples/webgl_decals.html','examples/webgl_multiple_scenes_comparison.html','LICENSE','package.json')
$records=@()
foreach($relative in $paths){
  $name=Split-Path -Leaf $relative
  $target=Join-Path $out $name
  if($Refresh -or !(Test-Path -LiteralPath $target)){Invoke-WebRequest -UseBasicParsing -Uri ($base+$relative) -OutFile $target}
  $file=Get-Item -LiteralPath $target
  $records+=@{path=$relative;file=$name;source=($base+$relative);bytes=$file.Length;sha256=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLower()}
}
@{tag='r186';retrievedAt=[DateTime]::UtcNow.ToString('o');files=$records} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $out 'sources.json') -Encoding UTF8
Write-Output 'Pinned source files and hashes are ready. Asset modifications are recorded in assets/manifest.json.'
