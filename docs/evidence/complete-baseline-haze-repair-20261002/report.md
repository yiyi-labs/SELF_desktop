# 完整基线白雾：恢复、有限真实训练与离线显示对照

日期：2026-10-02。工作目录为原工程 P；当前代码以 Git 保存。本轮没有操作已断连的平板，没有部署、回传、切换生产配置或覆盖作品。

## 结论先行

1. **完整内容基线已恢复正确。**50,095 点的全部 67 个源状态字段保持精确一致，重新导出的 PLY 与原资产 SHA-256 一致，参考画面的 RGB、alpha、部件贡献与原路径一致。没有从旧稀疏 prepared 重新初始化它。
2. **最新完整基线仍有白雾与结构缺陷。**同资产 PlayCanvas 的面部比 gsplat 清楚，但头发、颈部接缝、衣物仍明显柔化。不能把 gsplat 中更严重的灰雾直接当作平板当前看到的严重程度。
3. **实际训练已完成，但没有可采用的质量候选。**两条同预算 160 步 Adam 对照实际更新了背景补丁的 SH、alpha、尺度与旋转。单纯细分宽核改善了某些正面指标，却损伤其他视角头发、衣物或房间，予以拒绝。
4. **目前只能保留恢复与研究能力，不能宣称白雾修复成功。**完整基线没有替换，失败模型不回传。脸、头发、颈肩、衣物参数本轮未重新训练；它们显示变化来自背景合成变化，不能算作这些部件重建完成。

## 身份与冻结起点

| 项目 | 实际值 |
| --- | --- |
| 原片 | capture-1790410633104.mp4 |
| 原片 SHA-256 | 7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf |
| 完整基线 PLY SHA-256 | a343ccf05292ce1e174c7fd63795122347a8d03bd0202a19395a9a414b691f41 |
| 完整 checkpoint SHA-256 | c3425ba01892940353909dbf3f95d5058ef507e023357ef864d4cb1460cac344 |
| 原来源 | W/backend/.sources/continuity-physical-surfaces-20261001-b/body-transition-sh |
| P 中保存位置 | backend/.sources/baselines/7ac189eb49e0/a343ccf05292 |
| 总点数 | 50,095 |
| 组成 | room 26,054；face 8,286；hair 2,917；分类 accessory 5；body 12,833 |
| 导出参考状态 | frame_0010.png |
| 原头姿规范参考 | frame_0111.png；与导出参考是两个不同且已核对的概念 |
| 原生尺寸 | 1080 × 1920 |
| 本轮开始 HEAD | b5b1283b2f8444f29269cffa485ae8a6cd5db221 |
| W HEAD | e443a5a32a6a0413e052f8300e67110297e33620；未修改 |

5 个 accessory 是当前分类口径，不能解释为整副眼镜只有 5 点。完整内容基线不等于完整质量通过基线。

mtime 更晚的 shared-scene-geometry-20261002-b 候选资产 SHA 为 fd21c779eaa77d709705ff34e5118075523b3b2a5b9314458f66ad4f692355d6，未成为通过基线。本轮不按文件时间自动选择它。

此前 mainline-control / surface / structural / boundaries 对照从旧稀疏初值开始，不能代表上述完整基线退化；其结论不用于本轮放行。此前已核对的平板磁盘作品来自另一段 32 秒视频、28,802 点，也不能与本轮 65 秒原片直接作同条件比较。平板断连，当前前台显示身份未重新验证。

## 实际代码修缮

- `reconstruction_render_contract.py`：收拢实际全幅 draw/frame/ROI 数学，避免完整基线恢复依赖未提交的生产 runner 辅助函数。未改变原 quaternion/scale 绘制路径；显式 covariance 路径仍单列诊断。
- `reconstruction_complete_model.py`、`audit_complete_baseline.py`：使用上述共同合同；不调用 initialize_scene，不丢失既有共享表面、姿态、SH、协方差、来源及部件状态。
- `reconstruction_checkpoint.py`：只补允许读取标准 NumPy scalar 的数据合同；保留文件哈希检查、全局类型审查及 weights_only=True。未知可执行全局仍拒绝。
- `reconstruction_observation_domains.py`：恢复完整去畸变物理观察域，低纹理 room 像素不受 SIFT/三角支持 mask 限制。置信度不足、画幅外与人物区域不作为房间 RGB 目标。
- `reconstruction_static_planes.py`：有分布静态轨迹支持的有限平面提议，保留其“表面假设”的边界。本轮实际 surface 分支使用 grow_observed=False；没有执行扩墙或伪造稠密 MVS。
- `reconstruction_complete_room.py`：同一个完整状态上建立来源可追溯的有限背景替换事务及对照；全部部件共同排序合成。研究模式不是多个生产算法版本。
- `audit_complete_room_results.py`、`probe-complete-baseline-display.mjs`：同一资产/相机/原生画幅的实际桌面 PlayCanvas 读取、float gsplat 对照、参数更新核对及固定 PLY 绕看。

最后的元数据修订不改变训练数学：将 geometryFrozen 明确为“中心与姿态冻结，协方差可训练”；将 normalScalePreserved 明确为“初始化保留第三协方差轴，不代表已验证物理法线”；将 newSurfacePoints 改为 newRepresentationPoints；按模式区分有限平面绑定与继承高斯体积绑定，并保存父索引。既有 run 的源码/config/sidecar不被覆盖，历史字段按此解释。数值门禁通过只允许继续审查，当前代码明确 qualityAccepted=False。

## 完整恢复回归

共同合同重新重放目录：`backend/.sources/complete-baseline-common-20261002`。

- 67 个源状态字段精确一致。
- 重新导出资产 SHA 与 a343ccf… 精确一致。
- 原路径参考 RGB、alpha、q 差异为零。
- 6 个原生视角，零 optimizer 步；33.691 秒，CUDA allocated 峰值 865.371 MiB。
- 显式 covariance 与原路径的平均 RGB 差约 4.4e-8—5.9e-8，局部最大约 0.00077—0.00287；局部贡献通道容差仍有未通过项。该差异不能解释全画面的重灰雾，因此继续保留原 quaternion/scale 路径，未取消半径限制或改 CUDA clamp。

K 的原始 float64 储存转 float32 最大差为 4.76148e-5；实际训练器与本次显示均使用相同 float32 K，逐元素一致。没有将正常储存转换误判成相机错误。

## 背景真实表面提议：具体阻塞

`complete-room-surface-20261002` 至 `-f` 各次前置失败都保留，没有进入 Adam、没有导出可发布候选。其实现依次补齐了三角来源后代、先归因后限额、原 23 个世界训练观察、真实透明合成贡献和有限邻域平面核查。

最终 `-f/selection-diagnostic.json`：

- 8 个分布静态平面假设，独立锚点数量分别为 362、205、124、92、75、59、56、49。
- 来源可追溯的宽核分别为 34、9、4、8、9、1、7、20。
- 这些平面组对参考脸区的实际平均 q_room 最大只有 4.7293e-6。RGB 标签重放差为 0，贡献守恒检查成立。
- 实际覆盖脸部的最大单核来自 source_kind=0 / POINT3D_ID=13378，平均贡献为 0.14169735；96 邻域内未得到满足分布与有限域检查的可用替代表面。12311、18155、17521 家族的有限局部检查同样未通过。
- 后续对照选中的 13378 家族 14 个后代，参考脸区贡献合计 0.27172196；基线脸区总 q_room 为 0.27286127。

最后两个数的分母是**该参考状态的脸区 room 贡献**，不是全场景错误或全部白雾的责任比例。一个来源家族可能覆盖不同物理表面，不能由一个点外推整面墙，也不能直接删掉它承担的有效背景。

本轮没有放松几何阈值、把冲突统一改 unknown、安装新 MVS 或制造墙面。因此这条分支得出的是具体几何支持缺口，不是“所有背景都没有特征”。

## 两条真实 GPU 对照

训练使用既有 23 个可信世界训练观察、同一顺序/种子100216、同一 160 步预算与原生全幅共同前向。评价为参考0010（本身在训练集）及0015、0035、0115、0130、0145五个开发检查。不是完整8开发/6回归重验，更不是独立最终盲测。

所有源67字段冻结；仅 replacement patch 的 SH、opacity logit、log_scale、quaternion 由 Adam 更新。中心、offset、姿态与其他部件参数不变。房间颜色只由有效 room RGB/结构监督；人物 RGB 用于回归评价，不训练成背景的肤色。非增污染与覆盖约束通过共同合成贡献起作用，不强制所有 q_room 为零。

### 对照：原宽核同表示恢复

目录：`backend/.sources/complete-room-wide-control-20261002`。

14 个父核以相同 14 个初值替换，总量仍50,095。4组Adam源参数实际step=160。无预定数值退化条目，但画面没有明确去雾改善，所以**没有采用**。

资产 SHA：28e16586a90990d83b7cb1b963358ad7e78e1ac27699f7d4ee772e6cc5ff34ee。

### 候选：继承体积的局部细分恢复

目录：`backend/.sources/complete-room-local-resample-20261002`。

同14父核替换为126子核，总量50,207。子核仅沿继承协方差的前两轴3×3分布，第三轴初始化保留；这是**表示容量诊断，不是新增独立几何证据**。alpha分摊不是透明合成恒等。

4组Adam源参数实际step=160；log_scale/quat/opacity/SH的最大变化分别为0.112402、0.023175、0.610314、0.285730。完整Adam、RNG、采样剩余、绑定、初/中/终状态均已保存。新建Adam，不宣称从旧缺失optimizer精确resume。

资产 SHA：4cd2c328c1ebc1d195e5675f6df738428c2aa004f48fe306a6f90da20c55442d。

预先固定的检查为RGB退化>0.003、平均alpha下降>0.015、alpha<0.8比例增加>0.02。候选失败：

- room_rgb：frame_0010.png
- body_rgb：frame_0015.png、frame_0115.png
- hair_rgb：frame_0130.png、frame_0145.png

低alpha比例不是物理空洞真值，高alpha也不是正确背景证明。候选**不可采用、不可回传**；参数不回写源资产。

### 参考0010：同口径 float gsplat

| 指标 | 完整基线 | 同表示控制 | 被拒细分 |
| --- | ---: | ---: | ---: |
| face 固定区域 RGB L1 | 0.096323 | 0.097509 | 0.061999 |
| face q_room | 0.272861 | 0.270850 | 0.158579 |
| hair RGB L1 | 0.224791 | 0.226805 | 0.148428 |
| body RGB L1 | 0.050563 | 0.050708 | 0.051026 |
| observed_room RGB L1 | 0.026727 | 0.026456 | 0.031103 |

参考脸区改善不能代替其他视角通过，也不能证明头发结构被修复。

| 资源 | 同表示控制 | 被拒细分 |
| --- | ---: | ---: |
| Adam训练 | 19.291秒 | 18.304秒 |
| 加载、选取、评价、导出总计 | 86.285秒 | 84.861秒 |
| allocated峰值 | 4,087.973MiB | 4,087.349MiB |
| reserved峰值 | 4,488MiB | 4,506MiB |

本次无OOM，8GB不是此局部实验已证实的瓶颈。上述时间不含原片准备，不是完整新视频建模耗时，也不是达成2—3分钟或所有任务8GB可用的保证。

## PlayCanvas真实绘制与固定资产绕看

PlayCanvas实际版本2.22.4，桌面Chrome/SwiftShader，1080×1920、同原始参考C/K、同原始颜色，读取GL预乘RGBA8后翻转行，未再次乘alpha。compact、minPixelSize=2、AA关闭；没有fog、额外后处理或加光锐化。没有改生产查看器。

实际加载50,095/50,095/50,207点，三资产均无JS异常。它证明桌面绘制，不证明HarmonyOS绘制、交互性能或设备FPS。

| 原片固定区域 RGB L1 | 基线PlayCanvas | 控制PlayCanvas | 被拒候选PlayCanvas |
| --- | ---: | ---: | ---: |
| face | 0.025212 | 0.025128 | 0.025348 |
| hair | 0.044775 | 0.044280 | 0.043853 |
| body | 0.055995 | 0.056009 | 0.055989 |
| observed_room | 0.130149 | 0.133436 | 0.098974 |
| 全幅PlayCanvas—gsplat差 | 0.090770 | 0.092510 | 0.061552 |

桌面画面检查：基线面部比gsplat的灰雾清楚，颈部接缝、衣物、发壳柔化仍明显。细分在gsplat的脸区改善没有成为PlayCanvas明显面部改善。已知宽核对两引擎的影响不同，剩余差异未被完全归因；不能宣称是fog或更改全局gamma来修复。PlayCanvas observed_room中alpha<0.8比例0.361399→0.350429，仅是覆盖代理。

对照图片从左至右：原片、完整基线、同表示控制、被拒细分。

- [PlayCanvas原生画幅对照](D:/STUDY/College/mine/olay/backend/.sources/complete-room-local-resample-20261002/analysis-e/source-pc-baseline-control-rejected.png)
- [gsplat原生画幅对照](D:/STUDY/College/mine/olay/backend/.sources/complete-room-local-resample-20261002/analysis-e/source-gs-baseline-control-rejected.png)

以下为**gsplat1.5.3**参考状态固定PLY诊断视频，各61帧、24fps、1080×1920，相机控制0→−60→+60→0。控制yaw不是实际人脸观测yaw，未观察区域不承诺可靠外推；没有逐角度更换资产。视频也不是PlayCanvas或鸿蒙录屏。

- [完整基线绕看](D:/STUDY/College/mine/olay/backend/.sources/complete-room-local-resample-20261002/analysis-b/baseline-fixed-ply-orbit.mp4)；视频SHA edece9b93b3f7e127688d0ffda8e51805112bfb626716f54e7e07f9cc8caffd7
- [控制绕看](D:/STUDY/College/mine/olay/backend/.sources/complete-room-local-resample-20261002/analysis-b/control-fixed-ply-orbit.mp4)
- [被拒细分绕看](D:/STUDY/College/mine/olay/backend/.sources/complete-room-local-resample-20261002/analysis-b/rejected-resample-fixed-ply-orbit.mp4)

每份视频记录asset hash、相机矩阵、参考时刻及video hash，绘制前后资产哈希不变。记录在analysis-b/report.json；参数及颜色核对在analysis-e/report.json。

## 可复现入口与保存

实际训练run里的algorithm-source与source-hashes.json保存当时真实代码闭包，包含工作区尚未提交的依赖；单看Git HEAD不能反推当时源码。当前共同绘制模块消除了对dirty runner的辅助函数依赖，其像素/梯度回归及重新恢复基线已经实际通过。历史源码与失败目录完整保留。

命令中的fresh输出必须换成未存在的目录；以下仅示出可复用入口，不重新覆盖本轮run：

```text
# 在WSL的P/backend，使用 /opt/self-reconstruction/venv/bin/python -B
audit_complete_baseline.py --manifest reconstruction_baseline.json --out .sources/<fresh-recovery>
reconstruction_complete_room.py --mode surface --steps 160 --out .sources/<fresh-surface>
reconstruction_complete_room.py --mode wide-control --steps 160 --out .sources/<fresh-control>
reconstruction_complete_room.py --mode local-resample --steps 160 --out .sources/<fresh-resample>

# Windows P，配置提供当前私有资产完整路径、已核对C/K和hash
node scripts/probe-complete-baseline-display.mjs <private-display-config> <fresh-private-display-out>

# WSL P/backend；candidate/playcanvas目录提供上一步真实像素
audit_complete_room_results.py --control <control-dir> --candidate <candidate-dir> --out <fresh-analysis> --orbit-frames 61
```

上述研究入口可在新捕获建立可信checkpoint后使用；没有硬编码本人人脸坐标、历史窗口或source13378到算法选择中。本次选择自动来自训练观察的真实贡献及来源。锁定baseline manifest只固定本次比较的身份，不能把旧本人模型当作新视频输出。

28项测试实际通过：checkpoint6、complete-room9、fullframe4、portrait-model9，包含真实CUDA像素/源参数梯度对照、事务保护、完整观察mask和绑定回归；最终复验2.870秒，记录见同目录validation.log；JS语法检查通过。测试通过不等于候选质量通过。

原profile/服务入口没有在本轮变更，也没有把complete-state研究stage接成新视频默认生成器。不能把这些离线结果说成“鸿蒙端已全量接入”。之前运行时源码hash存在不一致的记录仍需另行核验；HTTP健康或旧心跳不能代替新任务实际调用证据。

## 状态与下一项动作

| 项目 | 状态 |
| --- | --- |
| 完整基线恢复、字段/哈希/参考画面一致 | 通过 |
| 原生共同绘制合同与关键梯度 | 通过 |
| 两次有限Adam更新、保存和回读 | 通过，非质量结论 |
| 桌面PlayCanvas三资产实际绘制 | 通过，仍有明显模型和跨引擎问题 |
| 有证据的物理表面接替目标宽核 | 未通过：目标来源附近无可接受有限表面 |
| 单纯宽核细分且不损伤其他部位 | 失败，候选拒绝 |
| 头发、镜框、颈部接缝和衣物结构修复 | 本轮未实现 |
| 完整新视频流程/2—3分钟/全部E1—E5 | 未验证或未通过 |
| 当前鸿蒙显示及性能 | 未测：平板断连 |
| 生产接入、部署和回传 | 未执行，未采用失败资产 |

下一项最有价值的修改是：**在自动归因得到的宽核家族承担的原片静态区域中，区分真实多表面，增加可核验的局部深度/连续表面支持，再事务替换并恢复其有效背景内容。**来源家族只作为查找入口，不能作为单平面；脸前错误贡献与正确柜墙贡献须同时评价。不能再靠同一宽体积细分、全局压opacity、删背景或拉长训练取得表面上的去雾。

头发、镜框、头颈运动和衣领—皮肤接触仍有独立结构缺口；这次背景表示试验未解决它们。可靠本人局部研究不需要无限等待房间全部通过，但最终发布仍要求共同遮挡、连续内容和实际显示验收。

代码与聚焦报告单独本地提交，不夹带其他dirty/staged文件。私有影像、checkpoint、PLY和视频在项目.sources固定目录，Git忽略；本机保留不等于外部独立备份，本轮未建立外部备份、未上传私人数据、未清理历史实验。
