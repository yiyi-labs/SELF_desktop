# backend 改名证据（2026-10-03）

在役模块统一去掉 `reconstruction_` 前缀：46 个 `backend/reconstruction_*.py` → `backend/*.py`（`worker.py`、`runtime.py`、`live_fullframe.py`、`code_identity.py` …；本就不带前缀的 `app.py`、`recon_transfer.py`、`probe_*.py` 等不动），31 个 `backend/tests/test_reconstruction_*.py` → `backend/tests/test_*.py`。全仓 387 处引用同步改写（导入、按路径启动的字符串、脚本、测试夹具）。完整映射见 `rename-map.json`。

## 算法闭包哈希

- 闭包 52 个成员按文件名 1:1 不变（`identity-before.json` vs `identity-after.json`；内容哈希因导入改写而变化属预期）。
- 哈希 `fa53df8abce1d19d03417ac0e8c2b189f187a6713a2ff508c5b0e0195ca9daef` → `e7040005a447ed672a43a6f1dd1d51619b3845c6e8d2e08a4c2def76ad65fcab`，`engine-profile.json` 同步重钉（`engine-profile-before.json` / `engine-profile-after.json`）。
- 运行时自证：服务重启后 worker 心跳 `loadedImplementationSha256 = currentImplementationSha256 = profileImplementationSha256 = e7040005…`，`sourceIdentityVerified=true`，`/v1/reconstruction/health` 返回 `engine=ready`。

## 测试 A/B（改名前后同命令、同解释器）

| 环境 | 用例 | 错误 | 结论 |
|---|---|---|---|
| Windows venv（缺 torch/cv2/scipy） | 139 | 34 | 错误集合（含完整回溯文本）逐一相同 |
| WSL 完整环境（缺 fastapi/httpx/PIL） | 295 | 13 | 错误集合逐一相同 |

原始日志：`win-before.txt` / `win-after.txt`、`wsl-before.txt` / `wsl-after.txt`。全部错误均为环境缺包，没有项目模块缺失。

## 真实端到端

`e2e-20261003.json`：用既有采集 `incoming/self-quality-temporary-20260926.mp4`（65,453,964 B，sha256 `7ac189eb…`）走完整 HTTP 协议（63 个分块上传 → 封存 → 轮询，18:31–18:46 约 15 分钟），作业 `07483aca583bd94566a4c115eb87636d` 到达 `gaussian_ready`，下载全部 5 个产物（`gaussian` 18,746,720 B 与 `preview3d`、`scene3d` 均为 PLY，magic `706c790a`；`preview` PNG，magic `89504e47`；`view` JSON），原始日志见 `e2e-run.log`。作业记录四处（`job.json`、`portrait.algorithm.json`、`portrait-state/config.json`、`portrait-state/report.json`）均为新哈希，且新作业目录中不出现旧哈希。

## 独立复现（同日第二次端到端）

改名与重钉完成之后，用同一采集、同一协议完整复跑，并如实记录一次中途作废的尝试：

1. **作废尝试 `13b77bfacfb4037c9ed8a9247fec153c`**（19:09:55 建单）：上传至第 57 块（`receivedChunks` 0–55）时服务端返回 HTTP 500。根因不在服务与算法，而在本次会话新增的外部看守脚本——它以 `open()` 读取作业目录的 `job.json`，与 WSL 侧 `os.replace()` 的原子替换竞争，触发 `PermissionError: [WinError 5]`（抛在传输模块的原子替换处）。看守改为只对 `portrait-training/` 与 `*.log` 做快照、不再触碰 `job.json` 后重跑新单；该作废单未再续传（目录中残留 `job.f422907f.tmp`，即当时被中断的替换现场）。
2. **成功复跑 `fad420202b75ad659ba69e1fd1727ab0`**：19:10:46 健康检查（`engine=ready`）→ 建单 → 63 块分块上传 1.7 s → 封存 → 轮询；19:25:34 到达 `gaussian_ready`，下载全部 5 个产物：

| 产物 | 字节 | sha256（前 16 位） | magic |
|---|---|---|---|
| gaussian | 23,354,384 | `833134a476d965c9` | `706c790a`（PLY） |
| preview | 15,506 | `baa27be55d61df21` | `89504e47`（PNG） |
| preview3d | 4,065,632 | `79997025ac3f8b0c` | `706c790a`（PLY） |
| scene3d | 6,609,476 | `8f254123e7d464b6` | `706c790a`（PLY） |
| view | 750 | `4660f3f563b34904` | JSON |

原始日志：`e2e-20261003-rerun.log`。

与首次作业（`07483aca…`）对比：`scene3d` 字节数完全相同（6,609,476），其余产物的字节数有小幅出入——训练管线含随机成分，不保证逐字节复现；两次作业的协议行为、终态与产物结构（PLY/PNG/JSON 及 magic）一致。
