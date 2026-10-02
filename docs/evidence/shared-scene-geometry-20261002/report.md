# SELF：共享完整场景几何、受保护训练与衣物运动交接

2026-10-02。本轮在已有隔离worktree执行代码修改、真实GPU训练和真实图像测量。保留E1—E5，没有发布、部署、回传、切换生产默认或覆盖旧作品。

**结论：完成了可复用共享几何阶段、显存执行修正和衣物交接保护，但没有彻底解决白雾、衣物裁切、颈部接缝和发壳。新模型不采用。不能把数值回归未触发当作完整画质通过。**

## 1. 现场与固定身份

- W：C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay；起始HEAD `1455dd3761234b5491b3ad117819f811d36e34b6`，分支codex/reconstruction-v3-audit-20260928。
- P：D:/STUDY/College/mine/olay；HEAD `3dad0cd5651824cc06d9e88d61aabdd2642c0b30`。本轮没有向P写文件；原有18个tracked修改和未跟踪文件保留，不顺带提交。
- W既有build_continuity_candidates.py修改、observed-coverage文件、旧日志和其他未跟踪证据均保留，不纳入本任务提交。
- 完整研究基线：W/backend/.sources/continuity-physical-surfaces-20261001-b/body-transition-sh。它是完整内容研究候选，质量没有通过，不称正式发布作品。
- 基线PLY SHA256 `a343ccf05292ce1e174c7fd63795122347a8d03bd0202a19395a9a414b691f41`；检查点 `c3425ba01892940353909dbf3f95d5058ef507e023357ef864d4cb1460cac344`。
- sourceHash `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`，capture-1790410633104.mp4。原片有两侧本人观察；世界连接和运动一致性未通过不能改写成“没有拍到另一侧”。
- preparedHash `e67d4dce02f9874e0befe15486532f80458f8a62a23221324fcc5abefc2e5301`；缓存深度manifest `11391f4d5f55cf1d1d1fa5bd7ba314b006879affa0783be5dc5d8d59cdaeba23`。
- 原生1080×1920；FLAME Open、torch2.8.0+cu128、gsplat1.5.3、head-local-SH1、完整投影/共同排序/透明合成后切ROI、标准PLY和PlayCanvas2.22.4保持。
- 50095点：room26054、face8286、hair2917、classified accessory5、body12833。五个稳定分类点不代表整副镜架只有五点。
- 本轮已进入GPU训练的分支将实际源码、配置、初始化/中期/终态/恢复检查点及私人资产保存在新的.sources目录；前置检查失败的运行可能只有错误记录或空目录，未伪造检查点。Git只保存代码和文字证据，不是独立私人资产备份；没有外部备份、上传或清理。

## 2. 实际实现

### 共享背景几何

reconstruction_shared_scene_geometry.py与run_shared_scene_geometry.py实现一个由多个视角共同约束的规范空间位移场。96个确定性分布的控制节点，法线和深度层保护，三维位移及解析Jacobian同步更新中心与协方差；SH1随局部极分解旋转。没有每帧2D warp、自由相机、逐帧scale、全局缩点、隐藏人物或删除背景。

单节点每坐标最大32原生像素尺度，不是32像素欧氏球。未知层不被强行接到邻近表面；仍保留RGB表示。表面法线来自原核协方差，是当前表示假设，不是独立测量真值。极分解的SH方向运输保持已有stop-gradient约定，以避免重复奇异值处不稳定的SVD反传；中心与显式协方差具有真实几何梯度，不宣称SH方向旋转本身也反传。

读取384个实际COLMAP长轨迹锚，用POINT3D_ID、imageName、point2D_idx及原相机模型关联。没有新匹配。缓存预测深度只作条件先验；至少三图且共享世界散布/距离通过才用于几何项。完整room有效RGB和结构窗口不受SIFT/三角支持mask限制。

全部人物/环境共同前向；face/hair/neck/cloth有逐像素退化保护，真实覆盖有约束。人物参数完全冻结以保护本轮比较，旧人像本身未重新训练。各部位按有效像素归一化，不用背景面积淹没人脸。

### 衣物观测和运动

run_measured_body_handoff.py接通共享X与受限上身运动的真实像素求解。移动人物不再先按静态三角化误差判死；仍要求多视角误差、正深度、视差和数据Jacobian成立。相机C、K、尺度与参考状态固定，不制造世界位姿。

同一物理轨迹一个X；源、目标都约束；最后一图不参与拟合，稳定hash划出的整条轨迹组不参与运动求解。增加消去XYZ后的数据Schur信息，正则不能冒充可辨识性。新canonicalize_sources严格要求已验证运动及全部源时刻，不会对未知源默认单位矩阵。XYZ、协方差方向和SH使用同一反变换合同。

run_locked_body_tracks.py适配已有固定CoTracker3模型，多帧网络仅提议；实际坐标必须通过原生25×25真实patch、前后向、仿射和第三图循环检查。保留可见性/颜色/清晰度拒绝，不降低阈值。网络预处理align_corners与原生坐标往返已测试。

普通刚体不足时，限定试验包含共享加速度时间基、8度范围对照、条件初值不确定性对照及两节点上下身连续运动。两节点固定规范材料权重，跨图共享，不是每帧自由形变或2D变形；单矩阵B输出为空，防止被旧刚体运输器误消费。随后基于静态投影核对增加一次四时间节点、18参数的共享运动对照；参考状态与相机固定，首节点固定以去掉常量姿态规范，二阶差分有限正则。不是逐帧自由位姿，旋转参数是每坐标范围，不能当成SO(3)总转角硬上限。所有候选均未通过，未应用于现有衣物或颈部。

### 深度交接

run_static_depth_calibration.py用真实静态轨迹做每窗口共享逆深度两参数校验，按POINT3D_ID分训练/留出，重复观察不跨组泄漏。未改SfM、相机或原深度缓存，也没有把静态校验外推成衣物深度真值。

这些模块均是隔离可调用stage，参数/输入由命令和合同传入，不硬编码该人的三维坐标、衣服logo、历史窗口或帧ID。测试视频仍只有一段，跨用户泛化未验证。

## 3. GPU对照与资源修正

固定23个有可靠world C的训练观察。原32train/8development/6固定回归不更换；只有5个开发观察具备world C，6个固定回归不能伪造完整场景合成。它们已参与长期研发，不称最终盲测。

控制240次外观Adam；共享几何120次几何Adam＋120次外观Adam。同总反传预算、种子和图像顺序。二者外观步数不同，是集成调度比较，不称纯粹一个几何因素A/B。拓扑、点数、UID、来源均固定，无新增density。SH/alpha/scale实际更新；控制field Adam状态为空，共享field Adam实际120步。

.sources/shared-scene-geometry-20261002-a保存最初执行。原训练渲染路径对26054个room核一次性做极/特征分解，显式协方差绘制并不使用其中的四元数/scale分解结果，导致不必要的大CUDA工作空间。

修正：训练直接使用JΣJᵀ；必要SVD固定512批，标准PLY导出才分解四元数/scale。不改变像素、拓扑或几何精度。对a终态相同检查点的原生全幅核对，RGB/alpha/q最大差均0；真实几何梯度有限。该核对与完整训练分开。

| b实际执行 | Adam总步 | 几何步 | 纯训练秒 | Torch allocated/reserved峰值MiB |
|---|---:|---:|---:|---:|
| appearance-control | 240 | 0 | 40.832 | 764.87 / 1012 |
| shared-geometry | 240 | 120 | 54.691 | 772.33 / 1020 |

a共享分支allocated7314.15MiB、reserved14146MiB；reserved不等于实际驻留物理显存，也不能当作模型更细致的证据。b使用实际峰值检查6144MiB预算，不再只查瞬时allocated。本机Torch报告设备总量8123.44MiB；没有OOM。更高峰值本身不保证速度或质量。

a旧trainingSeconds包含终态评价/导出，不能与b纯训练秒直接相除声称加速倍数。b两分支完整运行356.633秒，仍不含原视频准备和最新显示检查，不能宣称完成2—3分钟全链路。

## 4. 实际质量：小幅进展，仍拒绝

下表为5个world开发观察，同固定mask，RGB L1包含缺失像素。

| 部位 | 完整起点 | 外观控制 | 共享几何 |
|---|---:|---:|---:|
| face | .058422 | .058570 | .057523 |
| hair | .138903 | .138653 | .133645 |
| neck | .098850 | .098871 | .098512 |
| cloth | .129719 | .129659 | .129563 |
| room | .041586 | .040019 | .040396 |
| 原片低纹理room | .038941 | .037321 | .037743 |
| 衣物边界9px带 | .196082 | .195963 | .196187 |

两分支没有触发既有逐视角数值退化屏，但衣物边界的小幅变差明确保留。共享分支face上room贡献.113078→.109513，正亮度偏差.051380→.050491，变化很小；hair的room贡献.229202→.219542，不代表发型重新训练成功。

低纹理room alpha<.8比例.005443→.005455，近似不变；衣物边界.022459→.020385。alpha代理不能证明真实内容完整。实际图像仍有薄雾、柔化鼻唇镜框、粗头发、下颌与颈部色/几何接缝和衣物淡化。没有显著去雾或真实发丝恢复，不称主目标实现。

共享场景最大位移25.742原生像素尺度；120步field参数确实更新。本人67个源状态字段完全不变，头发、镜架和衣物的新增GPU训练步数为0；不能把遮挡改变说成这些部件重建改善。

[原片／完整基线／控制／共享几何](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/shared-scene-geometry-20261002-b/quality/frame_0010.png.jpg)

[面部同脸宽对照](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/shared-scene-geometry-20261002-b/quality/frame_0010.png.face.png)

## 5. 衣物失败与深度证据

缓存17个不同训练world图中，22020点有至少三图取样，只有2点通过当前共享世界散布/距离规则。room mask不能证明点真的可见；此关联只是条件先验，不是测量表面。不靠放宽此规则生成雾片。

静态逆深度校验结果：

| 窗口 | 记录/独立点 | 留出相对深度P90，前→后 | 留出中位，前→后 | 决策 |
|---|---:|---:|---:|---|
| 0 | 2058 / 844 | .151757→.100058 | .063138→.017048 | 拒绝：P90仍超.08 |
| 1 | 2011 / 908 | .071070→.048478 | .032067→.013370 | 仅条件静态锚校验通过 |
| 2 | 2199 / 1278 | .574034→.210293 | .073135→.092534 | 拒绝：中位变差，shift触边 |

唯一通过的窗口没有被全局平均或套用衣物。窗口0/1存在同imageName的不同预测，不能dictionary最后一项胜出就宣称深度一致。当前衣物初始化优先参考0025（窗口0）；预测误差不能被5%先验当作三维真值。最终stage已补每源cache文件、窗口、hash和初值存储。

| CPU研究候选 | 实际测量 | 模型 | 共享点通过 | 留出最后图P90px | 状态 |
|---|---|---|---:|---:|---|
| body-b | 389去重缓存原生轨迹 | 6速度，4度 | 51 | 3.018 | 80次未收敛，拒绝 |
| body-c | 同389 | 12加速度 | 62 | 6.809 | 留出变差，拒绝 |
| body-d | 新47原生复核轨迹 | 6速度，4度 | 1 | 3.195 | 拒绝 |
| body-e | 同47 | 6速度，8度 | 1 | 3.227 | 旋转不再触边仍失败 |
| body-f | 同47 | 8度，XYZ条件范围15% | 0 | 4.137 | 留出变差，拒绝 |
| body-g | 同47 | 连续两节点，8度 | 0 | 3.464 | 拒绝 |
| body-i | 同47 | 四时间节点，18参数 | 4 | 11.130 | 训练中位下降但尾部及留出变差，拒绝 |

XYZ范围对照同时改变相应归一化先验的物理范围，不误称所有物理正则完全相同。没有对全部轨迹要求误差单调，但支持不足/留出失败不能放行。

CoTracker实际提出128点，47条通过原生复核；32条具备完整7图，9条6图、5条5图、1条4图。d中角度P10/P50/P90=3.124/3.273/3.514度；深度Jacobian比例=.01594/.01713/.01889，47条没有因视差/Jacobian失败。44条训练观察P90超2.5px、5条末图超3px。不能继续泛称缺少视差，或只扩大运动范围。e/g数据Schur条件比例.02136/.01193，可辨识性代理通过也不代表拟合正确。

不能据这些数字断言所有残差都来自真实布料形变：局部测量歧义、预测初值、现有世界投影误差仍需区分。加速度、初值范围和上下身自由度没有解决它们。没有让这些错误通过颜色/alpha训练伪装成衣领、肩部或颈部已经修复。


**新增的定位证据：**47条轨迹全部位于胸前下部（lower_left 29、lower_middle 18），不能代表衣领/肩部观测通过。空间分层没有消除源图可跟踪纹理集中在胸前图案的偏差；不能只加数量就宣布上身覆盖。g候选在0026/0027的衣物中位误差4.508/4.298px、P90 5.808/4.962px，两个下部区域同时偏差大。

同帧独立静态纹理复核保存在.sources/body-static-context-20261002-a。采用64条已有COLMAP物理轨迹提议，再作原生真实patch前后向复核；没有新匹配或修改相机。0026静态原始特征重投影P90=1.323px、9条原生复核P90=1.242px；0027为1.291px、11条原生复核P90=.708px。这排除了“这些帧全部都发生相同5px全局读取错误”作为充分解释，不能据此证明全部相机/衣物深度真值。筛掉的反光、歧义及非收敛patch全部记录，拒绝原因没有改成通过。

由此限定追加了时间节点试验body-i：同47条真实测量、相机/尺度/参考固定、误差和可辨识性门槛不变。中位4.877→.495px，但P90 7.496→8.910px、整条留出轨迹的最后观察P90=11.130px，只有4个点通过。它说明更多运动容量能局部拟合，却损害尾部和外推，不能采用，更不能让衣物颜色训练掩盖结构失败。实际23次信赖域调用、5.651秒，未应用或导出衣物模型。

body-h曾被晚期角色保护阻止进入求解（空目录保留）。核查发现颜色32帧小批次清单并不等于全部原始合法几何训练观察：0022/23/24/26仍是原prepared明确train，且不属于8开发/6固定回归。最终入口以原prepared训练角色排除所有保留集，额外几何观察显式记录为auxiliaryGeometryTrain，冻结原颜色split不变。body-i合同保存这些身份，不假称它们原本就在32帧颜色训练中。本轮任何新测量未使用开发/审计RGB，不把历史研发留出称最终盲测。

[真实衣物测量与共享3D预测误差位置](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/measured-body-handoff-20261002-g/residual-audit/measured-clothing-residuals.jpg)

CoTracker3实际commit `82e02e8029753ad4ef13cf06be7f4fc5facdda4d`；scaled_online.pth SHA256 `205d34789f19699d64b22cf93f9b697f15f28d4025240e31532e504109837218`。代码/权重按缓存manifest核对，CC-BY-NC-4.0，仅非商业离线研究，不成为产品默认。真实推理44.617秒，allocated2347.04MiB。没有新下载或安装进原环境。

## 6. 显示、导出与恢复

共享PLY SHA256 `fd21c779eaa77d709705ff34e5118075523b3b2a5b9314458f66ad4f692355d6`，final checkpoint `0708b2cb622b3a4c2fc2b5aed8c396b371d153312235649ed3251d200dc5cbdd`。

一份固定PLY在gsplat1.5.3完成121帧0→−60→+60→0连续绕看，原生全幅计算，540×960编码，20fps容器不是实际设备fps。q守恒最大7.75e-7。yaw是viewer相对角，不是实拍角。没有按角度换模型。

导出回载对训练终态同相机最大差：RGB .00079739、alpha .00027269、q .00075988。不能写成逐像素完全一致；本轮没有更改PLY字段或查看器去隐藏差异。

[固定同一PLY连续绕看，未通过研究候选](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/shared-scene-geometry-20261002-b/quality-orbit/frozen-ply/frozen-ply-orbit.mp4)

真实桌面Chrome SwiftShader / PlayCanvas2.22.4，1080×1920，同K/C/reference，compact、minPixelSize2、gamma1、exposure1，无fog/LOD/后处理，三个资产均加载，无脚本错误。完整RGB gsplat/PlayCanvas MAE：旧.090770、控制.091511、共享.088508，仍显著不一致。参考图PlayCanvas对原片face .025212→.024998、hair .044775→.044553、room .130032→.127191，都是很小的改变。不是HarmonyOS验收，不推断设备流畅或所有角度正确。

[原片与双渲染器实际对照](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/shared-scene-geometry-20261002-b/display/renderer-comparison/source-gsplat-playcanvas.png)

两个分支initial/restored的model、trainable、Adam、bindings、sampler、RNG、strategy、scheduler、extra、contract完全相同；67个保护源字段在final也完全相同。50095点的namespace/UID、部件与所有非资产hash身份字段精确保持。原完整PLY/检查点hash未变。

33项前一轮回归实际通过，8.445秒；新增时间节点/辅助几何观测隔离后35项扩展回归通过，5.025秒（extended-tests.log）；包括真实CUDA显式协方差前向/梯度、解析J、分批分解数值/梯度、世界单位/未知运动保护、点序与SH运输、原生坐标与短序列接口、深度分组校验，以及低残差但运动不可辨识的反例。final-tests.log是本轮运行。初次失败tests.log保留：直线匀速相机合成例无法独立确定运动深度，新Schur检查正确拒绝；随后增加可观测非线性相机正例及不可观测反例，没有降低判据。

## 7. 复现与异常证据

在W/backend、既有/opt/self-reconstruction/venv、Ubuntu-22.04中执行；以下参数路径为本次冻结输入，算法没有硬编码它们。

```sh
python -B run_shared_scene_geometry.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --priors .sources/surface-handoff-20261002-b/motion-consistent-observations --out .sources/<fresh-run-id> --steps 240
python -B run_static_depth_calibration.py --prepared /mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e --split .sources/fullframe-surface-patch-20260929-b/observations.json --depth .sources/dense-motion-surface-20260930-h/depth --out .sources/<fresh-calibration-id>
python -B run_locked_body_tracks.py --prepared /mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e --window-result .sources/measured-body-handoff-20261002-b/result.json --tool .sources/tools/cotracker3-82e02e8 --out .sources/<fresh-track-id>
python -B run_measured_body_handoff.py --prepared /mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --tracks .sources/locked-body-tracks-20261002-c/tracks.json --depth .sources/dense-motion-surface-20260930-h/depth --out .sources/<fresh-body-id> --motion-basis two-node --rotation-bound 8
python -B -m unittest test_shared_scene_geometry test_measured_scene_geometry test_surface_handoff test_reconstruction_surface_continuity -v
```

历史精确复现应使用各run的实际algorithm-source/源码快照，而非当前文件倒推当次运行。最终body入口额外补了当前split角色/源cache合同以及辅助几何训练观察身份，不能将这项晚期保护写成旧b/c已执行。普通body研究是重新求解；scipy没有序列化信赖域内部状态，不声称精确resume。GPU源模型完整恢复，新Adam从零开始，是warm-start；各本轮init/mid/final/restored可恢复Adam/RNG/采样状态。

保留的异常：body-a用了旧B窗口而缺少可用真实轨迹；calibration-a误传stage spec导致KeyError train，未计算；tracker-a许可文件名错误；tracker-b对T=7误走offline调用，锁定在线源码num_windows为零，坐标全0、概率全.25，不属于视频跟踪失败。tracker-c按实际online短chunk接口、两个方向分别reset、36辅助网格修正，原生47轨迹真实产生。内部重复末帧padding不算额外拍摄影像。既有结果不覆盖、不清理。

## 8. 当前状态与下一项具体工作

可保留的子能力：真实共享几何优化、完整内容/身份保护、数值等价的显存执行修正、原生多帧测量、受限运动与数据可辨识性检查、源时刻/深度合同和完整事务恢复。

失败：显著去白雾、衣物高精度共享运动、颈部自然连接、真实发型/镜架、完整模型画质及双渲染器一致性。没有新衣物/头发GPU训练或替换，不能称这些已修复。新初始化微小改善、优于某个数字基线、整体可发布是三个不同结论。

未验证：HarmonyOS最新候选、真机fps、新用户/无眼镜/不同发型或不同视频泛化、完整服务耗时。原P、签名、USB、AI、上脸、故事和生产查看器未修改。

下一项最有价值的实际工作不是继续加节点、增加步数或放松误差。同帧静态投影已作限定复核，更多时间自由度也已失败，不能重复同一组运动拟合。最有价值的下一项是将原生测量扩展到真实衣领/肩线及胸前边界，用法向轮廓残差正确表达低纹理边缘的切向不确定性；结合得到静态校验的深度初值，检验近刚性局部连续衣物表面。不能将沿边滑动的一维轮廓误当成高精度二维特征，也不能放松现有留出与世界可辨识性检查。低纹理room采用通过静态校验的共享表面初始化；不把不通过的窗口预测全局融合。可靠局部研究可以独立继续，最终完整场景仍必须共同遮挡、连续颈肩衣物和可辨环境。已有原片继续使用，无需将本次失败泛化成用户必须重拍。
## 9. 本轮提交边界

共享几何、资源执行和状态验证单独提交：`ca00a5a577b14ee7477b6f50315d9d4e03db28fd`。衣物观测/受限运动、静态条件校验、源码manifest和本报告使用另一项显式文件提交。原有暂存区为空后才纳入本任务清单，未提交其他既有修改，未推送。

source-manifest.json记录本轮最终12个源码文件的SHA256；它不替代每个.sources run中真正执行的源码快照。tests.log、final-tests.log和extended-tests.log分别保留早期失败、33项通过和35项通过，不把不同阶段日志混称同一次运行。