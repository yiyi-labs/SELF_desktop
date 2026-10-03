"""Mirror Start-ReconstructionServer.ps1's uvicorn launch without -ExecutionPolicy Bypass.

Reads backend/.env the same way the ps1 does (tokens are never printed), exports
SELF_RECON_JOBS_DIR + SELF_DEV_LOOPBACK, chdirs into backend, runs uvicorn in the foreground.
"""
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(r"d:/STUDY/College/mine/olay")
ENV_FILE = REPO / "backend/.env"

if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("DEEPSEEK_API_KEY=") or line.startswith("SELF_BACKEND_TOKEN="):
            name, value = line.split("=", 1)
            os.environ[name] = value.strip().strip('"').strip("'")

os.environ["SELF_RECON_JOBS_DIR"] = str(REPO / "backend/.data/reconstruction")
os.environ["SELF_DEV_LOOPBACK"] = "1"
os.chdir(REPO / "backend")

python = str(REPO / "backend/.venv/Scripts/python.exe")
sys.exit(subprocess.call([python, "-m", "uvicorn", "app:app",
                          "--host", "127.0.0.1", "--port", "8787", "--no-access-log"]))
