# SELF：薄雾、共享表面与背景连接的有限修缮记录

日期：2026-09-29。范围：既有隔离 W 内后端研究。未部署、未回传、未切换生产默认，原 P、应用、签名、USB、旧作品、编辑与故事未改。本轮不是完整人像发布成功。

## 先回答结论

1. **薄雾确有模型原因，同时查实训练器与查看器的绘制差异。** 同一个 R0 PLY、同一个参考 C/K、1080×1920 原生画布，gsplat 的脸部被大块灰色 room 核覆盖；PlayCanvas 2.22.4 的脸部较少遮灰，但环境覆盖损失明显。不是“显示端已排除”，也不是启用了 fog：实际 fog=none、toneMapping=0、exposure=1、无后处理。两者脸区原始预乘 RGB L1 差 0.16553。这是渲染一致性未通过，不能把较好看的一边视为模型正确。
2. **共享表面已实际训练，并同步中心和协方差方向；尚未同时改善全部观察。** 固定 F 的 180 步表面优化失败；随后从完整 R0 恢复，执行一次 120 步有限交替细化，源锚最大漂移降至 0.553 px、目标中位误差从 2.645 降到 1.483 px，但第三视图尾部及两个具体观察退化。几何候选均拒绝并完整恢复。没有在失败几何上继续 G1 外观恢复。
3. **背景未完成无损替换。** 在不同静态位置找到 239/215/243 个具有至少三次 room 观察的轨迹，得到 41/41/45 点的有限共面候选；它们仅覆盖所检查局部窗口内该来源家族贡献的 30.40%/19.86%/17.43%。这些候选跨相框、物件及柜侧附近，物理表面边界仍未确认；不能覆盖整组宽核所承担的背景。没有执行删除、统一降 opacity、推远背景或再次把九个点收回单点椭球。
4. **头发、镜框和衣物没有进行新的几何修复。** 2917 个旧头发点和 348 个身体种子保留；本轮面颊变化不代表真实发型、镜架、衣领或肩部通过。
5. **可保留的是代码子能力与证据，不是本轮画质候选。** 共享锚、表面传输、完整恢复、原生同相机显示比较可以保留；两个 G 几何候选和纯外观 Gctrl 都不作为新的质量基线。完整 T2 仍失败，没有新 T3/T4，没有最新鸿蒙验收。

## 冻结现场、资产身份

起点 W HEAD：`64eaf17a3c7ca2f0ed1bfd2c21d6d0232b5b5c6b`，分支 `codex/reconstruction-v3-audit-20260928`。
原先五项未跟踪内容完整保留，见 `before.json`；没有 reset、clean、stash、rebase、amend 或历史 run 删除。

| 对象 | 身份与用途 |
|---|---|
| 恢复 R0 | `fullframe-surface-patch-20260929-b/R0-frozen.pt`，SHA-256 `2468edc379f8b76eac97fccfbf9e9a4c775f980102b95283ee15b2dc4cee7cb8` |
| 本轮 R0 冻结 T2 PLY | `9fd631a133065c4e02fced9f650914abacd0a716d63f33afe3eb7df49c2cc094`，38372 点；与先前保存的同状态诊断资产 hash 相同 |
| 上轮被拒 R2 PLY | `507fe2a8cb9d70f279f84cf9a739b891e8e2d32abccebb66fe4c0eab9296ea1e`，38723 点；只用于 D 对照，未作为 G 初始化 |
| 本轮被拒共享表面诊断 PLY | `488371a16801352af88cba64e4ee085ec68ab76769beb413a08605dfb186f6e2`，38372 点；固定参考 `frame_0111.png` |
| 源视频 | `capture-1790410633104.mp4` 对应 SHA-256 `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf` |
| 平板当前作品 | 本轮未连接读取其资产 hash，身份未核验，不能当成以上任一份诊断 PLY；没有向平板写任何新资产 |

研究根目录：`W/backend/.sources/haze-shared-surface-context-20260929-a/`。每个阶段独立子目录；206 个输入文件、133 个检查点/参数/结果文件及源码 hash 见 `receipts.json`。私人照片、轨迹、检查点、PLY、视频未进入 Git，也未上传；仍只在本机研究目录，Git 提交不等于这些文件已有独立备份。

## D：同资产显示分离

实际运行：Chrome / SwiftShader WebGL2 + 本地锁定 PlayCanvas 2.22.4，与 gsplat 1.5.3。同参考时刻、同一完整场景 PLY；使用完整原生 K、C、near/far，不使用小 viewport 代替裁剪。CV→GL 相机矩阵转换最大误差 `1.70e-7`。没有改原生产查看器。

运行时确认：canvas 与 CSS 均 1080×1920，deviceScaleFactor=1，静止 maxPixelRatio=1；完整 GSplatResource、没有 LOD 资产，38372/38723 点，预算 1000000；unified=true，工作数据格式 compact，antiAlias=false，minPixelSize=2，radialSorting=false；gamma=1，toneMapping=0，exposure=1，fog=none，postEffects=0。WebGL premultipliedAlpha=true。本轮比较直接读取 GL 原始预乘 RGBA8、翻转行序后与训练器合成输出比较，没有错误地对 PNG 再次乘 alpha，没有加光、锐化或改对比度。

原生产源码存在移动降分辨率和静止恢复逻辑；隔离测试全程固定原生画布，**没有实测最新平板上的该恢复行为**。本轮也不是生产 ArkWeb 外壳端到端验收。

| 相同 R0 资产的固定 mask 指标 | face | room | 全幅 |
|---|---:|---:|---:|
| PlayCanvas 对 gsplat RGB L1 | 0.165531 | 0.191948 | 0.175980 |
| alpha L1 | 0.002335 | 0.216849 | 0.167670 |
| gsplat 对原片 RGB L1 | 0.190133 | 0.047382 | 0.105711 |
| PlayCanvas 对原片 RGB L1 | 0.032496 | 0.183777 | 0.171023 |

R2 同样出现该方向差异，脸区两引擎差 0.165444。不能以较低的 PlayCanvas 脸区 L1 忽略其背景损失，也不能用较低的 gsplat room L1 放行盖在人脸前的背景。

直接核对 2.22.4 源码：
- `gsplatOutput.js` 的当前组合保留输入 gamma 数值颜色，没有启用 fog/tonemap 分支；这里不存在“关闭 gamma 变清晰”的修复。
- `gsplatCorner.js` 有 `min(1024, viewport.x, viewport.y)` 的宽核半径限制，与 gsplat 的透视 clamp/足迹实现不完全相同。
- `gsplat` 片元核使用归一化的 `normExp` 尾部，统一工作缓冲还量化 scale、quaternion、alpha 和颜色；排序也是中心深度近似，不能只因为两边都异常就排除共有近似。
- 用原始 PLY 参数代入当前 shader 半径公式，有 67 个正深度 room 核触及半径限制。在 gsplat 的完整遮挡计算中，这些核对当前固定脸区的 alpha×T 累积贡献占总贡献 42.75%。这是“受限制点的贡献统计”，**不是薄雾的责任百分比**；尚未分别控制量化、尾部、投影和排序的所有交互，不把它们概括为已修复的显示 bug。

[原片 / gsplat / PlayCanvas / 三倍差值图](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/haze-shared-surface-context-20260929-a/D/playcanvas-01/R0-comparison.png)。差值图放大仅用于定位；前三栏原片与绘制没有美化。

D 的结论是：宽背景核已使模型本身不可靠，查看器还会把这些病态核显示成另一种覆盖结果。此处停止显示分离，不换引擎，也没有通过改变显示参数掩盖质量问题。

## G：固定拓扑、共享表面真正优化

新增 `reconstruction_shared_surface.py`：
- 一个连续真实纹理 track 对应一个不可变 triangle/bary 锚点。一次源射线求交后固定绑定，源、目标、后续图都通过同一表面投影；没有每对图独立三维点，也没有每轮重新求交。
- 仅从训练观察构造 56 条至少三次观察的连续轨迹，共 258 个像素观察。原生 LK、每段前后向检查 `<0.75 px`、训练语义/未知区排除；不使用开发 RGB 选控制点。
- 每五个 seed 保留一个完整 track；每条轨迹最后一个观察单独保留。权重固定来自前后向可靠性，不作为可训练参数。保留链内跟踪身份；不把跨时间缺口的相似纹理擅自认作同一物理点。
- 12 个局部控制点、36 个自由度组成连续紧支撑共享残差，邻接边界渐止；初始位移为零，范围上限为观测原生像素尺度的 3 倍，固定低频身份/表达/K/C/尺度。
- 表面位移作用到每帧表达 mesh；高斯中心、法向 offset 和局部三角基底共同更新。原协方差通过可微局部旋转传输，保留原轴长、颜色、alpha 和头发状态。SH 仍是原 head-local SH1，不把它当皮肤材质或随意加阶数。

数据 Jacobian 为 310×36，36 个奇异值完整保存，最大 7.47509、最小 0.00015267，相对 `1e-4` 阈值有效秩 33。存在弱约束方向；不把可求梯度当成深度已精确恢复。

### 固定 F 阶段：180 个 Adam 步

没有 RGB 反传，没有外观参数更新。最终共享位移最大 2.124 原生像素尺度，三角最小面积比 0.9508、最小法向余弦 0.99945。实际更新了表面而不是只优化姿态。

| 像素误差中位数 | R0 | 固定 F 后 |
|---|---:|---:|
| 源锚 | 0.000061 | 1.14517 |
| 目标观察 | 2.64468 | 1.89046 |
| 留出第三观察 | 3.54332 | 3.59628 |
| 整条留出轨迹 | 2.76496 | 2.00505 |

源锚最大漂移 1.7198 px，第三观察 P90 从 5.5018 升到 6.5463 px。拒绝并完整恢复，不能用目标中位数下降放行。

### 一次有界 F 细化：120 个交替步

重新恢复完整 R0，以相同锚点开始。偶数步只更新表面，奇数步只更新有真实 fit 观察的部分 F；每条链的源 F、参考 F、所有 K、世界 C、身份、表达、尺度固定。raw tanh 增量限制 ±0.20，沿用原 1°/.0015 单位包络；源重投影增加显式 0.35 px 软约束，观察权重仍不变。没有自由 2D warp。

| 像素误差中位数 | R0 | 有界交替后 |
|---|---:|---:|
| 源锚 | 0.000061 | 0.37305 |
| 目标观察 | 2.64468 | 1.48277 |
| 留出第三观察 | 3.54332 | 3.44836 |
| 整条留出轨迹 | 2.76496 | 1.76113 |

源锚 P90 0.48368 px、最大 0.55297 px，解决了该候选之前的大源漂移，但仍不足以保留：
- `frame_0028.png` 的 19 个观察，中位数 4.16365→4.49295 px；
- `frame_0042.png` 仅剩 1 个有效跟踪，11.35638→11.73828 px，不能用它宣称该方向已可靠覆盖；
- 第三观察 P90 5.50183→5.84751 px，没有稳定改善尾部。

最大表面位移 0.666 原生像素尺度，面积比最小 0.98460、法向余弦最小 0.99993；没有用塌陷表面降低误差。局部面积/法向检查不等于完整自交验收。保留完整失败证据，恢复初态，不进行 G1 外观恢复，不声称共同改善和可见细节已通过。

### Gctrl：原 R0 上的有限外观对照

实际执行 120 个 Adam 步、240 次原生全幅图像反传，固定拓扑与几何，只更新有共享片区支持的皮肤点 SH、alpha、scale、quaternion，片区外参数逐步恢复原值。没有增加 SH 阶数、生成皮肤或改全局对比度。

同一协议原 8 开发 + 6 固定回归继续保留；本片区只有 6/8 与 3/6 视角具有可见像素，其余不填零，也未从全脸回归中删除。它们长期参与研发，不叫最终盲测。

部分 patch L1：0035 为 0.019188→0.017271，0061 为 0.049975→0.046682；但0015、0115、0130、0145、0058、0059退化。实际观图没有稳定、明确的新细节，不将局部均值下降称为修好。Gctrl 同样保留为对照、恢复初态。

[0035 原片 / G0 / Gctrl / 被拒固定F / 被拒有界F](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/haze-shared-surface-context-20260929-a/Gctrl/comparisons/frame_0035.png)

[0058 固定回归同列对照](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/haze-shared-surface-context-20260929-a/Gctrl/comparisons/frame_0058.png)

G1 未运行是明确的几何前置检查失败，不冒充做完 Gctrl/G1 单因素质量比较；不是停止在前向探针：本轮已运行 300 个实际几何优化步和 120 个外观优化步。

## B：背景表面支持的实际边界

保持完整 R0 人像冻结。复用上轮来源贡献证据，选择最大疑点家族13378，仅将它当查找入口，不视为一个物理平面。使用其三个实际训练观察0135、0138、0136，检查源投影附近有限区域内不同 POINT3D_ID、原相机与原始轨迹，未重匹配、重做SfM或假称执行MVS。

| 训练观察 | 独立静态轨迹 | 共面假设内点 | 有限凸包对窗口内该家族贡献覆盖 |
|---|---:|---:|---:|
| 0135 | 239 | 41 | 30.40% |
| 0138 | 215 | 41 | 19.86% |
| 0136 | 243 | 45 | 17.43% |

平面用多个不同空间点拟合，容差由原生像素尺度确定，范围限于真实锚点凸包。即便如此，图中相框、柜体和物件有不同深度；共面内点和 room mask 仍不是完整可见墙面的真值，也不是候选点未被遮挡的证明。未完成跨视图物理边界确认，不能直接创建替代面。

[0135 真实原片上的有限窗口、静态锚及凸包](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/haze-shared-surface-context-20260929-a/B-surface-support/frame_0135.png)

因此本轮 B **没有背景替换或恢复训练**，背景不宣称改善。不以17%—30%的局部支持代表整家族背景，也不把该局部检查解读为“原视频没有拍到背景”；窗口外支持及其他物理面尚未审查。拒绝重复 O1 的单点收缩方案，未挖空任何背景。需要的下一步是分物理表面确定可替换区域，而不是提高全部 opacity 或只降低 q_room。

## 固定资产绕看、恢复与资源

[本轮一份固定 PLY 的连续绕看](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/haze-shared-surface-context-20260929-a/final-evidence/fixed-asset-continuous-orbit.mp4)

视频：gsplat 1.5.3，72帧、24fps、1080×1920，固定参考时刻、固定 PLY hash，全部头部/附件/身体/room 同次前向，未按角度换资产。控制范围±20° yaw、±8° pitch只是绕看控制，不是原片真实观察角。它是**被拒候选的冻结 T2 诊断**，不是 PlayCanvas 视频、不是鸿蒙测试、不是新 joint 成果。当前黑底头部对照也不是最终作品。

三个分支均11970个人点，固定 UID、父 UID、三角、重心、来源、置信度、语义；背景/身体各参数逐项未变。几何阶段所有外观和附件参数逐项未变。Gctrl 实际加载 candidate 后恢复完整 initial，模型张量、采样器、optimizer绑定校验通过；几何失败候选也保存了恢复检查点。`.pt` 包含 Adam、RNG、采样器、策略禁用状态、绑定、元数据及源码合同。不是从旧900无Adam包“精确resume”，本轮优化使用明确的新Adam起点。

| 工作 | 实际记录 |
|---|---|
| D加载、导出和gsplat原始绘制 | 25.39秒；PyTorch峰值450.41 MiB，reserved480 MiB |
| 固定F几何 | 优化及保存39.98秒；全阶段74.18秒，峰值allocated416.61 MiB、reserved470 MiB |
| 有界F分支 | 优化/保存/评价46.23秒；该独立进程未采集完整显存峰值，不补估 |
| Gctrl | 循环/保存/终态评价17.93秒，不含此前加载和初态评价；allocated612.76 MiB、reserved692 MiB |
| 固定资产轨道 | 3.91秒；不是采集到最终资产全链路时间 |

Windows/WSL实际识别 RTX5070 Laptop 8151MiB，训练成功，无OOM。上述是当前小范围研究的实际PyTorch显存，不含桌面系统总占用，也不证明完整重建仍有无限余量。不承诺完整2—3分钟。

## 文件级改动与复现

全部为新增研究文件，不改既有生产函数：
- `backend/reconstruction_shared_surface.py`：共享残差/锚投影/可微协方差传输。
- `backend/test_reconstruction_shared_surface.py`：协方差梯度、多观察共享锚、位移界限、状态恢复回归（4项通过）。
- `backend/run_haze_shared_surface.py`：真实R0加载、D输入、三观察轨迹、固定F几何。
- `backend/run_haze_bounded_pose.py`：一次有界交替实验及拒绝恢复。
- `backend/run_haze_appearance_control.py`：有限Gctrl。
- `backend/audit_haze_final_evidence.py`：完整恢复、不变量检查、固定资产与绕看。
- `backend/audit_haze_room_surface.py`：多锚有限背景候选，不修改room。
- `backend/audit_haze_projection_support.py`：实际shader宽核限制涉及的投影统计。
- `scripts/probe-haze-display.mjs`：隔离2.22.4绘制，不改应用。

在 W 的 backend 中，使用现有 WSL 环境。默认 run-id 已有结果，重复调用会拒绝覆盖。重现时显式提供新的私人目录 `SELF_HAZE_RUN_DIR`，D 浏览器脚本目前针对本轮固定目录；复用历史结果时不能将另一个 run 的检查点混入。

```bash
export PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=4
export CUDA_HOME=/usr/local/cuda-12.8 TORCH_CUDA_ARCH_LIST=12.0 MAX_JOBS=2
# 每次完整重现使用一个新的目录；不要覆盖本轮目录。
export SELF_HAZE_RUN_DIR="$PWD/.sources/<new-unique-run-id>"
/opt/self-reconstruction/venv/bin/python -B -m unittest test_reconstruction_shared_surface -v
/opt/self-reconstruction/venv/bin/python -B -u run_haze_shared_surface.py display
/opt/self-reconstruction/venv/bin/python -B -u run_haze_shared_surface.py geometry
/opt/self-reconstruction/venv/bin/python -B -u run_haze_bounded_pose.py
/opt/self-reconstruction/venv/bin/python -B -u run_haze_appearance_control.py
/opt/self-reconstruction/venv/bin/python -B -u audit_haze_room_surface.py
/opt/self-reconstruction/venv/bin/python -B -u audit_haze_final_evidence.py
```

本轮浏览器实际命令在 W：`node scripts/probe-haze-display.mjs`。输出版本分目录保留：最初打包失败为 `D/playcanvas/`，增加浏览器不执行的Node专用模块外部标记后 `playcanvas-01` 成功，`playcanvas-02`补齐实际AA/工作缓冲属性。未修改引擎。投影诊断曾遇CUDA大批特征值接口失败，保留原脚本与失败日志；改为1024一批后通过，不改变输入或公式。正式训练没有因此重跑。

## 保留、拒绝与下一项动作

可保留：共享锚点与协方差同步实现、真实Adam接线、完整状态恢复；同资产显示对照及67个极宽room核的定位证据；有限多锚表面支持的记录。

拒绝作为新画质基线：固定F共享表面、有界F共享表面、Gctrl；B无足够已核验范围，不创建伪造候选。头发、镜框、颈肩衣物和完整场景仍未通过。模拟器与真机本轮未测，不发布、不回传。

**下一项最有根据的单独动作：对已定位宽room核承担的真实背景，按原片可见边界划分多个物理表面并建立覆盖保留的局部替换事务。** 从现有静态图与轨迹继续，不立即要求补拍；必须覆盖旧核在不同观察中承担的有效背景，不能再用一个来源点、一个平面或局部凸包替代全部内容。同时以训练器和PlayCanvas两边完整背景/脸前贡献验收，不让查看器半径截断掩盖病态几何。该动作尚未执行。

面部单独保留具体后续缺口：第三观察和0028/0042的局部对应/F一致性尚不稳，当前表面弱模态不能被当成真实细节。没有因此删除这些回归，也没有把“减少源漂移”宣传成面部重建已完成。
