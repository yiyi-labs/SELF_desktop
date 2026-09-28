# SELF 建模主链路总审查（实施前冻结）

审查日期 2026-09-28；只审查重建、导出与点序。本文在 v3 算法修改前形成。后续运行结果另见同日 implementation / results，不把旧结果记作本轮通过。

## 现场与证据边界

原工作区 D:/STUDY/College/mine/olay，master HEAD f68587bb34f8970d21bda9231e15b2536a33df97。1639 个已跟踪或未忽略文件逐字节复制到隔离 worktree，保存原 diff、staged diff、status、145 个未跟踪文件名及 SHA 清单。隔离分支 codex/reconstruction-v3-audit-20260928；完整现场提交 c46286a05bcff1b64b3e24e3dbfe66739fb70973。原工作区不 reset、不清理、不提交。回退是查看这个隔离提交，绝不重置用户工作区。忽略的私有原片、模型和旧 run 不在 Git 中，仍保留原位置；242 个关键研究输出另有只读哈希清单 reconstruction_audit_private_manifest_20260928.json。Git 快照不能冒称备份了所有私有二进制。

源片 capture-1790410633104.mp4 对应保留研究 capture.mp4，SHA 7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf。已确认两侧面部观察存在，缺的是关键中段可靠世界相机，不能归咎用户没拍到。当前 8 个开发视角已反复参与方案选择，不能再称独立盲测。

实际 RTX 5070 Laptop，8151MiB，驱动617.14；本轮 WSL CUDA 矩阵乘法成功。torch2.8.0+cu128、gsplat1.5.3、pycolmap4.2.0、PlayCanvas2.22.4。此前设备消失不能由低显存使用量推断为训练 OOM；本轮不重装驱动。

## 三条链不能混淆

| 链 | 实际入口和用途 | 不能由它推出的结论 |
|---|---|---|
| 当前在线测试链 | engine-profile.json 为 portrait-first-soft-surface-test。worker → reconstruction_runtime → 同源缓存或 live_prepare → portrait_pipeline(local900/T3 300/T4 300) | 不是旧默认 train_joint；research 允许回传的旧决定不等于本轮允许 v3 发布 |
| 旧默认分支 | worker 原 SfM/face/pose/observation → train_joint；默认分组把另一组 opacity 置零 | 一份混合 PLY 不代表训练时共同遮挡 |
| 隔离研究 | shared/clean/detail、components_v2、SH1局部、soft surface、父点替换 | 不同 split、点集、相机、阶段不能混成公平 A/B |

## 已看代码与关键证据

- worker.extract_frames(91–206)：源索引/PTS记录；run_one(364–477)：真实分流。face.make_component_observations、static mask、prepare：皮肤/发/衣物观测不是独立三维部件真值。
- pose.refit_local_pose_same_camera、prepare_face_views；observations.build：按名称匹配 F/K/C，局部观察和世界观察分开。当前 E1 证据不能因注册数多而放行。
- scene.supported_static_surfaces(190–312)：静态多视图稀疏轨迹、有限三角插值。比旧室内体积散点合理，但不是完整稠密房间。中间洞不是简单删背景就能修复。
- train_joint.render(165–224)：旧隔离组训练；shared 模式改为共同合成，但衣物仍夹在静态 environment。clean 的脸区环境贡献惩罚没有独立深度/静态支持判别，不能替代几何。
- components_v2.local_fit/shared_scale/triangulated_component：独立局部 F 和一个全局尺度；后者假设近似静止头中心，P90约23mm残差，非独立标定。三视图发/镜框匹配数量少，不能填上外观未覆盖区域。
- shared_v2.initialize(61–158)：skin投票筛选会排除曾投到发区的面点；新增发/镜框是真实三视图种子，但数量与范围不足。posed(161–202)：cloth仅经验性平移混合，不是独立躯干运动。
- portrait_pipeline.initialize_scene(148–180)：完整保留11715头点（8798表面+2917粗发壳），避免 v2 重新裁掉头部，却也保留旧壳错误。configure_stage(222–233)、train_stage(236–305)：hair_delta永远不开，学习率0；只改颜色/尺度/透明度不会把壳变成正确短发体积。
- portrait_model.replace_skin_parents(285–366)：参数、Adam矩、绑定、语义、来源等同步；子点矩归零。既有事务可回滚。该函数未参与原900步，所以不能将所有旧模糊归因split。5033父点替换的容量实验局部变差并回滚，说明同步通过≠画质通过。
- research_face_surface_refinement：有界几何与局部替换已跑，增密不是未做；不能继续相同实验冒充新路线。
- export_flame_appearance_research与portrait_model：head-local-sh1旋转、协方差/尺度同变换和精确SH已修正。T0/T1画面平均差约2e-7，不能重新声称所有问题来自H或方向色。
- viewer-gs/main.js：editableSplats仍是前缀。实际 PlayCanvas parsers/ply.js:460 默认 reorder=true，gsplatData.reorderData 改存储点序；与每帧绘制深度排序是两回事。E研究资产30386点中，6033可编辑点全部被排到前缀外；reorder:false诊断恢复。坐标重复10点，不能用近邻XYZ反推可靠映射。

## 为什么越修越差：因果树

**主因一：表示与观测不匹配。** 固定/稀少的发、镜框几何却用宽高斯和颜色拟合细节。v2原生投影半径：皮肤中位约24px，头发约48px，衣物P90约118px；覆盖可以提高，纹理仍被宽核平均。镜框没有独立完整空间结构；普通皮肤自由度被迫解释配饰边缘。局部头部在进入场景前已经明显比原片软，不能全怪背景。

**主因二：部件边界与运动解释不正确。** 旧衣物并入环境，v2只是语义分开而运动近似，当前soft链自由cloth又是准静态世界点。颈部FLAME皮肤不是衣领真值。头部F、房间C与躯干并无同等可靠的运动约束，接缝和颜色竞争不是羽化能修。

**主因三：阶段过早放开，质量没有逐部件阻断。** 当前T4允许脸和环境再动；frame35脸L1 .022163→.025919，即使平均下降也伤了局部。旧clean将q_environment压低后六视角五张脸误差上升。一次颜色损失下降并不能批准共同阶段。

**次因：世界约束不够可靠。** live_prepare选择注册数最多地图和至少6相机；这是可计算门槛不是E1严格相机通过。原片两侧存在，局部F可用不等于C可靠。角色、时间、K/裁剪已比早期清楚，但不能把估计尺度称为真实测量。

**诱因：表示预算和筛选策略。** v2保守裁掉旧壳/部分面点，再以少量三角种子代替，会丢覆盖；新视频自动准备实际发点17、镜框0。缩小所有scale/用大薄片补洞都会转移问题。密度事务与来源同步正确只是必要条件。

**二次集成问题：点序。** 会错选编辑范围，但没有证据证明它是未编辑时所有脸模糊的主要成因。共同中心深度排序/投影近似仍可能贡献亮边，两个渲染器都出问题不排除共同近似。

**表现：** 局部软、发壳、漂浮镜边；环境删薄后消失，衣领白团，前景/背景竞争后脸空洞或混色。不是一个正则权重或8GB显存解释全部。

## 七个问题的直接结论

1. 单独脸相对清晰，是没有错误房间和衣物的前方贡献，且原生ROI权重较高；加入场景可能再降低脸质量。但原片/InitialT0/Strong900/Soft900/JointT0/JointScene固定35视角已显示，单独脸也不合格，不能吹成曾经恢复了真实细节。
2. 背景消失来自缺覆盖的有限表面/少数种子代替整个房间，以及贡献惩罚压掉可见性；人物颜色和运动仍错，所以没有换来清晰脸。需要增加有证据的表面覆盖，不能“重新塞满体积散点”。
3. 主因是结构、部件运动、优化交接，次因是姿态不可靠/宽footprint。强软对照900几乎相同且数据梯度大于先验，没有证据将主因定为FLAME约束过强。容量候选退化和点序错另有证据，不能统称根因。
4. 粗发壳只在2D支持范围找点，缺完整外表面深度；当前位置被冻结；新独立种子又太少。没有合格Hair交接合同，导致用颜色/alpha拟合几何错误。皮肤不应主导发型。
5. 颈肩衣物在旧链被视为静态，在新链缺真实躯干变换，局部ROI只含头又弱化肩膀监督，三者叠加。应该独立人体部件并保留joint共同遮挡。
6. FLAME继续承担粗脸、表达/头姿、拓扑绑定、共享表面参考；不承担头发、镜框、衣领/衣物和房间最终形状。普通FLAME A/B已经做过，本轮不再切版本。
7. 可诊断性更接近成熟：输入身份、精确SH、共同贡献、事务回滚真实存在；完整画质还没接近通过。clean、覆盖不足的替代种子、无分部件门禁T4属于不应推广的方向。说“数字一直变好所以成熟”不成立。

## 旧实验同口径索引（不是本轮通过）

| 证据 | 结果与限制 |
|---|---|
| integrated-detail-occlusion-20260927.md | Base→Shared三脸L1 .09514/.18581/.18987 → .02718/.02390/.03361；Clean/Detail无相应局部视觉通过 |
| integrated-components-v2-20260928.md/json | 支持表面/语义进步；宽footprint、稀少附件、衣领失败；实际点序不兼容 |
| portrait-first-soft-surface-20260928.md | 11715点保持、T0/T1精确；T4局部退化；强软无决定性差距；容量回滚 |
| private controlled-comparison(frame35/75/145) | 本轮已看35：镜边模糊，发帽感，场景脸前白区，不是仅凭数值评价 |

新质量研究仍用E1—E5：A为E1输入；B为E2/4人物；C/D为E3背景/共同遮挡；E为E5。新阶段名不另起发布规则。
