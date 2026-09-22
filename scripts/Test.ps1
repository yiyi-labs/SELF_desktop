param([switch]$Emulator,[string]$Node='C:\Program Files\nodejs\node.exe')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
& $Node scripts/prepare-assets.mjs
if($LASTEXITCODE -ne 0){throw 'Asset preparation failed'}
& $Node scripts/validate-assets.mjs
if($LASTEXITCODE -ne 0){throw 'Asset validation failed'}
& $Node scripts/build.mjs
if($LASTEXITCODE -ne 0){throw 'Web build failed'}
$tests=@(Get-ChildItem -Path renderer-web/tests/*.test.ts | ForEach-Object {$_.FullName})
& $Node --experimental-strip-types --test @tests 2>&1 | Tee-Object -FilePath docs/evidence/unit-tests.log
if($LASTEXITCODE -ne 0){throw 'Source tests failed'}
foreach($script in @('scripts/browser-test.mjs','scripts/browser-advanced-test.mjs','scripts/browser-design-test.mjs')){& $Node $script;if($LASTEXITCODE -ne 0){throw ('Test failed: '+$script)}}
if($Emulator){& $Node scripts/emulator-full-test.mjs;if($LASTEXITCODE -ne 0){throw 'Emulator tests failed'}}
