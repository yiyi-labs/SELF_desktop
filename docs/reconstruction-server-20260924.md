# SELF 本地重建服务核验（2026-09-24）

本记录区分**程序可启动**、**GPU 核函数可运行**、**一段视频通过质量门槛**和**用户的可编辑个人面容完成**。后一项必须由真实录制、外观检查与鸿蒙显示/圈选验证证明，不能由前几项推断。

## 已核对的 Remy 边界

[华为 HarmonyOS 7 产品页](https://consumer.huawei.com/cn/harmonyos-7/)把 Remy 举例为无人机影像重建大场景，也提到 3DGS 的商品建模能力。[Remy 官方网站](https://www.remy3d.cn/)介绍 3D 记录和体验，未公开其训练源码、端云分工、传输协议、人物脸部编辑拓扑或资产格式。因此本工程没有声称“复刻 Remy 算法”，也没有把 Remy 当成一个可接入的后端。华为[支持说明](https://consumer.huawei.com/cn/support/content/zh-cn16076523/)还指出 Remy 对平板机型有限制；本机设备是否可运行 Remy 不能作为 SELF 链路依据。

## 实施路线与固定存储

已连接的鸿蒙平板录制 MP4，应用以 1 MiB 分块发送到 Windows `127.0.0.1:8787`；HDC USB 反向端口把平板的同一地址连接到 PC。服务校验每块及整个 MP4 的 SHA-256，把任务原子封存在 `backend/.data/reconstruction/<jobId>/capture.mp4`。`scripts/Start-ReconstructionServer.ps1`同时运行 Windows HTTP 服务和 Ubuntu 22.04 WSL 工作器；两者共用上述固定任务根目录。此目录不参与 HAP 打包，也已加入 Git 忽略；迁移服务器时通过 `SELF_RECON_JOBS_DIR` 改到持久化数据卷。

工作器只认封存成功的 `queued` 任务：读取视频信息、原分辨率抽取无损 PNG、确认多张正脸、由 COLMAP/PyCOLMAP 恢复真实相机位姿，核对正脸区域确有三维轨迹，再由 gsplat 在 RTX 5070 上训练并验证留出视角。全分辨率训练与 8 GB 显存限制冲突时明确失败，不以静默缩小人脸换取成功状态。`portrait.gaussian.ply` 经大小、头和 SHA-256 校验后才标为 `gaussian_ready`。平板分块取回到应用私有 `filesDir/models/<jobId>/portrait.gaussian.ply`，再次核对 SHA-256，并保留本地原片 `filesDir/captures/`。可编辑 GLB 的预定路径仍是 `filesDir/models/<jobId>/portrait.glb`，只有真实 GLB 构建并验收后才能发布 `complete`。

**格式边界**：gsplat PLY 包含 Gaussian 位置、缩放、旋转、不透明度和球谐颜色，不是带 UV 的脸部网格。当前鸿蒙主界面解析 GLB Mesh；不能仅把 PLY 改扩展名、把点云三角化或用示例头模来称为本人可圈选面容。因此 `gaussian_ready` 会保存到平板并提示“可编辑面容仍在核验”，不会切换主界面作品，也不会声称脸部圈选、保护和上妆已适配。后续须建立与高斯资产配准的高质量人脸网格、纹理/语义面片及双向投影，并在真机验证遮挡、侧脸和编辑效果。

## 本机依赖与许可

| 组件 | 安装/源码位置 | 版本、许可及本工程改动 |
|---|---|---|
| Windows 驱动 / GPU | 系统驱动；WSL 复用 Windows GPU | RTX 5070 Laptop 8151 MiB，驱动 616.92，计算能力 12.0。驱动未替换 |
| CUDA Toolkit | Ubuntu 22.04 WSL `/usr/local/cuda-12.8` | NVIDIA 官方 WSL 仓库 `cuda-toolkit-12-8`；只装工具包，不装 WSL Linux 驱动；受 NVIDIA 许可约束 |
| PyTorch | WSL `/opt/self-reconstruction/venv` | `2.8.0+cu128`；官方 CUDA 12.8 wheel。适配 Blackwell SM 12.0 |
| gsplat | 同一隔离 venv；审阅源码 ZIP 在 `backend/.sources/gsplat-1.5.3` | `1.5.3`，[Apache-2.0](https://github.com/nerfstudio-project/gsplat/blob/main/LICENSE)。使用公开 rasterization、DefaultStrategy、export_splats API；未把示例训练器当作产品实现；本工程自写 `backend/reconstruction_train.py` 适配当前 PyCOLMAP、单卡 8 GB、质量门槛和任务清单 |
| PyCOLMAP / COLMAP | 同一 venv | `4.2.0`，[COLMAP new BSD](https://github.com/colmap/colmap/blob/main/COPYING.txt)；以 CPU 提取/匹配/恢复位姿，GPU 用于重建训练；不依赖旧版 `SceneManager` |
| OpenCV | 同一 venv | `opencv-python-headless 4.12.0.88`，[Apache-2.0](https://github.com/opencv/opencv/blob/4.x/LICENSE)；正脸质量门槛，不作为脸部 3D 模型或身份识别 |
| FFmpeg | Ubuntu 22.04 apt | `4.4.2`；用于读取 MP4 与无损抽帧。发行版构建许可按 Ubuntu 包和 [FFmpeg 法务说明](https://ffmpeg.org/legal.html)单独核对，不复制到 HAP |

源 ZIP 仅作审查，不纳入发行包；实际 Python 包由固定版本安装。gsplat 的 CUDA 扩展在本机用 CUDA 12.8 编译，必须通过 GPU 前向和反向 smoke 才能宣称工作器准备就绪。`backend/setup_reconstruction_wsl.sh` 是重建环境的复现脚本，`scripts/Start-ReconstructionServer.ps1` 启动日常服务，`scripts/Connect-ReconstructionDevice.ps1` 在重连 USB 后恢复 HDC 映射。

## 验证状态

可机读的本轮真机往返记录见 [`evidence/reconstruction-e2e-20260924.json`](evidence/reconstruction-e2e-20260924.json)。其中仅记录任务数值与哈希，不收录人像帧。

| 项目 | 状态 | 证据或限制 |
|---|---|---|
| Windows↔WSL 同一任务目录 | 通过 | Windows 服务在共享根保存合成 MP4；WSL 可访问该根 |
| 65 KiB 二进制探针、分块与 SHA-256 | 通过（上一轮真机） | 见 `usb-reconstruction-transfer-20260924.md`；本轮新共享目录的合成上传 SHA-256 为 `2a4764856315a0f310488f95cdffcf1a1728b24813c5a110b91b558d1512ef90` |
| RTX 5070 PyTorch CUDA 运算 | 通过 | `torch 2.8.0+cu128`，SM 12.0，2048² GPU 矩阵乘法成功 |
| gsplat CUDA 前/反向 | 通过 | CUDA 12.8、RTX 5070/SM 12.0 上 `reconstruction_train.py --smoke` 前向渲染及反向求导成功；首次编译 165.71 秒。仅证明 GPU 核函数，不证明人脸训练质量 |
| 合成空白视频质量拒绝 | 通过 | 任务 `9bb5a3c0d6379955ad40d39effe45341` 自动从 `queued` 转为 `failed:face_not_confirmed_in_capture`，资产为空；27 帧无损抽帧成功 |
| 默认端口电脑与真机状态读取 | 通过 | Windows 与已连接平板在 USB/HDC `127.0.0.1:8787` 均读到 `engine:ready`；测试端口 8789 上平板也读到上述拒绝结果 |
| 当前 HAP 上传真实拍摄并自动启动工作器 | 通过 | 用户解锁后在平板 SELF 的采集记录中启动现有 14.2 秒视频；应用通过 USB/HDC 分块上传任务 `774b943d527db68f6358966039963b38`，电脑收到 14255575 B、SHA-256 `df2246bee269c56c1501d514fd5705a82b92820b6ea23917bb49907266e4af81`，与原片完全一致，工作器自动完成位姿恢复与 GPU 训练；提交到资产写出约 2.2 分钟 |
| 真实面容 3DGS 数字质量 | 部分通过 | 自动任务独立注册 43/43 帧，40 个确认面容的视角有三维轨迹，3199 稀疏点、6779 次面部区域轨迹观测；6000 次 GPU 训练输出 92715 个 Gaussian，5 个留出视角整体 PSNR 20.65 dB、正面面部 PSNR 21.10 dB。视觉细节、侧脸及本人相似度尚未人工验收，数字指标不能替代主观外观确认 |
| 真实 3DGS 电脑→平板字节传输 | 通过 | `portrait.gaussian.ply` 为 24785017 B，SHA-256 `2ac4d2ecafb10f1cae65dca0c4008ab4396f39355e94914ea9c8d1d7b6f34d4d`；平板经 HDC 反向端口下载至测试临时目录后 SHA-256 完全一致，临时副本已删除 |
| 应用私有目录自动保存 PLY | 通过 | 应用自己按 1 MiB 分块下载 `21882216` B 到 `filesDir/models/774b943d527db68f6358966039963b38/portrait.gaussian.ply`；平板 SHA-256 与电脑资产清单同为 `035727c372d3f43b26984868fdf05332ec9f6dc5fc7876b7b14216ea823df7fa`，`reconstruction-result.json` 指向该私有路径，`reconstruction-pending.json` 已清除 |
| 高质量可编辑 GLB、鸿蒙主界面显示、贴脸圈选、上妆/保护 | 未完成 | 当前 `gaussian_ready` 只可保存 PLY；不会标为完整个人作品 |

完整人物建模是否可成功还取决于拍摄时**相机绕稳定面容移动并形成视差**，不能把脸左右转动的 11 档提示当成已知相机位姿。COLMAP [官方教程](https://colmap.github.io/tutorial)要求足够重叠、清晰纹理与几何视差。标准场景 3DGS 对表情变化、低纹理皮肤、背景占比大及 8 GB 显存都可能失败；本工作器把这些情况作为质量失败或人工核验事项，不宣称稳定性已经验证。

验证时遇到 gsplat 首次 JIT 编译缓存被两个并发工作器互相清理的问题。现在工作器启动时持有 WSL 本地独占锁；同一台电脑只能有一个重建工作器。Ubuntu 22.04 的 Python 是 3.10，MP4 与输出资产哈希使用兼容 3.10 的流式 SHA-256。首次手动编译成功后默认服务端口 8787 已在本机启动。

首个真实任务最初在训练入口因 NumPy 双精度缩放参数与 CUDA 单精度核函数不匹配而失败。修正为单精度后，在同一私有任务上手动重训，按训练指标与 PLY 完整性复核，再标为 `gaussian_ready`。之后由平板应用重新上传同一原片，后台从零自动完成并由应用保存，覆盖了此前的手动恢复缺口。训练器在保持源分辨率和质量门槛不变的前提下缓存无损解码帧，减少 Windows/WSL 共享卷反复读取开销。

华为[官方 spatialRender API](https://developer.huawei.com/consumer/en/doc/harmonyos-references/spatial-recon-spatialrender)声明 `GSPlugin.loadGSNode` 可加载 3DGS 模型，但公开示例使用 GLB，未明确保证本工程输出的 gsplat PLY 可以直接导入。当前工程主渲染器使用 GLB Mesh，也还没有与高斯资产配准的人脸网格和语义面片。因此本次验证止于**应用私有存储里的真实 PLY**；主界面仍保留示例作品，原生显示、可旋转查看本人面容、贴脸圈选/编辑均不得宣称通过。
