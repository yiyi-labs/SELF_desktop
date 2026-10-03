"""Restart the reconstruction service as detached processes that outlive this session.

Same commands as scripts/Start-ReconstructionServer.ps1 (worker) and run-uvicorn.py (API),
spawned with DETACHED_PROCESS so no Claude task limit reaps them.
归档修正：原先指向临时目录的 run-uvicorn.py 改为与本脚本同目录，临时目录清理后仍可直接运行。
"""
import pathlib
import subprocess

REPO = pathlib.Path(r"d:/STUDY/College/mine/olay")
HERE = pathlib.Path(__file__).resolve().parent
DATA = REPO / "backend/.data/reconstruction"
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def spawn(argv, out, err):
    with open(out, "ab") as o, open(err, "ab") as e:
        proc = subprocess.Popen(argv, stdout=o, stderr=e, stdin=subprocess.DEVNULL,
                                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                                close_fds=True)
    print("spawned pid", proc.pid, "->", pathlib.Path(out).name)


spawn(["wsl.exe", "-d", "Ubuntu-22.04", "--", "env",
       "SELF_RECON_JOBS_DIR=/mnt/d/STUDY/College/mine/olay/backend/.data/reconstruction",
       "CUDA_HOME=/usr/local/cuda-12.8", "TORCH_CUDA_ARCH_LIST=12.0", "MAX_JOBS=2",
       "PATH=/opt/self-reconstruction/venv/bin:/usr/local/cuda-12.8/bin:/usr/sbin:/usr/bin:/sbin:/bin",
       "/opt/self-reconstruction/venv/bin/python",
       "/mnt/d/STUDY/College/mine/olay/backend/worker.py"],
      DATA / "worker.stdout.log", DATA / "worker.stderr.log")

spawn([str(REPO / "backend/.venv/Scripts/python.exe"),
       str(HERE / "run-uvicorn.py")],
      DATA / "api.stdout.log", DATA / "api.stderr.log")
