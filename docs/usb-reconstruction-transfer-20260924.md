# USB 重建传输与固定存储核验（2026-09-24）

本页只记录这次**真实平板与 Windows 笔记本**的链路结果。合成片段和示例 GLB 只用于字节、格式及路径测试，均不是用户面容，也不是重建结果。

## 两端固定位置

| 内容 | 固定位置 | 当前状态 |
|---|---|---|
| 鸿蒙相机原始录制 | 应用私有 `filesDir/captures/capture-<时间>.mp4` | 既有相机实现；安装升级保留，用户可在拍摄页删除上一段 |
| 鸿蒙已验证网格 | 应用私有 `filesDir/models/<jobId>/portrait.glb`；本机路径前缀为 `/data/storage/el2/base/haps/entry/files/` | 下载方法已在真机用测试 GLB 通过；测试文件已删除。真实个人模型尚未生成 |
| Windows 任务数据 | `%LOCALAPPDATA%\SELF\Reconstruction\<jobId>\`；本机为 `C:\Users\30243\AppData\Local\SELF\Reconstruction\` | 合成上传留在 `capture.mp4`，任务清单在 `job.json`；不随工程重编译移动 |
| 后续真实结果 | 同一任务目录中的经核验资产和清单 | 尚无重建工作器产出，不存在可交付个人资产 |

服务可通过 `SELF_RECON_JOBS_DIR` 改变电脑数据根目录；默认路径由 `backend/recon_transfer.py` 固定在用户数据目录。每个 `jobId` 独立保存，传输先写分块并校验 SHA-256，封存后才原子生成 `capture.mp4`。鸿蒙端下载 GLB 时再次核对清单大小、SHA-256、GLB 头和长度，先写临时文件再更名。服务端返回资产前也检查路径、大小及 SHA-256。数据没有写进 APK/HAP 资源或示例模型路径。

重启电脑后用 `scripts/Start-Backend.ps1` 启动本地服务；USB 重连后用 `scripts/Connect-ReconstructionDevice.ps1` 恢复 HDC 反向映射。当前仅为本机开发模式；将来换服务器时需配置后端访问口令、HTTPS 与用户授权流程。

## 真机实测

设备：已连接的 MatePad Edge / HarmonyOS 7 / API26。PC：NVIDIA GeForce RTX 5070 Laptop GPU，8151 MiB，驱动 616.92。通过 HDC USB 反向映射 `tcp:8787 -> tcp:8787` 与本机 `127.0.0.1:8787` 服务通信。测试期间临时使用 8788，结束后已恢复正式映射和服务。

1. 探针在鸿蒙应用私有目录写入**合成** MP4，调用 `/health`、65,539 字节二进制 `/echo`、创建任务、分块上传、封存和状态查询。真机日志：`SELF_RECON_TRANSFER_PROBE {synthetic:true,bytes:53849,echo:true,jobId:b1e8fa59307b3c9265eb3f66a08b82b3,state:queued,engine:not-verified}`。
2. Windows 固定目录中的 `capture.mp4` 为 53,849 字节；与测试原件的 SHA-256 同为 `7945e37bf0a3c38efcf24990e3a705f1576121596dcfa167c94cb3cfa8be3d6a`。任务清单为 `queued`。没有读、上传或删除用户的既有拍摄。
3. 为单独测返回路径，**临时**把公开示例 GLB 放到这个合成任务并标为测试资产；设备通过生产下载方法收到 553,116 字节，写到 `/data/storage/el2/base/haps/entry/files/models/b1e8fa59307b3c9265eb3f66a08b82b3/portrait.glb`。真机日志 `SELF_RECON_DOWNLOAD_PROBE` 与 `SELF_RECON_DOWNLOAD_FIXTURE_REMOVED` 均出现。随后删除平板和 PC 两端的测试 GLB，任务恢复 `queued`，保留合成 MP4 作为传输证据。
4. 一次性探针页面、合成 HAP 资源及测试入口已从正式构建移除；最终 HAP 重新构建、覆盖安装并启动。

## 尚未通过的建模环节

当前服务只接收、保存、校验和返回**已有**资产；没有从 MP4 解帧、估计相机位姿、拟合个人脸部、训练 3DGS、生成可编辑 Mesh/贴图的工作器。生产拍摄页结束录像后仍只保存在鸿蒙 `captures/`，尚未自动提交重建任务；当前 `downloadMesh` 也未接入主界面作品切换。因此这次验证**不等于**“拍摄本人 → 电脑重建 → 返回并显示本人 3D”。健康接口的 `engine:not-verified` 正确反映这一点。

本机 Python 环境：`pycolmap 4.2.0` 但 `has_cuda=False`，没有 PyTorch、gsplat，也没有已验证的 COLMAP/3DGS 训练运行链。显卡可见不等于重建程序已经可运行。[COLMAP 官方教程](https://colmap.github.io/tutorial)说明从多视角图像先恢复稀疏场景与相机位姿，视频应按需抽帧并保持视差；[gsplat 官方 COLMAP 示例](https://docs.gsplat.studio/main/examples/colmap.html)从已处理的 COLMAP 数据训练。[gsplat Windows 安装说明](https://github.com/nerfstudio-project/gsplat/blob/main/docs/INSTALL_WIN.md)要求核对 PyTorch/CUDA 匹配的预编译包或配置 Visual Studio 与 CUDA 构建环境。现有自拍角度灯只来自相对人脸偏航角，不能充当相机外参或重建质量证明。

后续必须完成：有来源和许可记录的 PC 工作器及隔离依赖；实际录制数据的多视角/相机参数质量门槛；真实 GPU 重建输出 GS 与可编辑网格、纹理及坐标映射；模型完整性/多角度/局部圈选/保护编辑验证；生产拍摄自动提交、任务恢复与成功后原子切换作品；真人授权测试的质量、耗时和失败路径。任何一步失败都应保留原作品，不用示例模型顶替。

## 回归结果

- 后端 `python -m unittest test_recon_transfer -v`：3/3 通过，包括分块与封存、授权/摘要拒绝、返回资产同长度篡改拒绝。
- `npm run test:camera-guidance`：通过，包括 11 档视角、横竖屏坐标与现有跟踪规则。
- API26 签名 HAP 构建、真机覆盖安装和启动：通过。视觉质感与真人脸部稳定性仍待用户实看；没有把日志当作画面验收。
- 模拟器、真实个人 3D 重建、3DGS 编辑与 PNG 从个人模型导出：本次未通过或未验证；不可由二进制传输测试推断成功。
