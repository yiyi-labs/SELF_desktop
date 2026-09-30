# 通用观测与规范表面交接修缮：实际结果

日期：2026-09-30。限定后端研究；不是生产默认更新，不是整体建模通过。

## 先回答结果

- 本轮修改的是可复用算法和数据合同，没有把用户视频帧号、个人脸部坐标、衣物图案或 room 来源ID写进新算法。
- 查实并修正了原生仿射图块测量的通用问题：ECC矩阵的平移列是相对图块原点的量，不能直接当成图块中心的位移。旋转/缩放后，中心位移必须计算 A*c+t-c。合成真实纹理的旋转/缩放/平移回归通过。
- 新增按真实时间戳连接的连续源帧提议、部件ROI提高有效网络分辨率、早/中段重播种、原生像素复核。没有用 image ID 当源帧序号，没有复制中间帧 F/C/mask。
- 共享规范顶点场现在通过同一个姿态传递算子进入测量求解和实际高斯绘制，协方差使用 JΣJᵀ；真实求解和两组240步 Adam训练已执行。几何投影误差改善，但**画质没有优于R0，不保留候选为生产模型**。
- 第一次候选训练出现非有限梯度，证据保留。研究绘制改用 gsplat 1.5.3 原生 covars 反传，导出才分解回旋转/尺度。修复后两组训练有限、真实参数更新，像素/梯度与实际PLY回载检查通过。
- 新可靠对应尚不足以支撑完整发型、镜架、双肩/衣领三维表面。本轮没有再次训练房间、没有更新衣物几何、没有新T3/T4。不能把观测提取改善写成这些部件已修复。
- 18项回归通过。PlayCanvas/HarmonyOS新候选均未测试、未部署、未回传。既有 E1—E5、应用、签名、作品、USB、编辑与故事保持不变。

## 身份、基线和文件范围

W：C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay
P：D:/STUDY/College/mine/olay

W起始HEAD：5c9dcbda50929f3c37421e5ed36a5244152d0181。
P起始/结束HEAD：3dad0cd5651824cc06d9e88d61aabdd2642c0b30，以现场 before.json 为准。
没有reset、clean、stash、rebase、amend、历史实验删除或原工程写入。保留W原有未跟踪证据；本地提交只列本任务文件。

研究ROOT：W/backend/.sources/canonical-observation-repair-20260930-a。
PREP：P/backend/.sources/integrated-components-v2-20260928-e。
源片SHA256：7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf。
R0：W/backend/.sources/fullframe-surface-patch-20260929-b/R0-frozen.pt。
R0 SHA256：2468edc379f8b76eac97fccfbf9e9a4c775f980102b95283ee15b2dc4cee7cb8。

| 文件 | 实际变化/用途 |
|---|---|
| backend/reconstruction_temporal_observations.py | 时间戳/源索引严格关联、质量/覆盖/运动选窗、原生ROI像素中心变换、中心位移与对称仿射复核 |
| backend/run_continuous_observations.py | 连续源视频区域提议；训练观察独立于世界C；原生测量，不复制未知相机 |
| backend/reconstruction_canonical_surface.py | 同一规范位移场、逐顶点姿态传递、表面协方差运输；训练原生covars，导出分解 |
| backend/reconstruction_evidence_stage.py | 仅新增可选研究模型类；不传参数时仍用旧类，不切默认 |
| backend/run_canonical_surface_repair.py | 固定拓扑规范表面求解、同预算控制/候选外观训练、非有限即拒绝 |
| backend/audit_continuous_observations.py | 冻结提议缓存的原生复核、末观察三维检查，不把头F当衣物B |
| backend/audit_canonical_surface_handoff.py | 同资产原生绘制/PLY回载与固定绕看，不导入设备发布接口 |
| backend/test_reconstruction_canonical_surface.py | 多姿态/尺度、横竖尺寸、异常索引、无眼镜、像素/梯度和真实纹理仿射回归 |

新训练/审计实际运行源码在各输出 algorithm-source 或脚本副本。最终代码随后补充了异常索引、失败文件保护、未知区域检查及审计尺寸自动读取；不得把最终Git源码hash冒充早期运行源码hash。receipts.json分别记录它们。

## 连续观测：实际运行，不等于三维已成立

选窗规则只读训练观察的时间戳、清晰度、可见覆盖和相机中心变化。开发8帧/固定回归6帧在提议阶段也排除；在它们的时间点切断窗口，避免拿留出RGB构造提议。当前同一头部质量窗口也用于body提议：**尚非独立、成熟的上身近刚性/视差选窗**。

本次规则选出两段训练窗口（输出身份，非写死选择）：0022—0028、0037—0043；每段33个实际源帧，约12Hz，中间帧仅跟踪提议。14个源片解码/去畸变锚帧与缓存RGB平均差均为0。解码器有H.264告警，不能由锚帧一致推断所有中间帧都无编码问题；告警保留在log。

头ROI网络有效缩放约0.57/0.56；原全幅缩放约0.20。没有降低最终1080×1920图像监督精度。
前向/反向可见性、原生FB≤2px、25px真实纹理仿射、相关≥0.78、中心偏移≤3px、有限伸缩和循环约束，最后仍查真实部件mask/unknown。不是放宽相关/颜色阈值。

| 提议对应分类 | 初次原点平移口径 | 中心修正+完整unknown保护后 |
|---|---:|---:|
| face | 9 | 22 |
| hair | 20 | 28 |
| glasses | 7 | 9 |
| 下左衣物空间格 | 10 | 20 |
| 下中衣物空间格 | 24 | 35 |

两列复用同四份冻结网络提议；也包括修正后UV的unknown复核差异，不称严格唯一因素计数实验。数字是跨播种提议数，**不是独立表面面积、唯一物理点数或三维真实点数**。旧上一轮不同选窗的数量不能作为本轮同条件因果对照。

实际头局部三维代理检查：
- 以记录的F/K作短窗口近刚性假设；最后观察不参与XYZ拟合。
- 正深度、拟合P90≤2px、夹角≥2°、末观察≤2px：face 4/22、hair 3/28、glasses 1/9。
- 这不是外部深度真值，也没有证明表达/局部头姿完全准确。它仅说明大部分2D对应不能直接拿去建模。
- 上部衣物格仍没有可靠轨迹；下方55条提议不能证明双肩/衣领成立。未伪造B_t，没有把头部F用于衣物三角化。
- 无眼镜用户的空镜框mask回归通过，不要求每个用户都出现镜框部件。

ROOT/continuous-observations/config.json记录选窗、源时间、模型/权重hash、锚帧差；native-center-corrected/measurements.json记录每条三维检查及拒绝。原始提议文件hash仍不变。

CoTracker是像素跟踪提议，不是识别人像细节的大模型。复用已安装固定代码82e02e8029753ad4ef13cf06be7f4fc5facdda4d、权重SHA205d34789f19699d64b22cf93f9b697f15f28d4025240e31532e504109837218，未下载升级依赖。官方许可CC-BY-NC仅作当前隔离研究，不新增为产品默认依赖。[官方说明](https://github.com/facebookresearch/co-tracker)

## 规范表面：求解器与真正绘制用同一位移

输入仍为上一轮112条测量缓存，未混入本轮新提议，因此本对照与观测提取分开：
同K/F/C、尺度、身份、表达、拓扑；866个相关及邻接顶点的同一个规范3D场。用面积加权局部旋转传递到观测mesh；图像残差使用原生sigma，而非把每条信息矩阵最大特征值都归一到1。TRF软L1有界求解15次函数评估。

| 原生px | R0中位/P90 | 规范场中位/P90 |
|---|---:|---:|
| 源 | 0.000032 / 0.000084 | 1.072 / 2.492 |
| 目标 | 2.404 / 5.973 | 1.403 / 4.441 |
| 末观察 | 2.502 / 7.063 | 1.874 / 5.214 |

源初始接近0来自射线构造，不是3D真值。目标/末观察有所改善，但P90仍超过预先4px容差，**几何未放行**。没有大姿态漂移、自由2Dwarp或身份变化来降误差。

皮肤高斯中心随实际mesh变化；基底和协方差用三角的切向变形+单位法向运输。眼镜不被切向拉成皮肤，既有头发点未伸缩为新发型。原始拓扑、UID、绑定、来源不增加、不删点。不是“只在图像上移动色块”。

首轮face输出含非有限参数，失败记录保留，资产无效。采用原生covars反传后等轴/各向异性核的像素与源参数梯度回归通过，不改全局CUDA。[锁定gsplat1.5.3接口](https://docs.gsplat.studio/versions/1.5.3/apis/rasterization.html)

## 真实外观训练：同预算但没有胜出

ROOT/face-covariance-safe中：
- appearance-control：R0几何。
- canonical-appearance：规范场几何。
- 各240步、每步一个原生全幅视图、同sampler种子/帧序/参数组/损失；完整前向后mask损失，多个部件共同参与T0人像透明合成。
- 只更新皮肤SH、alpha、局部scale、quaternion；几何场、F/K、头发、镜框、身体、room固定。scale范围相对初始化±log(1.2)，无density、无新的joint人物更新。
- T0是局部研究；参考T2含同一冻结room/body共同排序，不是完整场景已修复。
- 真实参数平均绝对变化见result.json；不是增加步数后换一份平均表宣布通过。

| 全幅后切固定ROI RGB L1 | R0 | 同预算外观控制 | 规范场+外观 |
|---|---:|---:|---:|
| 原8开发帧 | .0311001 | .0314553 | .0315102 |
| 原6固定回归帧 | .0417701 | .0424380 | .0426257 |

6/6固定回归帧都变差；部分开发帧变好，不能据此选新模型。查看原片/R0/控制/候选四列，仍有厚发壳、镜框/耳颈污染、皮肤柔化，未出现足以保留的真实结构提升。**两组训练候选均拒绝，不切生产、不回传。**
这一失败不证伪“运动补偿/共享表面”全部路线，也不支持继续无界加步数。当前粗表示和测量/形变误差仍需分别解决。

全部初始、中120、终240、恢复checkpoint均含Adam、RNG、采样器、策略和完整模型。初始→restored逐字段对比model/optimizers/samplers/rng/strategy均为true。原R0没有旧Adam，本次是warm-start，不称从旧900步精确resume。

## 固定资产与绘制交接

参考frame_0111.png，38,372点。UID与拓扑同原R0；没有生产编辑mask迁移。

| 研究PLY | SHA256 | 原生训练绘制与回载RGB平均差/最大差 |
|---|---|---:|
| 控制 | 4696a1652fd898c03e7bab3697a04a91d6a308642c202893b159a5c37710b4fb | 4.73e-8 / .000909 |
| 规范场候选 | ec35404396e9a1e37033082629fef446f922aee55672900ee9797dd54265869c | 5.90e-8 / .001235 |

alpha/q也保存。数值往返容差通过；这是gsplat原生covars→标准PLY→gsplat，不是PlayCanvas/鸿蒙一致性验收。

同一候选hash绕看49帧，K与参考状态固定，相机量是viewer绕看控制，不当本人真实观察角：
ROOT/handoff/fixed-orbit/diagnostic-only-gsplat.mp4。
来自gsplat1.5.3；视频编码540×960，原绘制帧1080×1920；12fps只是编码播放率，不是平板交互fps。
ROOT/handoff/frame_0015.png-comparison.png、0095、0145分别为四列对照（按预先开发列表首/中/尾取，不按效果选图）。

最新候选PlayCanvas/HarmonyOS未测试，不复用历史设备报告。失败T2上下文不会通过这份数值回载结果获准发布。

## 时间、显存和一般性边界

RTX5070 Laptop 8GB、PyTorch2.8.0+cu128、gsplat1.5.3，原环境未升级。
- 连续解码/跟踪/原生复核阶段47.47秒；Torch峰值allocated 2528.57MiB，reserved 3790MiB。
- 规范求解+两组240步训练+评价/导出合计100.31秒；训练峰值allocated 2715.44MiB，reserved 3116MiB。
- 绘制交接/绕看31.52秒；这些不是采集→SfM→FLAME→完整场景的总耗时，不宣称2—3分钟全链路。
- 没有OOM。Torch峰值不包含完整Windows图形/驱动内存，不称全过程设备独立精确上界。
- 只对当前原片跑了实测。多尺寸、多尺度、多刚体姿态及无眼镜回归证明合同可泛化，**不等于跨人物重建画质已验证**。
- 没有生成毛孔、锐化/磨皮、刷黑头发、假高光、背景贴片或只改截图。
- 原room、旧发壳、旧body未改；局部进步不能冒充完整内容已连续。

## 可复现入口和后续唯一主要动作

在W/backend锁定环境执行，OUT必须是新目录：
1. run_continuous_observations.py --prepared PREP --split 原observations.json --tool 固定CoTracker目录 --out NEW_PROPOSALS
2. audit_continuous_observations.py --prepared PREP --proposals PROPOSALS --out NEW_NATIVE_CHECK
3. run_canonical_surface_repair.py --manifest ROOT/stage.json --measurements 上一轮measurements-visible-reverse --old-tracks 上一轮F-geometry/tracks.json --out NEW_FACE --steps 240
4. audit_canonical_surface_handoff.py --root FACE --out NEW_HANDOFF
5. python -m unittest -v test_reconstruction_canonical_surface test_reconstruction_complete_contract

必须区分本次face实验用旧112条测量与新提议阶段，不能称“22条新face已经用于本轮训练”。一次性审计输出不成为生产输入。各命令不调用发布/设备接口。

下一项最有价值的有限动作：**把新的原生部件观测接入有不确定性和实际形变检查的共享几何阶段，先验证局部F与物理track一致，再把可靠约束传给同一个规范表面；衣领/肩线需另外提取分布观测，不能用胸前轨迹替代。**
保留源、目标、第三视图；反光/遮挡/弱深度观测仍拒绝，不把权重优化到零，不继续相同120/900步或空MVS重跑。
可靠新几何不足时，保持该部件旧研究表示和失败状态，不切产品；新的连续表面容量/衣物/房间训练仍是明确未完成项。

本轮保留的正向成果是**通用测量、数据关联、几何—绘制一致性与数值稳定性代码**；尚无可发布的画质改善模型。私人checkpoint/图像/PLY不进Git，也未独立外部备份；Git不能恢复被忽略资产，现有文件均保留。
