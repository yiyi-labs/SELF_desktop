# SELF：人脸测量、衣物表面与双端绘制实际对照

记录日期：2026-09-29。本轮是隔离研究，整体质量仍不通过。没有部署、回传、切换生产默认或覆盖旧作品。

## 1. 先回答本轮的五个问题

1. **双端差异确实有一项明显缩小，但不是切换读取格式的功劳。** R0 的 COMPACT→LARGE 未改善；仅降低 minPixelSize 没有改变像素。采用真实多视图背景表面并退役六个有证据的异常宽核后，参考 0111 的脸区 gsplat/PlayCanvas RGB L1 从 0.165531 降至 0.007430。与此同时背景内容丢失，因此这份结果仍拒绝。正常核控制资产差异小，极宽核差异大；不是 fog 问题，也没有靠调曝光、gamma 或对比度掩饰。
2. **新测量与共享三维求解已实际运行，但尚未获得可靠的面部细节提升。** 102 条新物理轨迹、507 个观察，独立共享 XYZ 求解后融合到连续表面，更新 476 个顶点并同步高斯中心和协方差方向。拟合与第三观察中位误差下降，但五个源视角超出预先容差，第三观察尾部没有改善。候选恢复，未用外观训练掩盖几何失败。
3. **衣物实际建出了胸前纹理附近的有限表面，并完成 240 步真实 Adam 训练。** 不是复制旧 348 个种子：29 个多视图支持点形成 33 个有限三角、6857 个表面高斯。能看到部分印花边缘，但仍有大片缺口，未建成连续衣领和肩部。完整衣物有效区域约 97.1% 的像素 alpha<0.8，不能用局部覆盖好宣称衣物通过。
4. **背景没有同时做到减少遮脸与保留内容。** OpenMVS 实际产生 7 张深度图和 27970 个融合点；取有多视图支持的局部物理表面建立 5002 个高斯并训练 180 步。脸前背景贡献显著下降，但全部 13 个检查视角的 room RGB 都退化。六点退役的修正版零训练重放仍失败，保留证据并恢复原状态。
5. **头发、镜框、完整肩颈仍未修复。** 2917 个旧发壳点没有被当成真实发型验收；没有新增可靠镜腿/镜框三维曲线，也没有完成颈皮肤与衣领的接触、遮挡及上身连续性。本轮没有把分类变化、磨平或加亮当成结构修复。

可保留的是新测量与表面接口、独立上身运动接口、真实深度工具接入、训练/恢复事务及显式 UID 退役合同；**不能保留为质量通过资产的是 F、C、B 的候选参数。**

## 2. 冻结身份、范围和恢复

- 工作区 W：`C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay`。
- 起点：`9c62434bc4dd873556a72f860078ca2e5c651e25`，分支 `codex/reconstruction-v3-audit-20260928`。没有按旧提交强制恢复。
- 原工程 P：`D:/STUDY/College/mine/olay`，HEAD `f68587bb34f8970d21bda9231e15b2536a33df97`。结束时 HEAD 与 porcelain 状态和开始时完全相同。
- R0：`backend/.sources/fullframe-surface-patch-20260929-b/R0-frozen.pt`，SHA-256 `2468edc379f8b76eac97fccfbf9e9a4c775f980102b95283ee15b2dc4cee7cb8`。
- R0 冻结 T2 PLY：`backend/.sources/haze-shared-surface-context-20260929-a/D/R0-frozen-T2.ply`，SHA-256 `9fd631a133065c4e02fced9f650914abacd0a716d63f33afe3eb7df49c2cc094`。
- 原视频 SHA-256：`7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`；prepared 的 preparation.json SHA-256：`e67d4dce02f9874e0befe15486532f80458f8a62a23221324fcc5abefc2e5301`。
- 私有输出根目录：`C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/surface-evidence-face-clothing-20260929-a`。没有覆盖已有 run-id，失败目录继续保留。
- FLAME Open、gsplat 1.5.3、head-local SH1、原生全幅后切 ROI 保持。没有升级原 PyTorch/PyCOLMAP、改驱动或 CUDA；没有修改生产查看器、AI、OLAY、上脸、故事、签名或 USB。

`receipts.json` 保存本轮 574 项源码、参数、图像、资产、检查点和视频文件摘要；`before.json`、`protection-check.json` 保存保护检查。训练目录各有当次 algorithm-source，根目录 final-code 保存最终修订代码。两者在明确修过的接口处不完全相同，不能用最终源码冒充当次执行源码。

F 没有 Adam（使用真实非线性最小二乘）；C/B 保存 init/mid/final、实际 Adam、RNG、采样状态、UID、来源与绑定。C 早先 `restored.pt` 只恢复模型、没有完整回退 Adam，这个诊断失误已保留；随后修正恢复代码，并另存、核对 `restored-complete.pt`，模型、Adam 绑定及初始状态、采样器均恢复。旧文件不被称为精确 resume。

这些资产在当前磁盘上保留，**尚无本轮独立离线备份**。Git 不包含私人视频、模型权重、PLY 和面容图，也不能替代它们的备份。

## 3. R：同资产单因素与正常核控制

读取本机 PlayCanvas **2.22.4** 实际源码和常量，使用 `GSPLATDATA_LARGE`，不是虚构 float 模式。LARGE 仍含半精度/打包量化。minPixelSize 只用于剔除诊断。

同一 R0、相机、原生 1080×1920、同 near/far、K、颜色空间、gamma、预乘 alpha 读取与行方向。隔离浏览器实际绘制；没有变更 AA、曝光、色调、排序或 fog。使用本机 Chrome 的 SwiftShader，不能据此声称鸿蒙设备性能。

| R0 配置 | 脸区 PC↔gsplat RGB L1 | room PC↔gsplat RGB L1 | 结论 |
|---|---:|---:|---|
| COMPACT，minPixelSize=2 | 0.165531 | 0.191948 | 冻结原始对照 |
| LARGE，minPixelSize=2 | 0.165585 | 0.192849 | 不改善 |
| COMPACT，minPixelSize=0.2 | 0.165531 | 0.191948 | 实际像素相同 |

另有有限平面、折角、细线与前后遮挡的控制资产。正常版本：COMPACT RGB L1=0.004665、alpha L1=0.009830；加入一个极宽核：RGB L1=0.209422、alpha L1=0.413727。LARGE 分别为 0.007407 / 0.299447，没有救回极宽核。控制指标在两端 alpha>0.05 的并集上计算，不与原片人物质量指标混用。

这支持将重点转向异常宽表示，但不是逐项排除了共有中心深度排序、核尾截断或投影近似；正常核也不是逐像素完全一致。没有取消半径上限去复制灰雾。两个候选配置均不合入生产。

[原片、gsplat、三种 PlayCanvas 配置对照](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/surface-evidence-face-clothing-20260929-a/R/factor-comparison.png)

## 4. F：新二维测量、共享 XYZ、连续表面

### 实际方法

新阶段使用训练图像的亚像素特征，串行/直接跟踪循环检查，再以对称 25×25 patch ECC 平移细化，并检查前后向、第三视图和局部清晰度。选择静稳上部面部，排除明显嘴部表达与眼镜区域；不读取开发/回归 RGB 选点。不称为完整 PixSfM，也未安装其旧依赖。

10 个短窗口获得 102 条物理 track、507 个观察。每条 track 只有一个自由 XYZ；由原连续表面初始化，保留软先验和有界位移。固定 K、F、身份、尺度与表达先验，按已有局部形变传输到各观察。源与目标都进入稳健残差；每条 track 最后一个第三观察不进入该点求解。SciPy trust-region/soft-L1 合计 931 次函数求值，不是旧的 12 控制点 / 120 Adam 步。

数据 Jacobian 在像素尺度/参数单位规范化后检查。102 条达到当前条件奇异值比阈值，但这只说明**固定 F 和形变模型条件下**的局部可辨识性，不能证明相机无系统误差或深度是测量真值。最终 63 条用于连续表面融合；固定高斯数量、UID、绑定拓扑、颜色/alpha，更新 476 个顶点，最大位移 0.0010165 头局部单位。局部基底与协方差方向同步。

### 结果及不放行原因

| 连续表面重投影 | 原状态 | 修正后 |
|---|---:|---:|
| 拟合观察中位数，405 项 | 1.6325px | 1.3784px |
| 拟合观察 P90 | 5.2606px | 4.8056px |
| 第三观察中位数，102 项 | 2.5228px | 2.1994px |
| 第三观察 P90 | 7.0635px | 7.1044px |

0002、0008、0022、0133、0147 超出预先记录的每视图中位增量 0.5px / P90 增量 1px 容差。源图初值接近零源于射线构造，不是绝对真值；本轮不把它永久定成 0.35px 硬门限。但也没有事后放松预先规则来让候选通过。

原 8 开发 / 6 固定回归未换掉，另保留 0028/0042 绘制。0028 的固定脸区 RGB L1 为 0.017870→0.018036；0042 为 0.018720→0.018686。0042 仍只有 1 条有效测量（3.2075→2.4587px），不能据此优化 6DoF。0028 没有进入短窗口的共享点求解，不隐瞒成“全部视角都有新约束”。

没有观察到足以支持放行的稳定真实细节改善。几何失败后恢复 R0，**没有运行 G1 外观恢复，也没有伪造同预算 Gctrl 结果**。本轮 F 的实际优化是非线性几何求解；GPU 用于连续模型绘制与回归，不宣称新增了面部 Adam 外观训练。

最初 F 运行在已完成点求解后，因指标键 `l1` 与实际 `fixedRgbL1` 不匹配而中断报告。修复读数适配后复用已保存 tracks，未再重复求解；两个目录及日志都保留。38.74 秒仅是缓存恢复、表面融合和评价耗时，不是首次跟踪与求解总耗时。

[固定局部头部：原片 / gsplat / PlayCanvas](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/surface-evidence-face-clothing-20260929-a/final-evidence/dual-renderer.png)。该局部 PLY 双端脸区 RGB L1=0.004972、alpha L1=0.003460；显示一致不代表几何改善通过。

## 5. C：独立上身运动、真实 MVS 尝试和衣物训练

### 工具与合同

独立安装官方 [OpenMVS v2.4.0](https://github.com/cdcseacave/openMVS/releases/tag/v2.4.0) Windows portable 到 `backend/.sources/tools/openmvs-2.4.0-cpu`。提交 `58117204c86bbb11a0b25b26a8987676cf11274d`；官方 ZIP SHA-256 `0c31660c15c9ebc4c106873cf67564d9570d404aef7a6403451da1b6178b2167`，与官方 release digest 相同。实际运行 InterfaceCOLMAP 与 DensifyPointCloud；没有调用不存在的 PyCOLMAP dense CLI。

[AGPL-3.0 许可](https://raw.githubusercontent.com/cdcseacave/openMVS/v2.4.0/LICENSE)已保存，独立进程不豁免分发/源码义务。本轮仅离线研究，不默认加入产品分发包。

导出明确 imageName/ID、去畸变 PINHOLE K、W2C、原始 RGB、掩膜与尺度。mask 是有效观察掩膜，RGB 没涂黑。深度阶段 540×960，后续颜色监督仍用原生 1080×1920。没有将低分辨率深度当成原生像素纹理训练。

### 实际尝试及阻塞

评估 8 个短窗口。静态上身假设均未通过独立检查；依据纹理跟踪数和误差选择训练 0022—0028 七张图，而非硬编码衣物 logo。B(t) 与头 F 分离，整段仅 6 个刚体速度变量，固定参考 0025 的 B=I、固定世界 C/尺度，不允许逐帧自由 scale/位姿。

一次受限运动求解保留 30 个点；对称端点重新提议后为 29 个点，均未满足预设 60 点及运动质量条件。诊断导出仍实际送入 OpenMVS：导入 7 图 / 30 点，深度阶段发现 0 个可用邻接对，**0 深度图、0 稠密点**。程序退出码 0 不算成功。反向端点这一次有限尝试没有消除阻塞，未继续全局匹配或重复调阈值。

因此衣物的硬缺口是：当前短窗口下可靠分布的上身局部对应、运动和有效深度基线仍不足。不是缺可执行工具；同一工具在静态房间确实产生了深度。

### 实際训练产物

为不让工具失败替代全部衣物工作，使用已有 29 个三视图以上支持的点，构建有界有限三角：不外推、限制边长、各点共享可见观察及真实颜色。33 三角，6857 高斯，头与上身不共用 F。固定不可靠几何，只训练 SH、alpha、尺度和旋转 240 步，保存 init/120/final，真实 Adam 和采样状态。

| 训练观察 | 固定片区初始 RGB L1 | 240 步后 |
|---|---:|---:|
| 0022 | 0.056915 | 0.018762 |
| 0023 | 0.063980 | 0.022536 |
| 0024 | 0.053223 | 0.027380 |
| 0025 | 0.044414 | 0.054243 |
| 0026 | 0.083677 | 0.083011 |
| 0027 | 0.082923 | 0.054600 |
| 0028 | 0.068525 | 0.032075 |

这些都是训练观察，不是独立衣物质量测试。0025 还变差。有效片区 alpha<0.8 约 0.26%—0.47%，但完整衣物 mask 约 97.1% 未覆盖。低局部误差不能掩盖片区之间的黑洞。

[实际支持范围](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/surface-evidence-face-clothing-20260929-a/C-surface/supported-patch.png)；[0022 原片 / 旧 348 种子 / 新训练片区](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/surface-evidence-face-clothing-20260929-a/C-training/final-images/frame_0022.png)。可见新的印花边缘片段，但中央和外侧大量内容缺失。**仅实际训练了胸前的一小块，不是衣领—肩部完整连续重建。**

全场 T2 同时绘制冻结人像、原房间与新衣物候选，暴露未覆盖部分，没有交替隐藏组件。固定参考 0025 导出并实际 PlayCanvas 绘制，双端脸区 RGB L1=0.005671、room=0.062513。该参考相机不同于 R 的 0111，不能直接用这两个值宣称 R0 同条件改善。

## 6. B：真实背景表面替换及失败回退

静态 0133—0139 七个训练观察，970 条可靠静态地图锚。全可见 room mask 包括白墙/门板等低纹理内容，不使用 SIFT 支持区域替代可见区域。

OpenMVS CPU 实际用时 28.84 秒，7 张深度图、1312743 个原始深度样本，融合得到 **27970 点**（约 2% 留存；不能把原始深度样本数当独立支持点）。深度/法线、view_indices 和权重经解析保存，没有把列表属性丢掉。有限目标区域由真实原片物理位置定义；不同深度表面不强拟合成单平面。

取 5002 个有效多视图表面点，使用法线协方差与受限像素间距，训练 180 步 SH/alpha/尺度/旋转；所有组件同一次光栅化，人像完全冻结，没有 T3/T4 面部更新。未用单点椭球扩整面墙，也未统一推远背景或降低全部 opacity。

### 发现并修复的退役范围错误

初次 `B-replacement` 实验错误地退役了 source 13378 的全部 14 个家族点。来源家族不是物理表面，不能以家族身份一概删除。这次执行源码及失败参数完整保留。

随后训练入口改为强制接收证据哈希和显式 UID 清单，校验 namespace/sourceID/UID 唯一性。依据原贡献审计中的 6 个 UID：27814、27972、28096、28578、28736、28860，只保留这 6 个退役；恢复同源其余 8 个。`B-scoped-replay` **不创建 optimizer、没有新增训练**，直接用已训练 5002 点做冻结重放。不能把这份结果写成“按 6 点范围重新训练 180 步”。

### 内容与遮挡联合判断

| 同一参考 0111，全场共同绘制 | R0 | 六点范围重放 |
|---|---:|---:|
| 脸区来自 room 的平均贡献 q_room | 0.427611 | 0.004342 |
| 脸区对原片 RGB L1 | 0.190133 | 0.030471 |
| room 对原片 RGB L1 | 0.047382 | 0.259223 |
| 脸区 PC↔gsplat RGB L1 | 0.165531 | 0.007430 |
| room PC↔gsplat RGB L1 | 0.191948 | 0.043978 |

13 个检查视角仍全部出现 room RGB 退化。恢复 8 个同家族点修正了事务范围，却不足以解决真实内容缺失。当前有限物理表面的观察范围和覆盖不能接替这些旧宽核在其余真实背景区域承担的内容；也不能为了补回内容继续保留错误遮脸的雾。没有将 q_room 下降或两个渲染器一致当成重建质量通过。

[同一参考：原片 / gsplat / PlayCanvas](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/surface-evidence-face-clothing-20260929-a/B-scoped-replay/dual-renderer.png)。图中真实背景大范围缺失、头发帽壳和衣物模糊都仍清楚可见。这是拒绝候选的证据，不是可用作品展示。

[固定同一 PLY 的连续绕看](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/surface-evidence-face-clothing-20260929-a/B-scoped-replay/orbit/fixed-asset-orbit.mp4)：gsplat 1.5.3，48 帧，24fps 编码，原生 1080×1920，±18°水平/±6°垂直的相机运动；不是实时设备 fps，不是逐角度换模型。相机数组和资产摘要与视频同目录保存。这一小范围也不能代表全部真实观察方向已通过。

## 7. 固定资产与双端身份

| 资产 | SHA-256 | 状态 |
|---|---|---|
| F 局部头部 `final-evidence/fixed-F-local.ply` | `29118cb7ff195d780e2a337f86d4af70d3db6fe481b2128095f601e166bcb7d9` | 11970 点，几何拒绝，实际双端 |
| C 全场诊断 `C-training/fixed-T2-garment-diagnostic.ply` | `fe3fd1c8067139949d46d79df2c9cd491f5fd46e52c3c7cd40f5253be0ed312d` | 44881 点，衣物不完整，实际双端 |
| B 首次 14 点退役 `B-replacement/fixed-B-T2.ply` | `7dfe27e1bd0909f3dc2abbe81d9d5f6aedfeaa851bb9a0178b99eb0d0d189ba5` | 43360 点，错误范围诊断，不使用 |
| B 六点范围 `B-scoped-replay/fixed-scoped-B-T2.ply` | `b769e83b82e304b8607874aa827c840f8cdc67b7139ec3c9c47c2f40ea12fadf` | 43368 点，背景内容失败，实际双端与固定资产绕看 |

每份候选保留 imageName、参考时刻、K/C、source hash、asset hash；identity sidecar 保存 UID、来源 namespace、source ID、三角与重心绑定。不同参考时刻的 PLY 不能相互冒充。同一项比较内始终使用固定资产，不按观察角更换。

## 8. 实现文件、测试、资源

| 能力 | 本轮新增文件 |
|---|---|
| 共享阶段加载、测量、MVS 属性与退役合同 | reconstruction_evidence_stage.py / reconstruction_surface_evidence.py / reconstruction_mvs_contract.py |
| F 几何与连续表面 | run_surface_geometry.py |
| C 窗口、独立运动、表面、训练 | run_surface_window.py / run_surface_body_motion.py / run_garment_surface_patch.py / run_surface_component_training.py |
| B 真实静态窗口和表面替换 | run_static_surface_window.py / run_room_surface_replacement.py / audit_room_retirement_scope.py |
| 双端、控制资产、固定资产绕看及报告 | scripts/probe-surface-render-contract.mjs；backend/audit_surface_*.py |

实际 stage 通过 manifest/参数加载 prepared/checkpoint/window，不接入生产。证据聚合脚本可针对本次 run 定位文件，但不被当作生产重建入口。

10 项合同/回归测试通过：共享三维点、亚像素 patch 平移、RGB 与 imageName/ID、MVS list 属性和截断、显式退役范围及错误身份拒绝、原共享表面梯度/协方差传输/序列化。测试通过只说明这些合同，不代表画质通过。

| 实际阶段 | 耗时 | PyTorch 峰值 allocated / reserved |
|---|---:|---:|
| F 缓存恢复、连续表面及评价 | 38.74秒 | 401.30 / 436 MiB |
| C 240步、评价、输出全阶段 | 36.90秒；其中训练+评价15.22秒 | 670.57 / 1040 MiB |
| B 180步、评价、输出全阶段 | 112.46秒；其中训练+评价38.55秒 | 728.52 / 1002 MiB |
| B OpenMVS CPU 深度 | 28.84秒 | CPU进程峰值工作集约189.25MB，非显存 |

这些不含完整视频准备，不是端到端 2—3 分钟成绩。allocated/reserved 是当前 PyTorch 阶段记录，不含所有外部进程的整机显存峰值。RTX 5070 Laptop 8GB 本轮可用，没有 OOM；当前有限研究不能证明最终完整密度也不会受显存限制。

## 9. 复现方式与执行差异

实际命令参数、配置、源码及 stdout/stderr 保存在各阶段目录与本报告目录。下面是参数化入口，必须使用新的输出目录；不要重新占用本次 run-id。

WSL Ubuntu-22.04，Python `/opt/self-reconstruction/venv/bin/python`；工作目录 W/backend；环境 `PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=4 CUDA_HOME=/usr/local/cuda-12.8 TORCH_CUDA_ARCH_LIST=12.0 MAX_JOBS=2`。

```bash
ROOT=.sources/surface-evidence-face-clothing-20260929-a
PREP=/mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e
PY=/opt/self-reconstruction/venv/bin/python
# 使用本轮冻结输入，输出另一个独立目录。以下是复现实验入口，不在报告生成时执行。
$PY run_surface_geometry.py --manifest "$ROOT/stage.json" --out .sources/surface-evidence-reproduce-F
# 只复用已实际求解轨迹进行几何/渲染恢复：
$PY run_surface_geometry.py --manifest "$ROOT/stage.json" --tracks-cache "$ROOT/F-geometry/tracks.json" --out .sources/surface-evidence-reproduce-F-cached
$PY run_garment_surface_patch.py --window "$ROOT/C-motion-multiseed" --out .sources/surface-evidence-reproduce-C-surface
$PY run_surface_component_training.py --manifest "$ROOT/stage.json" --surface .sources/surface-evidence-reproduce-C-surface --steps 240 --out .sources/surface-evidence-reproduce-C-training
$PY run_static_surface_window.py --prepared "$PREP" --reference frame_0136.png --out .sources/surface-evidence-reproduce-B-mvs
$PY -m unittest -v test_reconstruction_surface_evidence test_reconstruction_shared_surface
```

OpenMVS 实际运行参数（Windows portable，`DIR` 为已导出的单阶段目录）：

```text
InterfaceCOLMAP --working-folder DIR --input-file DIR/colmap --image-folder DIR/colmap/images --output-file DIR/scene.mvs --max-threads 4 --normalize 0
DensifyPointCloud --working-folder DIR --input-file DIR/scene.mvs --output-file DIR/dense.mvs --max-threads 4 --resolution-level 1 --max-resolution 1920 --min-resolution 640 --number-views 5 --number-views-fuse 3 --ignore-mask-label 0 --iters 3 --geometric-iters 2 --estimate-normals 2 --estimate-colors 2 --estimate-roi 0 --crop-to-roi 0 --tower-mode 0 --normalize-coordinates 0 --remove-dmaps 0
```

最终代码的背景训练入口强制 `--retirement`：

```bash
$PY run_room_surface_replacement.py --manifest "$ROOT/stage.json" --mvs "$ROOT/B-mvs" --source-id 13378 --retirement "$ROOT/B-scoped-replay/retirement.json" --out .sources/surface-evidence-reproduce-B
```

**上述六点范围重新训练命令本轮未执行。** 本轮实际 180 步是首次 14 点版本，源码在 B-replacement/algorithm-source；其后使用 audit_room_retirement_scope.py 进行六点范围零训练重放。不能将最终修复代码与首次训练结果混写成同一次运行。

Windows W 根目录实际 PlayCanvas 入口：

```text
node scripts/probe-surface-render-contract.mjs backend/.sources/surface-evidence-face-clothing-20260929-a/R large
node scripts/probe-surface-render-contract.mjs backend/.sources/surface-evidence-face-clothing-20260929-a/R fine
node scripts/probe-surface-render-contract.mjs backend/.sources/surface-evidence-face-clothing-20260929-a/B-scoped-replay baseline
```

该脚本检查资产 SHA，按递增 attempt 建立独立输出；不改原查看器。合成控制和 C/F 的同资产绘制也使用该入口。

## 10. 保留、拒绝与下一项最小工作

- **子能力保留**：真实二维 patch 细化与共享 XYZ 求解接口；连续表面/协方差传输；独立 B(t) 与真实衣物片区训练；OpenMVS pinned CPU 导入/深度与完整列表解析；显式 UID 退役及完整恢复；同一资产真实双端比较。
- **候选拒绝**：F 多视图几何稳定性不足；C 只有不完整胸前纹理片区、运动未通过；B 去掉遮脸宽核后真实环境内容明显丢失。它们没有互相拼成“通过”资产。
- **未完成**：衣领—肩部—胸前连续面及可靠运动、头发真实外表面、镜框空间曲线、头颈衣领接触、背景跨视角完整替换域、最终完整 E1—E5。
- **未测**：本轮 HarmonyOS、真机/平板显示和交互性能；没有部署或回传。PC 实际绘制不等于鸿蒙验收。

下一项最有价值的最小工作是：**在本轮同一衣物短窗口中，先增加分布于衣领、肩线和胸前的可靠跨视图约束，对世界 C 与独立 B 的残差分开核对，达到预先规定的运动/基线条件后，仅重跑该窗口深度与有限衣物表面训练。** 不先延长当前 240 步，不靠局部印花拟合吸收整体姿态误差。当前工具已可用，缺的是分布和局部运动的可信几何输入；已有视频是否能补齐应先验证，不自动要求用户重拍。

F 的后续也应先处理分布充分的稳定面部观测与局部姿态系统误差，不靠 0042 单点求姿态；B 则需要扩展到真实可见物理表面，而非旧家族或单点影响域。两者都没有理由回到全局调 alpha/scale 或重新做 FLAME 版本 A/B。

本轮代码按能力分别提交，完整提交 ID 见 commits.json；只包含显式本轮文件，原有未提交内容保持。当前结论是**实现与局部实验有进展，整体作品仍不可发布**。
