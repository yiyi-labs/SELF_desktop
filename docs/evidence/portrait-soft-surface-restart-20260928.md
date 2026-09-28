# 2026-09-28：人像软表面实施接续记录

用户正在主动重启 Windows。此时停止训练和设备操作；不自动重启或更新驱动。

## 实际进度

- 已完整读取下载目录的新要求和 attachments/02012aad-5679-4c45-8818-526bd5806aae/已粘贴的文本.txt，以后者作为实际实施请求。
- 已读取当前交接、v2 证据、JSON、当前组件和训练源码、E 算法快照哈希与依赖。原 E1—E5 保留。
- 当前生产 worker、应用、签名、PlayCanvas、编辑、USB/HDC 与故事文件未变；冻结文件逐项核对见同名 checkpoint JSON。
- 已新增 `backend/reconstruction_portrait_model.py`，不是生产默认。其 LocalPortraitModel 导入全部旧 11,715 点（8,798 表面+2,917 已知粗壳头发），用同一参数支持 T0/T1 坐标转换；不再在迁移时静默筛掉表面点。
- 核心代码包含共享表面残差、可训练重心/法向偏移、连接三角 walking、中心与协方差平方距离软约束，以及父点替换/Adam和来源同步的有限恢复事务。
- 以上仅通过 Python 语法编译。尚未进行运行时回归、CUDA 训练、画质对照或新资产导出，不能称软表面方案已验证。

## 显卡诊断

Windows：NVIDIA RTX 5070 Laptop GPU 的 PnP `IsPresent=false`、Status=Unknown；`Win32_VideoController` 当前只有 Intel Arc 140T，NVIDIA 驱动缓存版本 32.0.16.1714。WSL 2.7.10 / Ubuntu 22.04 / Torch 2.8.0+cu128：CUDA=false；NVML 报 GPU access blocked by the operating system。Windows nvidia-smi 同样不可用。

尝试一次 `pnputil /scan-devices`，Windows 返回 Access is denied，未作修改。已排除“仅在 WSL 中不可用”，但尚未确定是联想显卡工作模式、驱动还是硬件电源状态。不能判断显卡损坏，也不应直接重装 CUDA/Linux NVIDIA 驱动。

## 接着做

1. 用户重启回来后，先查 Windows PresentOnly 显卡和 WSL CUDA。没有恢复时继续 CPU 代码检查，不反复重启。
2. 先运行核心 CPU 回归：导入所有点无筛选、尺度只一次、协方差与 SH、跨边 walking/barrier、皮肤厚度梯度、事务完整 rollback 与 Adam 重映射。审查 CandidateTransaction 参数身份和子点元数据。
3. 使用当前 E 的 preparation/local_geometry 与已有 head-local-sh1 900 步参数，完成实际数据上的 T0/T1 原生投影/协方差检查。注意 rectified/refitted F 不自动等价于旧非整流训练图片；T0/T1必须彼此完全一致。
4. 实现可复用 SceneAssembly/训练入口，T2保留全部头部参数+冻结环境/身体，T3只环境接缝更新但全部共前向，T4一直保留所有可靠局部 F 的人像监督（不能把无 C 帧丢掉或拿来训练房间）。不修改生产 worker，直到实际质量通过。
5. 再做强/软同条件、有限容量恢复对照与新部件结构。没有新的有效几何信息，不重复原失败头发/NCC/SIFT/ALIKED实验；镜框须真实跨视图线对应/三角化。
6. 实际训练后导出一个固定状态 PLY与原片对照/连续绕看；坏候选不回传，旧作品保持。

实际源片：`backend/.sources/quality-geometry-20260926-temp/capture.mp4`，SHA-256 `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。
输入局部参数：该目录 `flame_open_e2_20260927/private-optimized-subset-900-footprint-1.00-sh1-head-local-20260927/private-optimized-parameters.npz`，SHA-256 `308da67a299dc98855fa4d3403197130811ec87d96dcb7ad967eee92950d9e46`。
可复用准备：`backend/.sources/integrated-components-v2-20260928-e`。准备缓存仍是研究相机，不是发布认证世界相机。

新代码尚未完成运行时核验，不能接生产。此次没有新模型，也没有平板安装/回传。
