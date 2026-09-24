param([string]$DevEcoHome = 'C:\Program Files\Huawei\DevEco Studio')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$node=Join-Path $DevEcoHome 'tools\node\node.exe'
$hvigor=Join-Path $DevEcoHome 'tools\hvigor\bin\hvigorw.js'
if(!(Test-Path -LiteralPath $node) -or !(Test-Path -LiteralPath $hvigor)){throw 'DevEco toolchain not found; supply -DevEcoHome.'}
$env:DEVECO_SDK_HOME=Join-Path $DevEcoHome 'sdk'
$env:JAVA_HOME=Join-Path $DevEcoHome 'jbr'
$env:OHOS_BASE_SDK_HOME=Join-Path $DevEcoHome 'sdk\default\openharmony'
$buildCmd=Join-Path $root 'artifacts\self-build-cmd.exe'
New-Item -ItemType Directory -Force (Split-Path -Parent $buildCmd) | Out-Null
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:exe "/out:$buildCmd" (Join-Path $root 'scripts\BuildCmd.cs')
if($LASTEXITCODE -ne 0){throw 'Build command adapter compilation failed'}
$originalComSpec=$env:ComSpec
$env:ComSpec=$buildCmd
try {
& $node scripts/prepare-audio.mjs
if($LASTEXITCODE -ne 0){throw 'Audio asset preparation failed'}
& $node scripts/build-gs-viewer.mjs
if($LASTEXITCODE -ne 0){throw '3DGS viewer preparation failed'}
& (Join-Path $PSScriptRoot 'Prepare-NativeResources.ps1')
# renderer-web remains a development reference. Production compilation does not require Three.js/esbuild.
$ErrorActionPreference='Continue'
& $node $hvigor --mode module -p product=default -p module=entry@default -p buildMode=debug assembleHap --no-daemon 2>&1 | Tee-Object -FilePath docs/evidence/hap-build.log
$buildExit=$LASTEXITCODE
$ErrorActionPreference='Stop'
if($buildExit -ne 0){throw 'HAP build failed; see docs/evidence/hap-build.log'}
} finally { $env:ComSpec=$originalComSpec }
