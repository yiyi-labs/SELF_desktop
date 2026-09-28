# SELF 阶段0：零训练交叉重放与下一项修复决定

日期：2026-09-28。代码锚点：`27c9810bf0746d8e4382eb218e89276954767d7d`。本报告只覆盖获批的阶段0，不是新重建候选或发布验收。

## 结论与修复选择

**下一项应优先走阶段2A：准备表面的支持、过滤与预算分配；不是先调大 scale 或统一提高 opacity。**

1. **背景在现存 prepared 表面假设中已经明显不完整。** 五个同协议视角的 S 只占固定可见房间 mask 的 **4.39%—13.65%**。这是比上一轮“初始低 alpha”更靠前的证据，但不能解释成原视频没有这些背景，也不能说只有这些像素有真实几何。2000 条稀疏轨迹本身不自动代表连续曲面；当前保存的 2659 个唯一三角假设也不是实测真值。
2. **本轮未发现 S 有而 U 没有的区域。** 五帧、两种光栅模式、各冻结状态下，已记录三角支持域均落在有效高斯足迹内。不能把 U 的存在当成足够重叠、正确厚度或清晰外观；但现有证据不支持把“支持域根本没被足迹覆盖”列为首要问题。
3. **U 有而 A 低确实并存，主要延伸到 S 之外。** v3 360 步后，固定房间区域的 62.67%—80.93% 属于 U 有、A<0.8；其中真正位于 S 内的部分仅占整块 mask 的 0.39%—1.46%。故不能用全面增加透明度来“补回几何”。
4. **v2 的高覆盖主要由少量膨胀高斯承担。** 830/22138 个点（3.75%）有至少一个局部尺度轴超过自身初值两倍，贡献了房间可见 q 的 **91.59%—97.36%**；最大轴前 1% 的点贡献 **90.65%—98.23%**。这是真实同次透明合成的贡献，不是按点数或投影面积猜测。它解释了旧版为何能把画面填满，但不能据此认定其深度和连续结构正确。
5. **PLY 回载与 AA/classic 不是大面积缺失的首发原因。** 同一冻结参数的图像往返最大绝对误差 `0.000647187`、最大平均绝对误差 `2.49e-08`；AA 切换对 v3 终态平均 A 的影响仅约 -0.00110 至 -0.00270。

本轮没有改善模型质量，也没有训练一个新模型。它把下一项修改的依据从“孔洞很多”推进到“现存连续表面支持不足，旧版主要依赖少量大高斯补偿”。

## 固定的输入与合同

- 同一原片：`capture-1790410633104.mp4` 的保留研究副本，SHA-256 `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。
- prepared：`P/backend/.sources/integrated-components-v2-20260928-e`；v3 当次运行：`W/backend/.sources/reconstruction-v3-20260928-a`。P=`D:/STUDY/College/mine/olay`，W=`C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay`。
- `static_surface_seeds.npz` SHA `22296697a46475e5099a5fe2430852422876150cfc9aaccc3e0b6f124b11ad35`；`local_geometry.npz` SHA `fae308b496a50dad7c67c58ee2767d20ea9c9957f2c8dcbd811bb337d44f07e0`。
- v3 `C-static.pt` SHA `13dd4aa905987266371a1bb2d391eabe9ed91dfc9f0e38ca9da5f4a408a366c4`。
- v3 PLY SHA `143d0529db257656f71e32b8f6786e26eafe1037f993d7d2f359dc447600dace`；v2 PLY SHA `1b2fe713df73ab87ce86458bf2b689c81eba1195f1004a6fa67e556841a9ccb3`。
- FLAME Open 文件只为恢复历史初始化而读取，没有拟合或版本 A/B；模型 SHA `e75a0990728ba038c7da2a420ae4396f7ddd7781366c13026066c5b24f127623`。
- 当次 v3 六份源码快照逐项核对 config 中的 SHA；复用代码核对到 27c9810。历史 v2 的 `initialize`、`posed`、`make_frame` AST 与复用版本一致；v3 `FreeComponent` 状态计算也与当次快照一致。`supported_static_surfaces` 当前及历史快照文件 SHA 同为 `55c4b22cac0e5b2dfde25a498670ed3695e2030a46e982e9c5587ecfa83b36d5`。
- 所有 C/F 按 imageName 查询，不按数组序号或 COLMAP ID 猜测。C 仍是现有研究相机，未因此重新判定 E1 通过；本轮未估计或细化相机。原始已去畸变图 1080×1920，无头部 crop；使用既有 half 合同得到 540×960。K 前两行乘 0.5，fx=fy≈594.53794，cx=270，cy=480；RGB 用 AREA 缩小，mask 用 NEAREST。
- 人物在所有固定人物合成中使用同一个 v3 导出参考状态 `frame_0111.png`。它与其他帧的真实人物姿态不同，因此这些合成只审计遮挡贡献，**不拿脸部误差评价本人画质**。
- 颜色：原片数值 RGB/255；使用已有 SH1 求值、加 0.5、仅下限截零；黑色 clear 的预乘透明合成。统计保存 float RGB，不做 gamma、锐化、对比增强或上限裁剪；仅 PNG 显示裁剪到 [0,1]。SH 不是物理皮肤材质。本轮没有调用 PlayCanvas 或鸿蒙绘制。
- 本次输入清单共 232 个文件，执行结束逐项复核一致：[完整输入、参数、源码 SHA 与逐帧结果](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage0-20260928-fiveviews/summary.json)。

## S、U、A 的具体含义与边界

**S**：从现有 `triangle_sources` 找回三个真实静态轨迹顶点；只把重复的三角引用归并用于求投影并集，没有删除任何高斯/种子。双面投影、像素中心采样、透视正确深度和 z-buffer，取已记录表面中的最近者；排除实际 mask 中人物及 unknown 区。五帧 room 与 unknown 交集均为 0。保存 `S_raw`、`S_visible`、深度和获胜三角索引。

这只是**已记录假设之间的可见性**，不是房间完整深度真值。未表示的室内物体仍可能遮挡某些三角，不能证明所有三角内部都是真实可见表面；因此 S 应视为有这些限制的支持上界。即便按这一上界，支持也远未覆盖房间。不能用本次 S 低直接要求用户重拍。

**U**：沿用 gsplat 1.5.3 实际投影 conic、AA 补偿后 opacity、tile 交集列表和像素中心。按内核 `alpha=min(0.999, opacity*exp(-sigma))`，保留 sigma≥0 且 alpha≥1/255 的有效足迹；不是中心计数、矩形包围框或人为指定半径。U 表示透明度遮挡前的候选足迹，不表示最后可见性。

**A、q_room、RGB**：直接来自既有 `draw` 的真实前向。共同合成时，房间与固定人物参加同一次光栅化，不能用两个各自渲染的 alpha 相加替代。

附加的全部候选 optical-depth 合成只校验 U，不代替 A。实际 CUDA 有 `next_T<=1e-4` 的**排他式提前终止**，高不透明旧资产的理论无限合成与真实 A 可相差约 0.01558。按真实排序对最差像素重放终止规则后，最大差 `0.000535563`（容差 0.0008；快速数学/截断边界仍有数值差），50 组绘制均无 U=0 而 A>1e-6 的像素。没有为让指标一致而修改原参数。

## 逐阶段结果：先 room-only

下表 S/U 均以固定可见房间 mask 为分母；A 为均值，RGB L1 包含缺失像素。v2 列是旧终态 AA 的同合同重放，不是与 v3 的单因素实验。

| imageName | 准备 S | 初始→360 的 U | 初始→360 的 A | 初始→360 RGB L1 | v2终态 A / RGB L1 |
|---|---:|---:|---:|---:|---:|
| frame_0015.png | 7.70% | 47.15% → 82.29% | 0.1128 → 0.2389 | 0.56301 → 0.41366 | 0.9619 / 0.06070 |
| frame_0035.png | 7.36% | 66.17% → 91.65% | 0.1465 → 0.3119 | 0.54627 → 0.35118 | 0.9684 / 0.04382 |
| frame_0115.png | 4.39% | 38.40% → 71.36% | 0.0937 → 0.2222 | 0.64237 → 0.47584 | 0.9514 / 0.06754 |
| frame_0130.png | 13.65% | 79.48% → 94.48% | 0.2666 → 0.4630 | 0.47041 → 0.27396 | 0.9784 / 0.05220 |
| frame_0145.png | 10.10% | 75.95% → 94.60% | 0.1976 → 0.3947 | 0.52223 → 0.29688 | 0.9734 / 0.05540 |

准备和恢复初值中 room XYZ 逐点相等；v3 room 为 world-static，坐标转换没有再施加头部矩阵，也没有乘第二遍尺度。`FreeComponent.base` 与恢复初值精确相等，initial_scales 在 float 容差内一致。因此“坐标变换把完整背景搬走”没有得到支持。

| 状态 | 点数 | 最大轴 P50 / P99 / max（世界单位） | 单点 opacity P50 / max |
|---|---:|---|---|
| v3 初值 | 22020 | 0.04006 / 0.27600 / 1.33544 | 0.26894 / 0.26894 |
| v3 360 | 22020 | 0.04275 / 0.31133 / 1.99842 | 0.27056 / 0.68851 |
| v2 终态 | 22138 | 0.04451 / 0.59045 / 16.34642 | 0.27388 / 0.99826 |

每个状态完整保存 XYZ 范围、协方差、各轴 scale 分布及 opacity 分布；每帧保存投影 conic、radii、opacity、Gaussian ID、实际重叠数。v2 内部参数点序和导出 sidecar 点序不同，初始尺度分别从各自对应记录读取，未使用跨文件顺序 zip。

v3 终态的 alpha 分档：

| imageName | A>0.01 | A>0.2 | A>0.8 | A<0.8 |
|---|---:|---:|---:|---:|
| frame_0015.png | 76.28% | 35.17% | 10.46% | 89.54% |
| frame_0035.png | 88.71% | 50.25% | 10.73% | 89.27% |
| frame_0115.png | 63.26% | 33.49% | 8.69% | 91.31% |
| frame_0130.png | 92.99% | 69.22% | 22.90% | 77.10% |
| frame_0145.png | 93.63% | 63.22% | 14.77% | 85.23% |

第35帧初始 A<0.8=93.707%，360后=89.274%，与原审计复现一致。**这是低 alpha，不是几何空白比例**。没有证据支持“初始完整、360步把它剪没”：本次无 prune，U/A/RGB 指标相对自身初始化整体改善。

## 缺失分类：允许重叠，不把低 alpha 偷换成无几何

下表全部以固定 room mask 为分母。“U有A低”含 S 内外，因此与“无S”可以重叠；“S内A低”给出其有表面假设依据的子集。高 A 且 RGB错定义为 A≥0.8 且 RGB绝对误差均值>0.1，仅为诊断阈值，不是发布标准；0.05敏感性结果也已保存。

| imageName | 无S | S有U无 | U有A低 | S内A低 | 高A且RGB错 |
|---|---:|---:|---:|---:|---:|
| frame_0015.png | 92.30% | 0.00% | 71.83% | 0.47% | 2.45% |
| frame_0035.png | 92.64% | 0.00% | 80.93% | 0.46% | 1.58% |
| frame_0115.png | 95.61% | 0.00% | 62.67% | 0.39% | 1.90% |
| frame_0130.png | 86.35% | 0.00% | 71.58% | 1.46% | 8.21% |
| frame_0145.png | 89.90% | 0.00% | 79.83% | 0.91% | 3.07% |

空间位置不是随机孔洞：S 主要沿上方柜门、把手附近的有限结构，少量在左侧下方；天花板、大片低纹理门板和右侧墙面缺乏连续假设。第115帧 S 仅4.39%，集中在左上柜门；第130帧 S 较多，但柜门边缘仍有高 A 的局部颜色错误。第35帧 U 扩展到大片门板，而高 A 仍集中在有限结构和光斑状足迹。每组 `metrics.json` 另有3×3空间分区，避免只有全图均值。

对应判断：

- **2A，首要**：无 S 占86.35%—95.61%。确定现存 prepared 表面表示不足；尚不能区分有多少是原始地图缺支持、过滤过严或预算提前耗尽。历史准备报告有 edge=8097、depthSpread=2896、normal=4298、multiView=5213 次拒绝；它们不是独立缺失面积，不能相加当作根因比例。
- **2B，不作为第一项单独修复**：本轮 S有U无为0。覆盖均衡仍可能改善足迹重叠和结构，但没有理由先全局缩放高斯或盲目加点。
- **2C，真实但次要且有边界**：在 S 内部，360后仍有6.07%—10.69%的支持像素 A<0.8；可在有依据的表面上随后核对重叠、alpha与训练约束。S外低A占主导，不应以提高opacity消灭这类“不确定性”。
- **A够但RGB错，真实并存**：v3 中占room mask 1.58%—8.21%；v2中6.93%—11.54%。局部柜门线条模糊/偏移和大点外扩可见，但本轮不能把颜色、位姿、深度、反光各自的因果份额分开。需要有限结构窗口对照，不能凭RGB阈值断言具体三维错误。

图例：紫=无S；橙=S有U无；蓝=S/U有但A低；红=S/U有、A高但RGB误差>0.1；绿=S/U有、A高且误差≤0.1。黑色为固定room mask之外。**紫色并不表示那里一定无高斯**。

![第35帧v3分离审计](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage0-20260928-fiveviews/frame_0035/v3_360-classic.png)

![第35帧v2同合同重放](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage0-20260928-fiveviews/frame_0035/v2_final-aa.png)

另外两个结构视角：[第115帧](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage0-20260928-fiveviews/frame_0115/v3_360-classic.png)；[第130帧](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage0-20260928-fiveviews/frame_0130/v3_360-classic.png)。

## v2 高覆盖由谁贡献，为什么不直接恢复它

保持全部点、opacity、排序和遮挡不变，将点的所属标签作为额外颜色通道前向合成，得到各组真实 q。标签绘制 A 与原 draw 在 2e-6 内一致；没有删除大点做反事实，也没有用 backward 估贡献。

“>2倍/5倍”取相同点各局部尺度轴相对记录初值的最大比值；最大轴前1%按最终绝对尺度选取，三个群组可能重叠，不能相加。

| imageName | >2倍830点的q占比 | >5倍55点的q占比 | 最大轴前1%的q占比 | S外>2倍点的q占比 |
|---|---:|---:|---:|---:|
| frame_0015.png | 95.39% | 53.37% | 95.45% | 97.89% |
| frame_0035.png | 94.09% | 45.99% | 94.21% | 96.26% |
| frame_0115.png | 97.36% | 62.35% | 98.23% | 97.82% |
| frame_0130.png | 91.59% | 44.47% | 90.65% | 94.38% |
| frame_0145.png | 93.63% | 47.74% | 93.89% | 96.11% |

因此“少量大点主要支撑旧版覆盖”得到直接证据。与此同时，v2在这些观察角的RGB和结构梯度误差确实比v3好：不能把它全说成无效；但高A与低均值误差不能代替有限表面深度、清晰边界及连续视差。room-only对照能看见大片模糊铺色和部分柜门细节丢失。本轮既不回退，也不据此删除这些点。

## 单因素、共同合成与导出分开看

**同冻结参数切AA**：v3终态的 AA−classic：

| imageName | 平均A变化 | RGB L1变化 |
|---|---:|---:|
| frame_0015.png | -0.001704 | -0.000168 |
| frame_0035.png | -0.001847 | +0.000240 |
| frame_0115.png | -0.001103 | +0.000021 |
| frame_0130.png | -0.002703 | +0.000055 |
| frame_0145.png | -0.002160 | +0.000137 |

变化远小于现存缺失，不能把AA开关列为第一项修复。

**固定同一个人物参考状态共同合成**，v3终态：

| imageName | room-only q | 共同合成 q_room | 共同合成总A | 共同合成room RGB L1 |
|---|---:|---:|---:|---:|
| frame_0015.png | 0.23891 | 0.22017 | 0.30490 | 0.38980 |
| frame_0035.png | 0.31194 | 0.28490 | 0.35998 | 0.34576 |
| frame_0115.png | 0.22215 | 0.21984 | 0.28809 | 0.45128 |
| frame_0130.png | 0.46300 | 0.44600 | 0.51818 | 0.26599 |
| frame_0145.png | 0.39465 | 0.37630 | 0.44564 | 0.29049 |

人物确实移除部分room可见贡献，但room-only已经低覆盖；不能归因于“完整背景主要被人物吞掉”。这里固定参考人物与当帧人物有位置差异，不能把这个差值直接称为错误遮挡，更不能用它评价脸部。

**完整流程差异另存**：`whole-v2-aa.npz/png` 用v2自己全部导出部件、AA；v3完整合成为v3部件、classic。二者固定相同C/K与各自111参考状态，但几何、训练、部件点数、约束均不同。这是多因素结果对照，不是AA、训练步数或密度策略的单因素证明。历史实际每帧动态合成指标也不与这组固定参考指标混用。

**导出回载**：分别对v2参数/对应PLY、v3检查点/对应PLY，在两个光栅模式和五个相机下比较float RGB、A、q_room。全图最大绝对误差0.000647187，最大平均绝对误差2.49e-8；少量截断边界像素不是位级一致，但不是孔洞来源。此项是同一gsplat绘制合同的资产回载，**不是新的PlayCanvas或鸿蒙显示通过**。

## 确定问题、尚未证明的原因与实现边界

确定且本轮保持原状：5249个重复XYZ；2000组跨source_kind的来源ID碰撞；v3 room侧车source_kind全为0、没有triangle_sources。没有去重、补元数据、裁剪或改opacity。

准备源码按view遍历、追加采样，到全局预算即退出，缺少跨视角统一表面元素池；同一三角可重复消耗预算。这与小S、重复实例和局部聚集一致。但尚未枚举被预算挡住的候选，所以**不能保证仅改预算就能补齐大片墙面**。`conflict==0`是否把真实遮挡误记为矛盾、低纹理区是否有可用静态深度，需下一项受控实验区分，不能本轮静默放宽过滤。

v3的真实范围保持原结论：face未训练；颈肩衣物冻结；hair267、accessory16、neck/cloth348、room22020；附件360步、房间360步；没有density对象或split/clone/prune/reset事件。joint调用空阶段状态，后续是占位异常，**没有可执行的完整联合训练循环**。因此501步不会自动细化，也不能称原定完整人像方案已经实施并失败。

## 下一项最小修改和有限对照预算（待批准，不在本轮执行）

建议先在 `C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/reconstruction_scene.py` 的 `supported_static_surfaces` 做一个范围明确的改动：**分开“收集现有过滤下的候选表面元素”和“分配采样预算”，不再让早遍历视角先消耗完预算。**

- 保持同一旧地图、59个已有训练观察、相机/内参/掩膜、现有过滤条件和不超过22020点的总预算；不重做SIFT/ALIKED、不修改人脸、不添加体积散点。
- 候选元素按源顶点及相容表面保存身份与观察证据；先汇总所有视图，再按未覆盖投影和空间分布分配预算。新的采样实例不能冒充新的三角化测量。来源合同必须保留source_kind/triangle_sources，旧sidecar不原地修复。
- 只做一个A/B：A为本轮冻结结果；B为单次新的候选池/预算准备结果。先零训练比较S、U、实际结构边界和三角跨深度风险。仍用这五个开发视角分析，但它们已参与方法选择，不能当最终独立审计集。
- 若现有过滤下的候选池S仍不足，停止反复采样。下一步最多选3个静态结构窗口，每窗至多3个已有可信训练观察，区分遮挡过滤与缺少几何；只有证据支持时再讨论有限表面或局部深度。不能直接扩大80px阈值，不能把生成背景或单目深度当真值。
- 在表面依据成立之后才讨论2B协方差/重叠或2C局部约束与有限训练预算。本轮不批准、不运行这类训练，也不为追求高A恢复v2全局膨胀。

这项改动优先检验“准备遗漏/预算偏置”这一可复用的问题，不针对本视频的具体帧号、肤色、柜门位置写补丁；但单个旧视频A/B也不能证明未来所有用户稳定。

## 复现、保存与停止状态

新增文件仅：

- [审计适配器](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/audit_reconstruction_stage_coverage.py)
- [审计合同测试](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/test_reconstruction_stage_coverage.py)
- 本报告。原工作区没有新增或修改文件。

在 W/backend 的既有 WSL 环境运行（禁止覆盖已存在output，复现时换一个新的audit目录）：

```sh
PYTHONDONTWRITEBYTECODE=1 CUDA_HOME=/usr/local/cuda-12.8 TORCH_CUDA_ARCH_LIST=12.0 MAX_JOBS=2 \
/opt/self-reconstruction/venv/bin/python -B test_reconstruction_stage_coverage.py

PYTHONDONTWRITEBYTECODE=1 CUDA_HOME=/usr/local/cuda-12.8 TORCH_CUDA_ARCH_LIST=12.0 MAX_JOBS=2 \
/opt/self-reconstruction/venv/bin/python -B audit_reconstruction_stage_coverage.py \
  --prepared /mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e \
  --run /mnt/c/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-v3-20260928-a \
  --output /mnt/c/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage0-20260928-fiveviews \
  --frames frame_0035.png frame_0015.png frame_0115.png frame_0130.png frame_0145.png
```

实际完成50组room-only状态/相机/模式绘制、50组固定人物共同合成、5组v2完整流程参考绘制，以及来源标签前向。四项合同测试通过，含透视深度、遮挡z-buffer、旋转椭圆/后方点、AA、提前终止、float RGB与零训练防护。[测试日志](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage0-20260928-fiveviews/review/contract-tests.log)。

五帧完整重放耗时 **104.33秒**；RTX5070 Laptop / torch `2.8.0+cu128` / gsplat `1.5.3`。该重放区间PyTorch峰值 allocated **210.28MiB**、reserved **254.00MiB**，不含驱动/其他进程，**不是训练显存结论**。首次合成测试触发既有CUDA扩展常规编译，未换依赖或驱动；后续直接复用。

前置试跑的路径解析、布尔拼图显示和过严数值断言失败分别保留在新pilot目录，不覆盖或删除。只有 `reconstruction-stage0-20260928-fiveviews/summary.json` 的完整重放计入上述结论。

执行后原工程1639个冻结文件、历史清单242项、v3清单299项全部SHA一致；原工程git状态摘要SHA仍是 `26338b0026321936b864a2f5aa875c9b6ea5e9f4a6c22b2625eeff0540d8a883`。[逐项保存核验](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage0-20260928-fiveviews/review/preservation-check.json)。本次读取的232个输入也完成前后核验。私人影像、NPZ/PLY及输出图仅留本地忽略目录，Git未包含私人资产。

没有Git提交、reset、clean、回滚或修改旧run。新文件保留待审查；本报告不把条件性的“提交只包含新文件”解释为必须现在提交。此前未跟踪的只读审计报告也保持原样。

**阶段0已完成并停止。阶段1及以后、算法修改、训练、部署、回传均未执行；现有应用、签名、作品、USB/HDC、查看器、上脸和故事不变。**
