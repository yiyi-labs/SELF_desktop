"""Run one isolated research command while sampling actual device GPU use."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path


def run(out: Path, command: list[str]) -> int:
    if out.exists():
        raise FileExistsError(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    process = subprocess.Popen(command)
    samples = []
    while process.poll() is None:
        probe = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=8)
        if probe.returncode == 0:
            try:
                values = [int(part.strip()) for part in probe.stdout.splitlines()[0].split(",")]
                samples.append({"seconds": round(time.monotonic()-started, 2),
                                "deviceUsedMiB": values[0], "deviceTotalMiB": values[1],
                                "gpuUtilizationPercent": values[2]})
            except (IndexError, ValueError):
                pass
        time.sleep(.8)
    result = {"command": command, "exitCode": process.returncode,
              "elapsedSeconds": round(time.monotonic()-started, 2),
              "samples": samples,
              "devicePeakUsedMiB": max((s["deviceUsedMiB"] for s in samples), default=None),
              "note": "Device used includes display/other processes; compare idle baseline separately."}
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("exitCode", "elapsedSeconds", "devicePeakUsedMiB")}), flush=True)
    return process.returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("research command required")
    raise SystemExit(run(args.out, args.command))
