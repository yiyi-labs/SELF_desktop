# 完整内容、可靠运动与交接修缮：本轮实测记录

日期：2026-09-30。W：`C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay`。
起点 `b636334816d4997a27e713c7c86356fe5ea6de19`，分支 `codex/reconstruction-v3-audit-20260928`。
研究根目录：`backend/.sources/complete-content-repair-20260930-a`，下文记作 ROOT。
本轮已实际修改隔离代码、运行新观测/几何计算、480 步 GPU 背景训练和双渲染器绘制。**没有达成完整人像明显改善，也没有可发布的新作品。** 不部署、不回传、不切生产默认。不能把下面的接口修复视为画质通过。

## 1. 先回答结果

1. **衣物**：新增两个重叠窗口的分布式跟踪，可靠衣物轨迹仅 6 / 7 条，仍集中胸前，双肩及衣领缺有效约束。未求解不受约束的新 Q，未伪造稠密衣物，也未重跑旧胸前小片训练。本轮没有建成完整新衣物；这是未完成项。
2. **人脸及头发**：112 条物理轨迹的共享 XYZ、23 个受限头姿和连续表面均实际计算并回放；目标视图重投影有下降，但第三视图及可见画质仍未通过。没有在失败几何上继续外观训练。头发新增 1 条观测的几何不可靠；旧帽壳未修好。
3. **背景**：从原始 R0 状态按正确六 UID 退役，使用 27,915 个真实 MVS 支持点做 480 步训练；脸前污染减少，但完整背景 13 / 13 视图比旧状态差，因此拒绝。
4. **实际合成内容**：诊断 PLY 仅含旧头部、保留的旧背景、新背景候选和旧身体；**不含本轮失败面部几何，也不含旧胸前片区**。已交付明确的合成失败记录、完整身份侧车和固定资产绕看。
5. **最小阻塞**：可靠测量的空间分布与后续表面表达仍不足。新增肩线/衣领的真实跨视图测量是衣物入口的最小缺口；面部则是自由 XYZ 到连续表面后的误差与观测不确定性，不能再靠延长颜色训练解决。

## 2. 本轮可保留的代码能力

| 文件（W/backend 下） | 实际作用与边界 |
|---|---|
| reconstruction_complete_contract.py | 局部片区不得整组替换；校验源、尺度、参考变换、UID和替换证据；保留完整目标分母；显式原生像素→COLMAP适配。仅研究接口，没有生产接线。 |
| run_complete_observations.py | 固定 CoTracker3 推理、等比 letterbox、最后可见帧反向查询、原生图像双向 ECC 与真实可见性复核。不是三维真值。 |
| run_complete_geometry.py | 旧可靠测量加新去重测量，固定 F 与受限 F 的共享 XYZ 对照、数据方向信息加权表面融合。 |
| run_complete_surface_check.py | 复核真正进入 SharedSurfaceModel 的连续表面及协方差传输，保留原 8 开发 / 6 回归。几何失败不会由自由点指标放行。 |
| run_complete_room_training.py | 原始上下文、显式六 UID、全有效 room 像素监督；offset / SH / alpha / scale / rotation 实际更新；完整状态恢复。 |
| audit_complete_content.py / audit_complete_handoff.py / audit_complete_summary.py | 实际 MVS 相机及逐对评分、原身体覆盖、附件负证据、UID清单、三相机双端绘制和同口径图像。 |

8 项合同测试通过，9 个新 Python 文件语法解析通过。测试不等于画质验收。
组件合同当前是可复用研究接口；它没有反向改写旧 runner，也没有声称已将所有历史入口升级。

## 3. 局部片区确曾替换整身体：已按张量和侧车核实

`complete-content-evidence-repair/result.json` 记录真实 UID namespace：

- 旧 C 诊断资产：head 11,970 + room 26,054 + 新胸前 cloth 6,857；**原 body 348 未包含**。
- 旧 B-scoped：head 11,970 + old room 26,048 + new room 5,002 + **原 body 348**；没有新 C patch。
- 新 B 诊断：head 11,970 + old room 26,048 + new room 27,915 + 原 body 348 = **66,281**。

不同候选参考时刻不自动拼接。`plan_patch` 拒绝整组退役、未知 UID、无可信参考变换、非刚性/含 scale 的伪刚体矩阵、未通过接替覆盖的退役。
新背景候选内部按审计证据退役六点训练，原状态仍完整保留；失败后没有安装进原模型。

完整目标沿用原 `neck_cloth_visible`，六个空间分区的并集与其严格相等。**这不是独立 neck/collar/shoulder/sleeve 解剖分割**，当前缓存没有这些细分真值，本轮也未伪造。该项仍有实现缺口。
原 body-only alpha<0.8：参考 0111 为 267,509 / 540,117（49.53%），0025 为 202,579 / 489,979（41.34%）。只表示覆盖诊断；覆盖像素也可能模糊。它与旧胸前片区的 97.1% 缺覆盖不是同一模型，不能直接相减。
完整性图：ROOT/complete-content-evidence-repair/*-body-unexplained.png。

## 4. 新二维观测与衣物/MVS阻塞

固定 CoTracker3 代码 `82e02e8029753ad4ef13cf06be7f4fc5facdda4d`；权重 SHA-256：
`205d34789f19699d64b22cf93f9b697f15f28d4025240e31532e504109837218`。
原生 1080×1920 等比缩为 216×384 后居中放入 512×384；转换包含 resize 像素中心。推理后在原生 25×25 patch 复核，不使用遮挡预测作颜色或深度依据。

| 窗口 | 查询 | 通过的观测轨迹 | 衣物结果 |
|---|---:|---|---|
| 0002—0014 | 305 | face 12，glasses 4，lower-middle 6 | 无双肩分布 |
| 0008—0014 与 0022—0028 | 309 | face 1，hair 1，lower-middle 6，lower-right 1 | 无双肩分布 |

去重后增加 10 条 face 轨迹，合并 3 条重复，共 112 条。衣物未达到运行前固定的“分布到双肩和胸前、至少 40 条三观察轨迹”等研究条件。**没有把 40 当作 OpenMVS 普适门槛，也没有降低门槛或强连邻图。**
首轮反向查询落在遮挡末帧的问题已修为“每点最后可见时刻”，首次结果保留在 measurements，修复结果在 measurements-visible-reverse。
窗口选择主要依据完整目标覆盖和时间连续；尚未实现成熟的清晰度/有效视差/运动联合选窗。这是本轮未补齐的关键能力，不宣称已充分搜索原视频。

实际 OpenMVS v2.4.0 邻接复算（MVS-pairs.json）：
- 原衣物 0022—0025 各有 3 个共享邻图，但最大 score 仅 0.129—0.270，低于 InitViews 的 2.0；0026—0028 没有达到 3 个共同点的邻图。不是全部在同一个环节被拒。
- 新增静态重叠窗口 0110/111/112/113/117/118/119，真实导入 7 图/204 点；各有 6 个候选邻图，但最大 score 0.970—1.762，真实运行 0 深度图/0 融合点。此失败不靠改阈值继续。
- 评分含共享点、正深度、夹角、尺度和 16×16 分布覆盖。索引按实际导入顺序与外部 image ID 显式对应；未拿 ID 当帧序号。七图规模未触发依赖邻图数量的过滤删除。

已查实的独立交接小修：旧 exporter 写入原生整数中心 K，固定 OpenMVS importer 减主点 0.5；实际 MVSI 相机确为 (539.5,959.5)，而 native K 为 (540,960)。新研究适配明确把 **K 和观测像素同时 +0.5** 后导出，只接受声明的 OpenCV integer 输入；实际小型导入回读与 native K 最大差 **0**。没有回写旧输入，原训练结果仍按其真实旧合同保留，不能把本次训练说成已经使用这项后发现的修复。
此偏差约为亚像素量级，不能单独解释大片缺失，修复也没有让零邻接自动成功。

## 5. 面部：点求解改善，没有可见质量提升

原始 R0 SHA：`2468edc379f8b76eac97fccfbf9e9a4c775f980102b95283ee15b2dc4cee7cb8`，本地副本同 hash。
新对照固定 K、世界 C、尺度、身份、表达；受限 F 只用于至少 8 测量且覆盖至少 3 面部象限的 23 个视图，固定参考 F。每 track 一个共享 XYZ，末观察作第三视图检查。固定 F / 受限 F 的实际非线性求解分别 16 / 32 次函数评估；866 个连续表面顶点有变化，拓扑不变。

| 实际连续表面回放 | 目标中位 / P90 px | 第三视图中位 / P90 px | 8开发固定ROI L1 | 6回归固定ROI L1 |
|---|---|---|---:|---:|
| R0 | 2.404 / 5.973 | 2.502 / 7.063 | .031100 | .041770 |
| 固定 F | 1.526 / 4.125 | 2.110 / 5.126 | .031119 | .041795 |
| 有界 F | 1.504 / 4.171 | 2.124 / 5.129 | .031126 | .041796 |

自由 XYZ 的第三中位约 1.556 / 1.575 px，融合后回到约 2.11 / 2.12 px，说明必须检查实际表面交接，而非只报告自由点改善。表面仍未达到预定容差；有界姿态没有胜出。原片/旧基线/固定F/有界F四列已保存，视觉检查未见真实细节提升。**本轮面部 Adam 外观恢复为 0 步**，不是将失败几何训练成低 RGB 后宣称成功。

执行记录纠正保留：
- face-geometry/config 曾误写 temporal prior，实际残差只有幅度先验；没有时间先验，不宣称实现了它。最终源码文案已修正，旧执行源码和配置保留。
- 该目录 geometryAccepted:true 仅为自由 XYZ 初筛，不能解释为表面通过；最终入口改名 freeXYZTolerancePassed。以 face-surface-check/decision.json 的 **false** 为准。
- 初次表面判定错误地比较源射线的近零初误差，后已移除这条相对零误差判据；源仍按真实像素容差检查。其他目标/第三视图失败保持，没有借修判据放行。
- 0028/0042 保留诊断，不能用 0042 一点求完整姿态；预留 0021/0036 在当前 prepared 没有可靠 local 状态，未伪造 F，也没有最终独立盲测结果。旧 8/6 仍是研发回归。

对照：ROOT/final-evidence/face-frame_0035.png、0075、0145、0058；完整 per-track / per-frame 在 face-surface-check。

## 6. 头发与镜框：具体负证据

从新观测实际三角化并检查第三视图：
- 两条镜框提议仅约 0.45° 视差，第三视图误差 5.91 / 5.16 px，拒绝。
- 另外两条镜框点约 2.52° 视差，第三误差 1.54 / 0.91 px，是有限点线索；尚无连接成真实镜架曲线的跨视图证据，其中一条第三观察没有临近可靠短线。未把四个点强连成眼镜。
- 唯一 hair 轨迹约 3.80°，拟合中位 4.88 px、第三 2.83 px，不能支撑“发际线—鬓角—耳上”连续外表面。
原生短线数量、正深度、每条观测误差在 complete-content-evidence-repair/result.json。旧 2917 发壳未更改，未刷黑、生成细丝或把反光当实体。

## 7. 背景：正确六UID上下文里的真实训练

退役：27814、27972、28096、28578、28736、28860。其余同源点保留。
从旧有效 B-mvs 的 27,970 融合点中按原生正深度、3×3 room/unknown、至少3来源观察筛得 27,915 点，不再限于旧 source 中心 180px 半径或5,002点。新增点位置、颜色、尺度、旋转与alpha实际训练；所有组件共同前向。
原始位置/法线支持范围、bounded offset、scale ±log(1.4) 与固定拓扑；本分支**无 density**，不把实际多视图稠密初始化谎称为又执行了分裂。480步不是成熟充分收敛的保证。

| 全13视图平均 L1 | 旧R0 | 新初始化 | 480步 |
|---|---:|---:|---:|
| face | .045654 | .021251 | .021251 |
| room | .044181 | .143935 | .123283 |

7个训练视图 room：.045646 → .125418 → .095255。确有相对新初值的训练改善，但仍远差旧状态。13/13 room 检查回归，**拒绝**。
参考0111脸区 q_room 从 .42761 降到 .00434；这只是已选六点替换的效果，不代表全场景错误贡献全部解决。对应 room 误差 .04738 → .25582，环境内容明显丢失，不能用脸更干净放行。
颜色、offset、scale、rotation、alpha都有非零源参数变化，详见 summary.json。完整 initial / mid240 / final480 / restored 保存了 Adam、RNG、采样、策略和元数据；恢复后 model、optimizers、samplers、RNG、strategy 均与初始一致。原模型未被候选安装。

图：ROOT/final-evidence/full-scene-comparison.jpg。原片中的柜门/天花板与衣物缺口清晰可见，未美化掩盖。

## 8. 同一资产的实际双渲染器交接

唯一诊断 PLY：ROOT/room-full-training/fixed-B-T2.ply。
SHA-256 `f00d9475341a1dc2fc7b82b5634782da204c44a56bf61ea9897a94df28b1f4fd`。
参考状态 frame_0111.png，66,281点；UID与来源侧车在 handoff-repair/candidate.identity.npz，合成失败记录为 handoff-repair/assembly-failure.json。

实际 gsplat 1.5.3 与 PlayCanvas **2.22.4**、1080×1920、同 K/C、相同固定资产；只用 baseline，未重复 LARGE/minPixelSize/fog 扫描。raw premultiplied RGBA8 读回，没有额外提亮/锐化。

| 相机 | 全幅RGB差 L1 | alpha差 L1 |
|---|---:|---:|
| 参考相机 | .030852 | .098433 |
| 固定绕看12 | .013415 | .107177 |
| 固定绕看35 | .022040 | .146069 |

参考脸区双端 RGB 差 .006037，room .043243。两端都能实际绘制，但**没有达到完全一致，也没有画质通过**。不能单凭比上一份全场景均值低便宣称修复了同一因素；本轮已换资产表示。
连续绕看：ROOT/room-full-training/fixed-orbit/fixed-asset-orbit.mp4，48帧来自同一 hash，gsplat生成。两侧相机是绕看控制量，不当作真实头部观测角；没有拿静态模型对另一个时刻的表情/衣物作伪逐像素真值。
**PlayCanvas为电脑SwiftShader；本轮鸿蒙、真机、交互FPS均未测。**

## 9. 资源、许可与剩余实现范围

RTX 5070 Laptop GPU；PyTorch 2.8.0+cu128 / gsplat1.5.3；原锁定环境未改。
跟踪修复后两窗约4.52/3.68秒，Torch峰值约2,426MiB，reserved最高3,754MiB；推理后卸载模型。
背景整个阶段135.69秒，含加载、训练和评价；train/eval计时59.73秒，**不含完整视频准备/MVS/跟踪总链路**。Torch allocated峰值766.71MiB，reserved1034MiB；设备独立202次采样峰值1274MiB，采样可能漏瞬时峰值，不等于全过程精确上界。没有OOM证据，当前质量失败不能归咎8GB。

[CoTracker官方](https://github.com/facebookresearch/co-tracker)代码固定commit；[官方权重](https://huggingface.co/facebook/cotracker3)固定revision bf55ea50d4390e1820a267f131cd6587240fb2c5。CC-BY-NC-4.0，仅隔离研究，未进入产品。
[OpenMVS固定源码](https://github.com/cdcseacave/openMVS/tree/58117204c86bbb11a0b25b26a8987676cf11274d)及本机v2.4.0 portable保留AGPL边界；未重编译或改变其阈值。[InterfaceCOLMAP像素中心代码](https://github.com/cdcseacave/openMVS/blob/58117204c86bbb11a0b25b26a8987676cf11274d/apps/InterfaceCOLMAP/InterfaceCOLMAP.cpp)与真实MVSI互证。官方方法不构成本视频质量保证。
本轮没有复现完整 Dynamic3DGaussians、LIMAP、MonoHair；没有新增它们的依赖或用其名字冒充已实现能力。

**未完成且不能声称通过**：分布充分的真实上身Q求解、成熟选窗、完整衣领/双肩/袖部深度与训练、独立解剖区域mask、连续头发/镜框结构、可见提升的脸部连续表面、完整背景替换以及最终共同更新。独立分支未被整体门禁阻塞，但其各自真实前提不足时停止；没有进入新的T3/T4面部更新。

## 10. 复现、恢复与下一项动作

入口均在W/backend，输出必须新目录，不能覆盖本轮run：

```text
run_complete_observations.py --prepared PREP --tool PINNED_COTRACKER_DIR --out NEW_OBSERVATIONS
run_complete_geometry.py --manifest ROOT/stage.json --measurements OBSERVATIONS --old-tracks OLD/F-geometry/tracks.json --out NEW_GEOMETRY
run_complete_surface_check.py --manifest ROOT/stage.json --measurements OBSERVATIONS --old-tracks OLD/F-geometry/tracks.json --geometry GEOMETRY --out NEW_SURFACE_CHECK
run_complete_room_training.py --manifest ROOT/stage.json --mvs OLD/B-mvs --source-id 13378 --retirement OLD/B-scoped-replay/retirement.json --out NEW_ROOM
```

实际路径、模型、参数和源码快照在各run，完整输入/输出hash在ROOT/receipts.json。本轮checkpoint可从自己initial恢复Adam；旧900步基线无旧Adam，仍只能warm-start。
OpenMVS实际命令与生成文件保留于room-depth-overlap日志；测试导入在pixel-handoff。首次审计侧车字段不匹配失败保留在complete-content-evidence与handoff，修复输出独立后缀repair，未覆盖失败证据。

下一项最有价值的有限动作：**复用本轮轨迹缓存，在原生肩线/衣领的轮廓与纹理上补可靠的分布测量，并把运动/视差纳入选窗；只有上身Q与真实邻接成立，才重跑该窗口衣物深度及完整目标训练。** 不重跑同一零邻接输入，不继续增加颜色训练步数；目前不能断言必须重拍，尚未完成对原片可用测量的充分提取。面部另需修复XYZ到连续表面的融合损失，这一分支与衣物可独立研究。

本地三项实现提交见commits.json；报告另行提交。原P的HEAD和dirty条目与before一致，旧R0与副本hash一致，W原有未提交条目保留，暂存区未混入他人内容。只做了7.7MB R0本地对照副本；没有授权或创建大规模独立私人资产备份，Git与hash清单不能代替该备份。未上传影像/模型/签名，未写平板。
