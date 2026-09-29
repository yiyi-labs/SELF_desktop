# SELF 人像细节与完整背景：有限实修总记录（2026-09-29）

## 先回答结果

**已经实际修改并训练，没有取得可稳定放行的人像或完整场景改善。** 人像开发集和少数新检查视角有局部进展，原审计组依然退化；背景边缘略好，但细纹/结构仍软，且冻结叠加就会挡脸。本轮没有执行新的T3/T4，没有部署、回传、覆盖作品或切换生产默认。

目前证据支持的主链条是：**继承的粗足迹和不充分的部件几何 → 多视图拟合偏低频、侧脸错位 → 背景在冻结叠加T2时已经错误遮挡 → 上一轮短时T4外观更新可能用颜色补偿这种错误。** 最后一项属于与证据相符的解释，尚无梯度隔离实验可证明其全部责任。不能说“加背景必然失败”，也不能笼统归罪FLAME或8GB。

原提示中“背景面积必然淹没人脸”“joint必然把背景拉平”“点序/SH交接丢失”均未被直接证实。损失已经分区域归一化；本轮同尺寸重放甚至显示旧背景在T4后的结构误差有所下降。应保留这些反证。

## 现场、运行入口和恢复边界

W：`C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay`，分支 `codex/reconstruction-v3-audit-20260928`。
P：`D:/STUDY/College/mine/olay`，HEAD `f68587bb34f8970d21bda9231e15b2536a33df97`。本轮前后完整dirty清单相同，没有写P。

历史是线性祖先：

```
27c9810bf0746d8e4382eb218e89276954767d7d
 → 933f664cd700b7845eca14fe1a5671228366d1f1
 → 9a6bef3ef13e47e011421a12a21e255648c76ff2
 → 13b1b0f58c87aa08c23b56999b4aa962fd542862
 → cef6c043ed7a4ad397de41c995b7787ec3db0ce5  已完成d2，不重做
 → fe8393f3dfc1afacfc02e1663b386d6425a9bd39  上轮真实训练
```

本轮先提交 `e6cc497`（只读审查、冻结身份），再提交 `79812d3`（独立细节训练模块、入口、合同测试）。末尾单独提交审计与总报告，完整提交关系见 `result-summary.json` 和Git历史。原有未追踪审计文件保持未追踪，未顺带提交。

| 能力 | fe8393f真实运行情况 | 本轮情况 |
|---|---|---|
| shared surface residual / embedding / offset | 已运行 | 继续实际交替更新，参数变化保存 |
| 有界头姿 | 已运行 | 同样受限；不是新世界相机 |
| replace-parent | 两次，254父点 | 两次，255父点，真实删除父点/生成510子点；1个提议因支持不足拒绝 |
| room density/Adam | 真实运行 | 原生全幅、absgrad和屏幕足迹参与局部分裂；真实回调/重置/恢复 |
| joint manifest/优化 | T3+T4真实运行；T4仅外观 | 因人像质量失败不再执行T3/T4 |
| PLY点序/SH/绑定/来源 | 已导出并回载 | 原合同保留，新增研究fine_component，逐点身份不改成近邻匹配 |
| 独立头发/镜框结构、颈肩衣领运动 | 未通过 | 仍未通过，不能拿分类表冒充独立几何完成 |

新增入口 `backend/run_detail_controlled.py`，调用 `reconstruction_detail_controlled.py`；仅研究脚本，没有接入worker/生产。旧 `run_reconstruction_v3.py`、应用、查看器和编辑代码未修改。评估入口为 `audit_detail_controlled.py`、`audit_detail_projection.py`。原模型/编辑合同测试继续复用。

42份旧checkpoint、输入快照、源码快照及PLY/sidecar逐一hash核对不变。新训练保留6份初/中/终checkpoint，含Adam、策略、RNG、采样状态、绑定和谱系。旧900没有历史Adam，仍然只能warm-start。本轮也是有意从完整旧初始模型开新Adam的受控实验，不冒称精确resume。Git不备份`.sources`；没有新增异盘私人资产备份。衍生投影审计a/b的源码完整版本未分别归档，仅有变更前hash/日志；最终c源码已保存。不能声称所有失败审计都已独立完整打包。

## 实际改动与有限训练

### A：portrait_refine_v1

从上一轮完整 `face-initial.pt` 加载，保留F/K、表达、共享形状对应网格、SH、offset、协方差、源点和绑定。32训练视角不变，包括只有可信局部F的本人观察。

- 原生RGB之外，加入有效窗口结构误差和真实有符号像素差分；不锐化输出、不生成细节、不在mask外涂黑。
- 每次Adam更新累积两个真实视角，减少单一视角立即拉动参数。900步+48恢复步，共1896次图像反传；比旧单视角方案看图次数更多，不能称严格单因素A/B。
- 180步后有界姿态与共享表面/绑定交替；形状/表达先验仍固定，FLAME未成为新的生成皮肤来源。
- 分别管理skin_face、hair、glasses、neck_shoulders、clothing_upper。初始8031/2917/5/762/348；结束皮肤8286，其余不变。分类仅使用训练观察投影票，不是独立首表面可见性证明。
- 镜框增加独立头局部三维有界位移；但仅5个既有点获得稳定镜框分类，不能覆盖镜腿/鼻托，也暴露出已有表面与细线语义对不上的问题。其余镜框颜色仍可能混在旧面部点里。没有声称镜框已重建完整。
- 颈部子集仍沿用旧头部绑定；348身体种子没有在本轮局部训练中优化。肩部与衣领未解决，不能说五部件都已独立正确建模。
- 350/550步分别接受128/127父点替换，11715→11970点。Adam、绑定、confidence、root/source、stable UID同步，恢复检查通过仅表示没有超过局部容许的覆盖损失。

共享表面平均变化0.00010536模型单位；头发位移变化0.00051933；有界姿态raw参数变化0.10279（不是角度）；镜框自由度也有实际更新。具体每步/每视角和参数形状记录在训练result.json，不把参数动了当作准确。

### B：room_fullimg_v1

使用同一22020房间初值，完整有效静态像素继续参与，未删背景、未用SIFT支持mask代替room观察。为保证原始投影足迹，最终实施采用**原生全幅**，不是预审计划中的随机块。

采用已锁定gsplat1.5.3的绝对梯度统计（阈值0.0008）和局部屏幕足迹判断；最大增长1024/事件、上限40000；没有全局缩点或统一提高opacity。900步中：1156复制、2902分裂父点、24近透明且反复观测点裁剪，终态26054；300步重置，600步最后拓扑，余300步恢复。check_sanity、initialize、pre/post backward和真实参数/Adam重映射均执行。

RGB+有效窗口SSIM+覆盖原有监督保留，增加真实像素差分。means学习率沿用原900步指数下降到0.1倍。本轮没有独立扫描恢复长度或学习率，故不能认定二者是剩余模糊的唯一原因。

C密集辅助未执行：安装的pycolmap4.2.0虽有PatchMatch符号，但 `has_cuda=False`，其接口明确要求CUDA；核对现有运行目录未找到独立COLMAP可执行程序。不伪造CLI、深度或墙面，不把它说成RTX又失效。

## 画质：局部进展，整体失败

固定ROI包含缺失像素；以下是同一尺寸、相机/掩膜的RGB L1。

| 集合 | 旧可恢复初值 | 上轮局部终态 | 本轮局部终态 |
|---|---:|---:|---:|
| 开发8帧面部 | 0.033757 | 0.031474 | 0.031100 |
| 原审计6帧面部 | 0.040160 | 0.041142 | **0.041770** |
| 原审计6帧镜框 | 0.157444 | 0.162336 | 0.159235 |
| 原审计6帧头发 | 0.044040 | 0.043231 | 0.043766 |

开发鼻/唇有小改善，本轮开发唇缘0.025271，旧局部0.025937；但原审计唇缘由旧局部0.036439变0.037844，眼区基本没有改善。可见侧脸仍有彩色杂纹、镜框错位、发壳与白边，下颈仍异常。不能称“人像更清晰、更立体”已经全面达到。

新增检查0060/0083/0108未参与本轮颜色更新；**0060参与过继承的旧900颜色训练**。这是warm-start新增检查集，不是独立盲测。单列未在旧900/上轮选中颜色帧中的0083/0108，face L1为0.032045→0.027806→0.026748；仍不足以抵消原审计组失败，历史几何拟合也用过这些观察。没有更换发布验收集来挑好看的数字。

四列顺序均为**原片／旧初值／上轮局部／本轮局部**：

- [0035完整局部对照](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/portrait-detail-evaluation-20260929-a/portrait-comparisons/frame_0035.png-four-panel.png)
- [0098侧脸失败对照](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/portrait-detail-evaluation-20260929-a/portrait-comparisons/frame_0098.png-four-panel.png)
- [0035唇缘原生局部](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/portrait-detail-evaluation-20260929-a/portrait-comparisons/frame_0035.png-lips.png)
- [同次可见性合成的部件贡献](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/portrait-detail-evaluation-20260929-a/components/frame_0015.png.png)：原片、皮肤、头发、镜框、颈部；小或空区域不是缺少保存，而是没有足够可靠的已表示部件。

背景五个开发视角统一在**原生全幅**重算：

| 参数状态 | room RGB | 结构误差 | 像素边缘误差 | alpha<0.8比例 |
|---|---:|---:|---:|---:|
| 上轮room900 | 0.038891 | 0.051594 | 0.004970 | 5.560% |
| 上轮T4后room | 0.036739 | 0.048569 | 0.004893 | 1.391% |
| 本轮room900 | 0.039202 | 0.051739 | 0.004832 | 0.923% |

本轮覆盖与像素边缘小幅进展，RGB/结构未优于旧局部；柜门细线仍软。旧T4的room指标没有整体变差，**不能据本实验断言joint把背景拉平**。

背景四列顺序：原片／同初值／上轮room900／本轮room900；均原像素，没有后期锐化。

- [柜门与门框](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/portrait-detail-evaluation-20260929-a/static-context-crops/cabinet_door.png)
- [天花板及交界](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/portrait-detail-evaluation-20260929-a/static-context-crops/ceiling_boundary.png)

## 进一步定位到的具体责任

**面部的粗足迹仍在主导。** 旧皮肤最大轴/原生像素尺度中位数7.647，上轮7.522，本轮7.687；本轮P90为10.259。固定参考视角可见皮肤投影半径中位数26像素（光栅化截断半径，不是sigma）。这与细节被平滑的画面相符。255个父点替换只涉及少量表面；不能靠2次小配额就宣称原生细节容量足够。所有部件实际scale都没有低于0.00045下限，所以**不是下限clamp导致梯度全部卡死**。不应未经证据再放宽该下限或全局缩点。

**继承发壳仍是发型主表示。** 2917点的主轴像素尺度中位数约10.3，P99由旧15.56增至18.24。自由offset和颜色确实更新，但没有独立真实外表面约束；结构没有因更多RGB监督自动变正确。眼镜只有5个稳定分类点，部件分组本身不能解决错误几何。

**T1没有大范围交接丢失。** 原生ROI本轮T0→T1 RGB平均差约1.98e-7—2.75e-6，原参数、SH和协方差持续使用。仍不等于完全逐像素一致或排序近似已被排除。

**T2已经引入明显错误遮挡。** 不经过任何新joint，0115的face RGB L1从0.032642变0.090999，脸区room贡献约0.25183；0015从0.025085变0.057308。故不能仅责怪T4的更新权重，冻结场景几何/足迹已经有问题。

**此前“分辨率敏感”需细化为裁剪投影合同问题。** 新冻结场景同全幅视域比较原生/半尺寸时，脸区q_room绝对均差仅0.00024—0.00066；AA进一步变小，但不消除真实room污染。换成脸部小viewport裁剪后则明显不同：同一固定PLY参考0111，先全幅绘制再裁剪的q_room=0.44703，直接小viewport绘制=0.30361；RGB差0.05790。

读取锁定gsplat的Utils.cuh可见投影协方差限制依赖width/height/cx/cy。实测共同可见点中心只差约6.1e-5像素，但两个测试视角各有8个room点的conic相对变化>10%，另有1/5个room点在全幅足迹与裁剪相交、却未进入裁剪输出。参考视角room半径P99约209像素，少量大核不能忽略。**这证实裁剪前后投影/剔除并不等价；未做替换conic及固定排序的单独消融，尚不能把全部差异量化归罪这8点。** 没有改CUDA引擎或查看器来隐藏现象。

[同PLY全幅裁剪／直接viewport对照](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/portrait-detail-projection-20260929-c/frame_0111.png-full-vs-crop.png)。原生F/K/crop/像素与相关hash均在该目录report.json。

## 单份资产、合同和资源

研究资产是**冻结T2诊断合成**，不是joint合格终态。38,372点：人像11,970（9053绑定表面+2917头发），room26,054，身体348。

PLY SHA256：`9fd631a133065c4e02fced9f650914abacd0a716d63f33afe3eb7df49c2cc094`。
[单份PLY连续绕看](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/portrait-detail-evaluation-20260929-a/fixed-ply-orbit.mp4)。72帧全部读取同一资产；K/C、参考0111、checkpoint/source hash保存在asset.json。轨道±20°/±8°只是控制量，不是假称这些都是实际可靠观察角。

原编辑合同的9053表面前缀/精确PLY点序不变；更细语义在新增fine_component字段中，未改变现有编辑读取器。PLY回载RGB均差4.71e-8，最大0.000909；alpha均差1.01e-8。通过的是数值格式与身份，**本轮没有PlayCanvas/鸿蒙绘制或实际编辑测试**，也没有说身份合同等于上脸质量通过。

输入视频SHA256：`7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。
FLAME Open SHA256：`e75a0990728ba038c7da2a420ae4396f7ddd7781366c13026066c5b24f127623`，实际项目内模型路径在pre-change-baseline.json。普通版未引入。

人像阶段114.79s，背景阶段110.74s（均含阶段内检查点/图像审计）；入口总计262.20s，不含原视频解码、分割、SfM和先验拟合。不能称完整链路达到2—3分钟。Torch allocated峰值713.50MiB、reserved1010MiB；2秒外部采样83条、整机显存最大2211MiB，采样非无遗漏瞬时峰值。无OOM，8GB不是本次已证实瓶颈。

21项相关合同回归通过，测试命令和运行环境见environment-and-test-evidence.md。过程错误也保留：投影审计a因int16索引失败，b/c修正并完成；没有为此重复训练。原训练目录不覆盖，未删除失败输出。

## 最小复现与下一步

在Ubuntu-22.04，工作目录W/backend，Python `/opt/self-reconstruction/venv/bin/python`，环境 `PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=4 CUDA_HOME=/usr/local/cuda-12.8 TORCH_CUDA_ARCH_LIST=12.0 MAX_JOBS=2`。使用新的输出目录运行：

```text
python -B -u run_detail_controlled.py <P/backend/.sources/integrated-components-v2-20260928-e> <W/backend/.sources/portrait-priority-training-20260929-a> <W/backend/.sources/新的run-id>
python -B -u audit_detail_controlled.py <prepared> <上轮baseline> <本轮run> <新的评估目录>
python -B -u audit_detail_projection.py <prepared> <上轮baseline> <本轮run> <评估目录> <新的投影审计目录>
```

重现实际训练应先使用run中algorithm-source及config/observations/输入hash；不要用未来默认值反推。所有数值与实际源文件完整hash在result-summary.json及run/contract.json。

**下一项最值得实施的单点：在可靠本人局部表面上，按真实原生投影足迹和多视图对应做局部“粗父核→覆盖保持细核”的成片替换。** 以鼻翼/唇缘一块为受控单位，保留邻域可见覆盖、绑定和Adam，完成恢复后用同脸宽留出对照决定；不是统一缩点、全局翻倍、加900步或再做背景候选枚举。当前约8像素主轴的粗表示使增加边缘损失也难以恢复高频，必须让合理结构拥有足够表示能力；对应不可靠的镜框/发壳不能强行套这一局部替换。

在未来恢复joint前还必须统一全幅投影后切ROI的监督合同，再验证冻结T2错误遮挡；这一点是交接前置，不是本轮已修复。当前E1—E5整体仍不通过，头发真实外表面、镜框、颈肩衣领运动/连接、静态深度与错误遮挡、跨视频泛化、最终设备绘制均为实际缺口。有限A/B已结束，未进入C训练或D联合优化。

参考复用：[gsplat1.5.3策略合同](https://docs.gsplat.studio/versions/1.5.3/apis/strategy.html)、[AbsGS论文](https://arxiv.org/abs/2404.10484)、[COLMAP官方CLI](https://colmap.github.io/cli.html)。采用锁定gsplat已有ops/absgrad及本地有限预算适配，未换引擎；Apache-2.0许可沿用项目已有存档。论文方法与官方示例均不构成SELF人像效果保证。
