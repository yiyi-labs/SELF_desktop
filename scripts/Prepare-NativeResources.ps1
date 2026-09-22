$ErrorActionPreference='Stop'
$project=Split-Path -Parent $PSScriptRoot
$destination=Join-Path $project 'entry/src/main/resources/rawfile/assets'
New-Item -ItemType Directory -Force $destination | Out-Null
Copy-Item -Path (Join-Path $project 'assets/*') -Destination $destination -Recurse -Force
Write-Output 'Copied checked-in GLB, masks, manifests, licenses and original audio into native rawfile resources.'
