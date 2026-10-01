# SELF：跨窗口真实表面、受保护训练与头颈连接复核

2026-10-01。已完成隔离后端修改、真实多视图深度计算、5个GPU外观分支、实际桌面双渲染器对照与完整恢复。**存在局部进展，但没有达到自然完整的人体、高细节人脸和无缺口环境的发布标准。没有部署、回传或替换作品。**原E1—E5不变。

## 首先回答用户看到的问题

- **头发有真实局部纹理改善，仍有旧壳亮边和体积错位。** 新颜色全部来自原片；没有刷黑、生成发丝或加假高光。新几何只获局部多视图支持，不能把更多点称为真实完整发型。
- **脸—颈接缝仍未解决。** 几个原片可见皮肤相邻区域中，总alpha接近1，却有约25%—36%的room颜色贡献；人物贡献不足和背景混入同时存在。总alpha高不证明连接正确。图像对照中仍有白边、颈部软化和头颈运动不一致，不能以RGB下降宣布修好。
- **面部确实再次训练，但精度提升很小。** 独立face分支优化8286点的SH、alpha、协方差；位置/身份/表达保持。两个新共享几何候选在条件深度留出上变差，未进入外观恢复。没有将“没有合格新几何”说成“脸没有训练”。
- **环境和衣物的受保护训练有小幅进展，几何完整性未改善。** 原有几何和点数保持，不能把它包装成填补房间空洞或修好衣领形状。
- **8GB不是这轮已证实的主瓶颈。** 本轮没有OOM，实际Torch峰值远低于8GB。主要未解问题是跨观察几何、头/身相对运动、旧宽room核与真实外表面的替换关系，以及两个渲染器的差异。

## 冻结身份与保护

W：`C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay`；起始HEAD `6b4e06ac9b28add445a4bc5c2e2a03e05add03e4`，分支`codex/reconstruction-v3-audit-20260928`。

P：`D:/STUDY/College/mine/olay`；HEAD `3dad0cd5651824cc06d9e88d61aabdd2642c0b30`。没有写入P，没有更改应用、签名、传输、生产查看器、AI/OLAY/上脸/故事/UI。原有dirty文件保留；没有reset/clean/stash/rebase/amend/强推、清理run/worktree或驱动修改。起始索引为空，只提交本轮明确文件。既有`build_continuity_candidates.py`等未提交修改未混入。

输入原片`capture-1790410633104.mp4` SHA256：`7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。原片包含两侧观察；没有把可信世界相机缺口写成用户没拍到另一侧。prepared SHA：`e67d4dce02f9874e0befe15486532f80458f8a62a23221324fcc5abefc2e5301`。

完整起点是`backend/.sources/continuity-physical-surfaces-20261001-b/body-transition-sh`，不是已经质量通过的作品。PLY SHA `a343ccf05292ce1e174c7fd63795122347a8d03bd0202a19395a9a414b691f41`；完整checkpoint SHA `c3425ba01892940353909dbf3f95d5058ef507e023357ef864d4cb1460cac344`。严格恢复所有模型字段、绑定、运动、协方差与SH，缺失字段不清零。

起点50095点：room26054、face8286、hair2917、稳定glasses分类5、body12833。5个分类点不代表整副眼镜只应有5点。旧Open900步保留；本轮从完整场景恢复起点开展32训练观察、8开发/6固定回归的研究，不能与旧14/8、小viewport或其他候选指标直接拼表。原开发/回归长期参与研发，不是最终盲测。

## 实际实现与几何计算

新增接口读取当前job的时间、角色、K/F/C、真实源图、语义与来源，不硬编码这个人的脸、衣服logo或特定失败帧。诊断图的显式帧名不进入训练选择。跨用户、其他视频仍未验证。

### 跨窗口MVS与头发表面

沿用已安装独立OpenMVS2.4.0工具。准备窗口0/1，复用已核验窗口2；原生RGB裁片没有涂黑、重采样或生成纹理。实际导入半像素/K检查保留。MVS内部resolution-level=1不是原生深度精度。

0/1在原默认配置下真实执行但没有产生深度。核对锁定源码发现稀疏邻域评分的绝对门槛拒绝了邻图：评分还包含稀疏轨迹覆盖面积，少量真实脸/发锚点不等于整个图像没有有效邻图。研究副本仅将`View Min Score`改为0；几何迭代、3视图融合、相机、mask与深度规则不改。**没有把这项研究配置切成生产默认。**隐藏配置接口由[OpenMVS2.4.0实际源码](https://github.com/cdcseacave/openMVS/blob/v2.4.0/apps/DensifyPointCloud/DensifyPointCloud.cpp)核验，不编造CLI。AGPL分发义务仍适用，独立进程不豁免许可。

| 窗口 | 真实训练观察 | 原片重新三角化锚点 | 融合点 | 有3视图真实hair颜色的点 |
|---|---|---:|---:|---:|
| 0 | 0002—0009，8张 | 54 | 26080 | 2304 |
| 1 | 0022—0028，7张 | 35 | 22812 | 6567 |
| 2，复用 | 0037—0043，7张 | 103 | 18115 | 4759 |

窗口0/1真实融合耗时10.68/11.61秒，CPU、4线程；准备时间另计29.04/37.35秒。点云hash与工具hash保存在原run合同。本轮没有再次跑窗口2的MVS。

13630个hair支持样本中，240条跨窗邻近/法线一致记录、57条近距离法线冲突、13333条unknown。它们是样本记录，不是独立物理表面数；远处没有邻点保持unknown，不当成空区。保留原始XYZ与来源，不平均冲突表面。去重后13109，有限提议6000个，依据真实法线和采样后间距建立切向/法向尺度。

旧壳退役改用原生全幅、完整head共同排序的每点实际alpha*T职责：至少3训练观察承担有效像素，且在每个显著观察中替代覆盖比例≥92%。59个旧hair点符合研究提议，2858个unknown旧点保留。**这能避免无依据删发量，却也留下旧壳与新外表面的混合，不能称已建立单一正确发型。**

### 有界几何与上身运动

从真实融合面部支持建立共享规范表面变量，固定K/F、身份、表达与拓扑；源UID预先决定条件深度留出。没有按开发RGB选点。真正独立三维真值仍缺失：MVS依赖相同恢复F，因此它是条件深度证据。

| 方案 | 支持/条件留出 | 控制数 | 初始→终态拟合中位px | 条件留出P90 px | 结论 |
|---|---:|---:|---:|---:|---|
| 共享XYZ场 | 39 / 8 | 39 | 1.3413→0.2318 | 3.2216→3.4200 | 拒绝；不训练外观 |
| 共享normal场 | 39 / 8 | 16 | 1.3413→1.1761 | 3.2216→3.9522 | 拒绝；不训练外观 |

限制是每坐标3原生像素对应长度，XYZ向量极值可更大，不把它写成严格3px欧氏球。最初“一粗高斯只能对应一个测量样本”的审计实现产生过不足留出，已纠正为每个实际测量位置在兼容旧切面上初始化；原失败目录仍保留。未靠调门槛放行。

上身从分布式原纹理轨迹尝试固定参考/尺度的12共享时间系数，不是每帧自由6DoF。三短窗分别51/37/34轨迹，仅0/4/5个通过；第三观察P90为14.03/7.14/5.45px，均拒绝。第二、第三窗甚至劣于起点；没有将这些B投入衣物/MVS或整段颈运动。此前只在五帧短窗拟合的B不能推广整分钟。这是连接仍阻塞的具体运动证据，不是显存猜测。

## 五个真实GPU训练分支

保持gsplat1.5.3、FLAME Open、head-local-SH1、标准PLY、正确全幅投影后切ROI。颜色来自原片；所有头部部件共同局部渲染，完整场景评价始终共同遮挡。没有新的T3/T4，没有隐藏背景给人像“让路”。

| 分支 | 实际Adam步数 | 训练+评价秒 | Torch allocated/reserved MiB | 保护结果 |
|---|---:|---:|---:|---|
| 旧59点hair控制 | 240 | 140.43 | 869/1116 | 数值筛查无新增退化；旧壳质量仍失败 |
| 6000实测hair提议 | 240 | 156.73 | 875/964 | 3处训练room RGB退化，拒绝 |
| 同提议+可靠空区保护 | 240 | 132.79 | 888/948 | 仍2处训练room退化，拒绝 |
| 冻结几何的room/body外观 | 240 | 86.11 | 1274/1394 | 数值筛查无退化；非几何修复 |
| 独立face原生外观/协方差 | 240 | 66.20 | 876/976 | 数值筛查无退化；精度改善很小 |

合计1200次实际Adam迭代不是一个服务任务的1200步。表中时间包含训练与终态评价，不含全部准备与MVS；context原字段名`trainSeconds`实际也包含终态评价，不能冒充纯训练耗时。hair最初整轮699.86秒包含两支、加载及初终多图I/O；保护分支总263.90秒。没有完整2—3分钟成绩。

可靠空区保护是后来根据3处room退化明确增加的唯一单因素实验，不冒充原始预登记预算内容。精确复用同6000点/59退役、初始参数、相机、32训练观察、原optimizer学习率、采样状态与240步；只有原confident room的腐蚀内部像素惩罚新增hair贡献。unknown/被遮挡不当成空区；没有把头发改成背景、全局压alpha或再造MVS。真实采样记录一致。失败从0005/0006/0008减为0006/0008，仍不可采用。

在有可靠世界C的5个开发观察（0015/0035/0115/0130/0145）上，完整合成hair平均L1从0.138903到0.116790，约15.9%下降；不是全部8开发/6回归的统一指标。例0035为0.044941→0.038737；原片/旧/候选图能看到更多短发颗粒，同时也清楚显示旧亮边、发际线与颈部断裂。平均数不放行这个资产。

![真实头发对照，左原片、中旧、右受保护候选](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/cross-window-surface-repair-20261001-a/hair-observed-empty/final-local/frame_0035.png.png)

context分支只更新room/body的真实SH和小幅alpha，几何/拓扑/头部精确冻结。相同5开发观察的neck L1 0.098850→0.087237，cloth 0.129719→0.126989、room 0.041586→0.040029。它属于颜色/透明合成恢复，不是颈肩几何、运动或房间孔洞修复。独立face平均0.058422→0.058275，改善不足以称面部高精度。

## 头颈接缝的实际定位

只在原片face/neck已有皮肤邻接的10原生px带内检查，衣物与unknown排除；观察域不是三维真值。找到4个有效带，不把其他帧没有该语义带说成没有颈部。

| 原片皮肤邻接带 | 旧人物贡献 | 旧room贡献 | context后room贡献 | 总alpha<0.8 |
|---|---:|---:|---:|---:|
| 0010，109px | .8012 | .1986 | .1918 | 0 |
| 0005，379px | .7363 | .2635 | .2559 | 0 |
| 0006，402px | .7480 | .2518 | .2441 | 0 |
| 0115，572px | .6380 | .3618 | .3561 | 0 |

这说明这里不能按“总alpha充足”结束排查。尚不能仅凭q判断room是错误前遮还是从不足人物覆盖后透出，也不能把FLAME或GS期望深度当首表面真值。结合当前不同表面来源、有限身B与白边对照，**头/颈/身的共同几何和运动仍未成立**。本轮没有填白边、焊皮肤到衣领、alpha羽化补缝或删真实背景。

![颈部对照，原片／旧／context／人物贡献／room贡献](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/cross-window-surface-repair-20261001-a/evidence-final/connection-frame_0115.png)

## 实际双端显示与来源合同

实际PlayCanvas2.22.4桌面Chrome SwiftShader，1080×1920，COMPACT/minPixelSize2，原gamma/exposure、无LOD/fog/后处理、预乘RGBA8。没有通过加光、gamma或取消核半径限制制造改善。**未测本轮HarmonyOS、真机fps或新的AI编辑交易。**

参考0010同PLY、相机、K、原生尺寸：

| 资产 | gsplat—PC全幅MAE | face差异 | hair差异 | room差异 |
|---|---:|---:|---:|---:|
| 完整旧起点 | .090770 | .089696 | .203489 | .121577 |
| context | .089514 | .081084 | .199464 | .122374 |
| 固定点序face | .090759 | .089754 | .203388 | .121577 |
| 受保护hair | .089877 | .089163 | .184406 | .120833 |

差异仍显著，不能说显示端一致。受保护hair的PC hair对原片L1由.044775降到.041464；PC room却从.130032到.131993。独立face的PC face仅.025212→.025098。不能拿head-only图替代最终查看器验收。

查实固定拓扑face的研究导出曾将更新行移到末尾并更换来源namespace。新增可微原位更新与独立逐字节重排适配：保持原50095行、point ID、来源UID/namespace和语义。旧导出不覆盖；只生成独立排列副本。所有浮点属性（含log尺度/logit alpha/SH）逐字节相同；同原生全幅gsplat实际RGB/alpha/q差值均0。未来face入口采用原位更新；已完成240步仍记录其真实旧执行快照，不能假称重新训练。

固定点序资产SHA `8615059bbf320ac3f26a1dd3ef7ccbb71e5cf78532ae585b7175edf81d30d9bc`；同一PLY完成121帧绕看，未按角度换模型，q守恒误差7.75e-7。绕看轴来自记录的头部先验，不把viewer yaw当真实实拍角。录像来自gsplat，不是PC或设备fps。

[固定同资产连续绕看](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/cross-window-surface-repair-20261001-a/face-fixed-orbit/frozen-ply-orbit.mp4)

## 资源、回归、保存与结论

RTX5070Laptop8151MiB、driver617.14，torch2.8.0+cu128，gsplat1.5.3。未安装或改变驱动、显卡模式、CUDA或原锁定环境。180次Windows实际采样（15:49:02—15:55:15）最大2943MiB，涵盖context及空闲片段，**不是所有分支连续系统峰值**。Torch统计不包含所有其他进程显存；没有OOM，但不能保证任意后续大模型都不超8GB。

55项必要合同回归通过：原生投影/半像素、跨窗unknown与法线冲突、实际职责退役、参考恒等/连续运动/SH梯度、逐点SH方向运输、固定资产点序与真实梯度、可靠空区与unknown分离。测试通过不等于画质通过。五个GPU分支的model、Adam、binding、sampler、RNG、strategy和trainable完整恢复精确一致；旧900无Adam仍只可warm-start。

所有输入、实际源码/hash、配置、initial/mid/candidate-final/restored、UID/来源、PLY、float RGB/q/alpha、MVS深度和失败证据保存在新`.sources/cross-window-surface-repair-20261001-a`。原失败run和旧资产保留。Git只保存代码/数值报告，不备份私人照片、PLY或checkpoint；这些文件仍仅在本机研究盘，没有独立外置备份、上传或清理。

**可保留的是可复用实现与证据：**真实跨窗收集/冲突/unknown、实际贡献范围退役、精确冻结恢复、受保护原生训练、来源点序保留及实际显示对照。**资产均未通过整体发布。**面部几何、发际线/鬓角体积、镜架、颈肩共同运动、衣领独立物理层与完整背景遮挡仍有缺口。

下一项最高价值动作应是**共享规范空间内的头—颈—上身物理表面和运动约束**：使用真实颈/肩/头部对应与轮廓，同一物理track共同约束源、目标、第三观察；固定可靠世界C、参考F、K和尺度，限制B与共享表面，先证明接触关系和跨窗一致性，再恢复外观/替换旧壳。现在cloth角点的失败B不能代替颈部测量；增加同样时间系数、颜色或点数不能解决。已有可靠局部face继续研究，不等待所有环境通过，但不跳过完整场景发布门禁。

## 文件与代码保存

代码提交：

- `a0d8cebd876798b6935d17fc80f2d98a49f89946`：MVS窗口接口、跨窗口表面和实际职责覆盖。
- `1e80b13b18a65be6d156c4dd29e24073c82c148f`：有限共享几何/上身研究、受保护原生训练、点序与回归。

主要文件：`prepare_measured_hair_mvs.py`、`Invoke-FiniteMeasuredMVS.ps1`、`reconstruction_surface_consensus.py`、`build_cross_window_surface.py`、`run_cross_window_surface_repair.py`；`reconstruction_motion_geometry.py`、`run_quadratic_body_motion.py`、`reconstruction_dense_face_field.py`、`run_dense_face_surface_repair.py`；`run_context_appearance_repair.py`、`run_protected_face_appearance.py`、`reconstruction_asset_order.py`、`reconstruction_observation_protection.py`、`run_observation_protected_hair.py`。全部在隔离W，没有接入生产服务默认。

审计适配：`audit_cross_window_evidence.py`、`audit_fixed_order_export.py`、`audit_order_render.py`。本目录`results.json`、`renderer-results.json`、`state-audit.json`、`hair-protection-state-audit.json`、`tests.log`为本轮真实证据；复现命令在`commands.md`。私人图像/模型不进入本地提交。