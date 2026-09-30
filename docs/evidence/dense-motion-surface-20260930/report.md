# 新深度路径交接验收与暂停记录（2026-09-30）

当前结论：代码/CPU 合同检查通过；真实深度批次、有限训练、画质和双端显示尚未通过。没有新合格模型，没有部署或回传。本记录不是重建完成报告。

用户已授权在原隔离 W 下载固定工具、创建独立环境、修改后端并有限训练。随后用户要求先验收并暂停，重启恢复后再继续。此处保存现场，不替换既有算法主干。

## 身份与保护

- W：`C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay`
- 开始/验收时 HEAD：`565d3452cbaa9cc78d3c46c9fa4e4e256d9579fe`，分支 `codex/reconstruction-v3-audit-20260928`。
- P：`D:/STUDY/College/mine/olay`，HEAD `3dad0cd5651824cc06d9e88d61aabdd2642c0b30`。本轮没有写入 P。
- 原未跟踪审计文件保留；验收前暂存区为空。只提交下列本轮文件，不处理其他文件。
- R0：`backend/.sources/fullframe-surface-patch-20260929-b/R0-frozen.pt`；SHA256 `2468edc379f8b76eac97fccfbf9e9a4c775f980102b95283ee15b2dc4cee7cb8`。
- Prepared：P 的 `backend/.sources/integrated-components-v2-20260928-e`，不修改。
- 输入视频 SHA256：`7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。
- E1—E5、应用、签名、旧作品、USB/HDC、PlayCanvas、AI/OLAY/上脸/故事及生产入口均未修改。没有清理、回退或覆盖旧 run。

## 本轮实际新增的代码

1. `backend/setup_reconstruction_dense_tool.py`：固定官方模型 revision，核对下载与 LFS SHA，保存权重锁。不导入上游 GS 输出器。
2. `backend/reconstruction_dense_contract.py`：明确 camera-z、W2C、原生像素中心、裁剪/缩放 K、一窗口一相似尺度与来源角色。只有已核实的同一 Parameter 对象可以补序列化别名；独立缺失权重拒绝加载。
3. `backend/run_dense_observations.py`：训练角色图像按明确名称和时间映射，头局部 F 与世界 C 分组。固定相机不被预测相机改写；使用预测相机只作整窗口尺度/一致性检查。有限重叠窗口、原图有效 crop、不读取开发/回归 RGB 作初始化。严格输出尺寸检查；异常保存 failure，不生成可用 manifest。
4. `backend/reconstruction_dense_surfaces.py`：分别从头局部/世界深度提议采样；真实原片颜色；深度断层不连接成宽核；三视角兼容、空区反证、遮挡未知分别记录；去重不跨语义层，保留 UID、像素与支持来源。**真实视频表面生成尚未运行，模型深度不代表测量真值。**
5. 两个测试文件：现共 16 项 CPU 回归。报告与原始测试输出附于本目录。

原生全幅后切 ROI、head-local-SH1、gsplat1.5.3 没有被新工具替换。以上模块目前没有生产导入；也尚未接上/执行新的优化循环。不能将“写了表面生成函数”写为“连续人像、衣物与房间已修复”。

## 下载、环境与许可

- 官方来源：https://github.com/ByteDance-Seed/Depth-Anything-3
- 源码 commit：`3d835ec1a5802d64a8b8b15f817a1ab54809bfe4`。
- 官方源码 ZIP SHA256：`a19b31f64ed11d5c38438ea0f3e0864eecc299044967026749304c3a03dcf053`。
- 官方模型：`depth-anything/DA3-BASE`，revision `f4a6c9b3c95e41c82048423d3493a81ec3fa810e`。
- 权重文件 541518028 bytes，SHA256 `e01067dc1659613083d9145a9a2547ccdbe6ccbbf83c4fe7b3e8a4e2bdae78b5`，与官方 LFS OID 一致。
- Base 模型和代码为 Apache-2.0；原 LICENSE/model card 保留。没有使用可能有不同许可的上游 GS head。没有训练/调用 MegaSaM 或 Shape of Motion，不能声称已复现它们。
- 工具固定目录：W `backend/.sources/tools/da3-3d835ec`；模型、源码和 venv 都在工程内。
- 新环境只安装固定小依赖，使用新的 `.pth` 只读引用 `/opt/self-reconstruction/venv/lib/python3.10/site-packages`：einops 0.8.1、addict 2.4.0、omegaconf 2.3.0、antlr4-python3-runtime 4.9.3、safetensors 0.6.2、imageio 2.37.0、tqdm 4.67.1。
- 没有直接安装 upstream pyproject，避免其 GS/CUDA/重依赖改动原锁定环境。新环境继续使用原 torch 2.8.0+cu128。验收 `originalPackageChanges={}`。
- 独立环境属于研究资产，Git 不备份这些下载文件；没有上传私人影像或模型。

## 实际执行与失败定位

独立 run a—f 都保留。前三次在预处理依赖加载时失败；d 在严格权重载入发现共享 LayerNorm 别名；e 已实际执行网络前向，但适配器错误对 N×H×W NumPy 数组调用 `squeeze(-1)`，未保存有效深度。别名及张量形状已修正，不代表深度本身通过。

f：CUDA 前向中返回 `torch.AcceleratorError: CUDA error: unknown error`。随后独立最小计算报告 `Found no NVIDIA driver on your system`，`torch.cuda.is_available()` 为 False。Windows RTX 5070 PnP 状态 Unknown；VideoController 只列 Intel Arc。此前最小 CUDA 计算及设备名称曾成功。

这证明训练环境在运行过程中失去可用 GPU；不能从这个错误断言 8GB 不足、OOM、算法本身失败或驱动损坏。没有自行切换显卡模式、修改驱动或重启。当前没有继续运行的推理/训练任务。

## 当前验收

| 项目 | 状态 | 实际证据 |
|---|---|---|
| 新增文件语法 | 通过 | 6 文件 py_compile |
| 像素/K、投影往返、旋转、唯一尺度、角色和身份 | 通过 | CPU 合同回归 |
| 共享参数别名/独立缺失权重拒绝 | 通过 | 实际别名核对 + 回归 |
| 平面法向/协方差、深度断层、遮挡、重复图像去重 | 通过 | CPU 合同回归 |
| 全部 16 项测试 | 通过 | tests.txt、acceptance.json |
| 固定权重 hash | 通过 | 实際文件 SHA / LFS 对照 |
| 原训练环境包版本 | 未改变 | 原版本快照逐项比较，差异为空 |
| 实际可用深度批次、尺度门禁及多视图表面 | 未完成 | 没有 usable manifest |
| 新表面真实训练/完整场景 joint | 未运行 | optimizer 步数 0 |
| 画质、连续颈肩衣物、房间与遮挡 | 未验证 | 没有候选，不以 CPU 合成充数 |
| 同 PLY 连续绕看/PlayCanvas/HarmonyOS | 未验证 | 未导出正式候选、未设备测试 |
| 部署/回传/发布 | 未执行 | 原作品不替换 |

注意，预测深度只是新几何提议。窗口间尺度一致、可信静态点深度、头部细节精度、头发真实外表面、镜框反光及独立身体 B 都需要实际验证；不能把头 F 套给衣物。当前生成器尚不生成新衣物运动或完整颈肩表示。

## 重启后最小恢复动作

1. 先检查 W/P HEAD、dirty 状态和当前源码 hash，保留此次本地提交，不强制 reset；读取本报告和 acceptance.json。
2. 在原训练环境执行最小 CUDA 计算，不以 is_available 单独放行。
3. 固定上述模型和相机，重新执行 `run_dense_observations.py`，输出到**新的** `backend/.sources/dense-motion-surface-20260930-g/depth`（若该目录已存在，使用下一个独立 run-id）。不覆盖 a—f，不冒称精确 resume。
4. 读取全批尺度与相机一致性结果。只在有效深度通过必要检查后运行 `build_surfaces`；先确认同坐标原静态支持与新深度及重叠窗口能互相解释。
5. 再接有限真实训练与相同原生全幅/角色划分对照，补独立上身运动与附件几何。尚未接线/训练的内容单列，不用当前单元测试代替。
6. 完成原片/R0/新初始化/真实训练后固定对照，单份 PLY hash、连续旋转和现有编辑合同核验。研究失败不回传、不切生产。

可复现命令（WSL 路径，重启确认 GPU 恢复后才执行）：

```text
/opt/self-reconstruction/venv/bin/python -m unittest test_reconstruction_dense_contract test_reconstruction_dense_surfaces -v

/mnt/c/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/tools/da3-3d835ec/venv/bin/python /mnt/c/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/run_dense_observations.py --prepared /mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e --split /mnt/c/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/fullframe-surface-patch-20260929-b/observations.json --tool /mnt/c/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/tools/da3-3d835ec --out /mnt/c/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/dense-motion-surface-20260930-g/depth --limit 24 --batch 8
```

本次暂停没有解除发布门禁，也没有完成用户要求的真实质量提升。恢复后从已保存状态继续，不重复 FLAME A/B、d2 背景审计或既有全幅修复。