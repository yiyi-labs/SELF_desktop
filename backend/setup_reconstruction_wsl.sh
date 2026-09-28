#!/usr/bin/env bash
set -euo pipefail

# Run only inside Ubuntu 22.04 on WSL. The Windows NVIDIA driver is reused;
# never install a Linux NVIDIA driver in WSL.
if [[ "$(id -u)" != "0" ]]; then echo 'Run as root in the configured WSL distro.' >&2; exit 1; fi
if ! /usr/lib/wsl/lib/nvidia-smi --query-gpu=name --format=csv,noheader | grep -q 'RTX 5070'; then
  echo 'The expected RTX 5070 is not visible to WSL.' >&2; exit 1
fi
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg curl build-essential ninja-build python3-venv libgles2
if [[ ! -x /usr/local/cuda-12.8/bin/nvcc ]]; then
  curl -fL --retry 3 -o /tmp/cuda-keyring_1.1-1_all.deb \
    https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb
  dpkg -i /tmp/cuda-keyring_1.1-1_all.deb
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y cuda-toolkit-12-8
fi
python3 -m venv /opt/self-reconstruction/venv
PYTHON=/opt/self-reconstruction/venv/bin/python
export PATH="/opt/self-reconstruction/venv/bin:/usr/local/cuda-12.8/bin:$PATH"
"$PYTHON" -m pip install --upgrade 'setuptools<82' pip wheel
"$PYTHON" -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu128
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$PYTHON" -m pip install -r "$SCRIPT_DIR/requirements-reconstruction-wsl.txt"
# The headless OpenCV wheel above is intentional. MediaPipe declares the
# desktop opencv-contrib wheel, but the ImageSegmenter/FaceLandmarker tasks do
# not use its contrib modules. Keep the service headless and avoid two cv2
# distributions overwriting one another.
"$PYTHON" -m pip install 'absl-py==2.5.0' 'certifi==2026.7.22' \
  'flatbuffers==25.12.19' 'sounddevice==0.5.6' 'matplotlib==3.10.9'
"$PYTHON" -m pip install --no-deps 'mediapipe==1.0.1'
PYTHONPATH="$SCRIPT_DIR" "$PYTHON" - <<'PY'
from pathlib import Path
import mediapipe as mp
from reconstruction_face import check_models
check_models()
assert mp.__version__ == '1.0.1'
PY
CUDA_HOME=/usr/local/cuda-12.8 TORCH_CUDA_ARCH_LIST=12.0 MAX_JOBS=2 \
  "$PYTHON" "$SCRIPT_DIR/reconstruction_train.py" --smoke
