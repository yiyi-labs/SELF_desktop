param(
  [int]$Port = 8787,
  [switch]$ConnectDevice
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $projectRoot 'backend'
$python = Join-Path $backend '.venv/Scripts/python.exe'
$dataRoot = Join-Path $backend '.data/reconstruction'
if (!(Test-Path -LiteralPath $python)) { throw 'Backend Python environment is missing.' }
New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null

# Windows owns the USB-facing HTTP listener. WSL owns the RTX 5070 worker.
# Both use the same private, fixed, ignored task directory.
$wslRoot = '/mnt/' + $dataRoot.Substring(0,1).ToLowerInvariant() + $dataRoot.Substring(2).Replace('\','/')
$wslBackend = '/mnt/' + $backend.Substring(0,1).ToLowerInvariant() + $backend.Substring(2).Replace('\','/')
$wslPython = '/opt/self-reconstruction/venv/bin/python'
& wsl.exe -d Ubuntu-22.04 -- test -x $wslPython
if ($LASTEXITCODE -ne 0) { throw 'WSL reconstruction environment is missing.' }
& wsl.exe -d Ubuntu-22.04 -- test -d $wslRoot
if ($LASTEXITCODE -ne 0) { throw 'WSL cannot access the shared task directory.' }

if ($ConnectDevice) {
  & (Join-Path $PSScriptRoot 'Connect-ReconstructionDevice.ps1') -Port $Port
}

$workerOut = Join-Path $dataRoot 'worker.stdout.log'
$workerErr = Join-Path $dataRoot 'worker.stderr.log'
$worker = Start-Process -FilePath 'wsl.exe' -ArgumentList @(
  '-d', 'Ubuntu-22.04', '--', 'env', "SELF_RECON_JOBS_DIR=$wslRoot",
  'CUDA_HOME=/usr/local/cuda-12.8', 'TORCH_CUDA_ARCH_LIST=12.0', 'MAX_JOBS=2',
  'PATH=/opt/self-reconstruction/venv/bin:/usr/local/cuda-12.8/bin:/usr/sbin:/usr/bin:/sbin:/bin',
  $wslPython, "$wslBackend/reconstruction_worker.py"
) -PassThru -WindowStyle Hidden -RedirectStandardOutput $workerOut -RedirectStandardError $workerErr
try {
  $env:SELF_RECON_JOBS_DIR = $dataRoot
  $env:SELF_DEV_LOOPBACK = '1'
  Set-Location -LiteralPath $backend
  & $python -m uvicorn app:app --host 127.0.0.1 --port $Port --no-access-log
} finally {
  if ($worker -and -not $worker.HasExited) { Stop-Process -Id $worker.Id -Force }
}
