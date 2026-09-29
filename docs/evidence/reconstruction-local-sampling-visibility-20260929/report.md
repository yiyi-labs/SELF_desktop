# SELF：冻结 A/B 后的限定采样与冲突归因

日期：2026-09-29。范围：三个既定静态窗口、每窗三张训练图、原59观察点级判断、一次 d=2 单质心研究对照。**没有全局准备、预算重分配、高斯重放、训练、相机重建、MVS、导出资产、部署或回传。** 这不是背景或人像画质通过报告。

## 直接回答五个问题

1. **实际漏了多少独立可接受样点／三角？** 窗口内466次 d=2 提议对应411个独立三角假设；361个唯一质心在至少一个已选提议来源下通过原59观察规则。其中4个已是冻结池中的合法质心，去重后**首次新增合法质心357个，对应357个原来没有合法样点的独立三角假设**。另外50个仍拒绝。没有把9784次全局事件当作独立面积或独立几何。
2. **新增表面假设还是既有表面的重复采样？** 本轮357个新增合法点全部给原无合法样点的假设带来首次点级支持；已有合法表面上的额外新点为0。另4个已有质心只合并来源证据，不重复计数。它们不是新测量的三维几何：顶点仍来自原地图，质心仍依赖三角内部连续性的假设；一个点通过不能证明整个三角真实，也不证明U、累计alpha或背景画质改善。
3. **是否查实无效源参考色导致错误决策？** 没有。350条旧拒绝事件与466条质心事件的源参考均正深度、原边界有效、中心room有效、3×3内9/9为room；无clamp实例。代码确实先取源色而没有独立源有效性门禁，但本次实际范围没有该风险的发生证据，不能据此修改规则或宣布旧冲突无效。
4. **哪些冲突能证明误拒，哪些未知？** 本轮没有独立首表面深度，**确认误拒0，确认同一可见表面真实矛盾0**。实际原片对照找到把手高反差边缘、3×3局部变化与跨视角颜色差异；几何／投影偏移、真实遮挡及反光不能分离。四组人工复核标为“边界／投影／反光原因未定”，不更改原判断。其余保留可见性未知或原规则排除，不把room标签当可见性证明。
5. **下一项唯一最小算法修改是什么？** 建议后续获批后，仅在隔离候选收集器的生成分支加入：通过原三角检查且d=2时提出一个三维质心，使用真实重心身份与其他视角d=3质心合并，再完整执行原59视角点级规则。d>=3、三角阈值、颜色阈值、conflict、相机、scale、opacity、预算全部保持。本轮只实现了审计专用生成器，**未接入生产或改变冻结prepared**。源参考有效性、目标可见性和核重叠另列待审，不同时改第二因素。

结论属于**A：限定范围确认生成缺口**，并同时保留50个失败质心及冲突归因未知；不是“已有全部候选覆盖，因此空枚举无关”的B，也不支持用阈值放宽强行通过。

## 现场、冻结与复现身份

- P：`D:/STUDY/College/mine/olay`。HEAD仍为`f68587bb34f8970d21bda9231e15b2536a33df97`，原有21项跟踪修改及未跟踪文件保留。
- W：`C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay`，分支`codex/reconstruction-v3-audit-20260928`。
- 执行前HEAD：`9a6bef3ef13e47e011421a12a21e255648c76ff2`，parent为`933f664cd700b7845eca14fe1a5671228366d1f1`；后者parent为`27c9810bf0746d8e4382eb218e89276954767d7d`。未按旧hash恢复、回退或清理。
- 入口读取的阶段2A `config.json`记录准备时HEAD为933f664，这是历史运行记录，不冒充当前HEAD。
- 既有未跟踪`reconstruction-stage2a-20260928/replay-report.md`与`reconstruction-v3-targeted-audit-20260928/`原样保留，不随本轮提交。执行前暂存区为空。
- 新独立run：`W/backend/.sources/reconstruction-local-sampling-visibility-20260929-a`。代码、测试、窗口配置和本报告单独提交；私人原片、图像、NPZ和研究资产不入Git、不上传。

| 冻结项目 | SHA-256 |
|---|---|
| 原视频身份 | `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf` |
| 地图／候选namespace | `d2a095bea0f82c85d8cf3b3061a0334e80ad60e23ecf24138cebcf62630fe67e` |
| 原prepared | `22296697a46475e5099a5fe2430852422876150cfc9aaccc3e0b6f124b11ad35` |
| 新prepared（未改、未再初始化） | `681b71264c169cb1892d3dcdc106248a77091d6513288e50e5fe07b027801d81` |
| 冻结triangle-proposals | `a9b58508e06b51ea9252dc6f52a17d8fa183f9246dfe2b71e0a41ca048505ab9` |
| 冻结sample-evidence | `9812dec0bd42d81c8a581cd64595fb03e906add2156e62e2078cb37efb8d6a77` |
| 冻结legal-samples | `f8b6b444f6725885984a748dfb8c53c5446322cd1e841d264da3a0d3ecd8e2dd` |
| 已完成Gaussian replay summary | `36d63b91381c2bfffedd92c16b763608817086ace7a4b7ba550b17affd50be89` |
| 本轮预冻结windows.json | `445adf9469c09a1cca88c4bcbc6b48e21a5f89afe1358fe0f9dbcc632772bdb3` |

A初值恢复和五视角A/B沿用已有证据，本轮**没有执行resume命令**。B的轻微足迹／局部画质退化结论保持；完整枚举与来源记录也没有撤销。244项运行输入在本轮点级执行结束时全部一致。

[冻结输入清单](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-local-sampling-visibility-20260929-a/point-check/frozen-inputs-before.json)包括完整阶段2A目录、实际地图、原prepared、C/K、59张训练RGB与mask及源码。

## 窗口与样本选择先于结果冻结

先查看九张原训练图确认柜门、门板、柜顶／天花板所在范围，再保存窗口和选择规则；没有读取开发RGB来选择点、取颜色或改变阈值。下列坐标均为原去畸变1080×1920图像的`[left, top, right, bottom]`：

| 窗口 | 训练图与固定矩形 |
|---|---|
| 上部柜门与门缝 | 0025、0026：[260,150,820,630]；0040：[170,80,650,610] |
| 左侧下方大门板 | 0133、0134：[290,470,440,1510]；0136：[280,430,440,1500] |
| 天花板与柜体顶部 | 0111、0112、0118：[10,10,740,560] |

选择规则：只读取缓存提议；原始来源属于相应训练图、三顶点正深度且均投影在固定矩形内，即进入局部审计。保留失败提议用于归因，不为增加点数移动窗口。矩形描述静态结构的位置，**不宣称每个像素静态或无遮挡**；例如下门板被人物部分遮挡，仍完整使用原mask排除规则，没有缩小人物mask。

![执行前冻结的九图窗口](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-local-sampling-visibility-20260929-a/frozen-windows.png)

缓存中窗口内共1303个三角提议事件：几何且d>=3为269、d=2为空枚举466、edge349、normal154、depthSpread65。未重新Delaunay枚举；失败的几何提议没有被质心挽救。逐条从原POINT3D_ID读取float64地图顶点，并复核缓存三角判断。

身份：namespace + source_kind=1 + 三个排序后的真实POINT3D_ID形成surfaceId，同时保存每次原winding。重心整数按顶点对应关系重排再最大公约数约分；`(1,1,1)`与d=3、d=6同质心识别为同一点。没有用COLMAP图像ID当帧序号，C按imageName连接并与原map核对。

## 唯一质心对照与跨视角去重

在三维三角内使用`P=(V0+V1+V2)/3`的等价float64重心运算，再经原C、K透视投影；未用屏幕质心或线性深度代替。原生成器在当前d=2提议上提出0点，研究生成器仅提出1点；该点是否已在别的观察生成、是否早已合法，分别记录。

| 统计 | 上柜门 | 下门板 | 柜顶／天花板 | 跨窗口去重总数 |
|---|---:|---:|---:|---:|
| d=2提议事件 | 330 | 26 | 110 | 466 |
| 唯一三角假设 | 300 | 24 | 99 | 411 |
| 其他观察已有合法样点的三角 | 4 | 0 | 0 | 4 |
| 原来完全没有合法样点的三角 | 296 | 24 | 99 | 407 |
| 原来已检验过的质心 | 5 | 0 | 0 | 5 |
| 原来已合法质心 | 4 | 0 | 0 | 4 |
| 尚未检验质心 | 295 | 24 | 99 | 406 |
| 本轮通过的唯一质心（含已有） | 268 | 21 | 81 | 361 |
| 新增合法质心／首次获合法点三角 | 264 | 21 | 81 | **357** |
| 已有合法表面补新样点 | 0 | 0 | 0 | 0 |
| 在本轮提议来源下仍拒绝 | 32 | 3 | 18 | **50** |

不同窗口可能看到同一地图三角，故分列不能直接求和当独立总数。已检验的5个质心中，4个合法身份直接复用，1个以前被拒、本轮仍拒。没有把已有点重复算新几何。

三维点与来源的全量明细见[点身份及坐标](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-local-sampling-visibility-20260929-a/point-check/point-identities.json)、[局部提议及原winding](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-local-sampling-visibility-20260929-a/point-check/local-triangle-proposals.jsonl)、[原判断与审计标签](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-local-sampling-visibility-20260929-a/point-check/local-point-decisions.jsonl)。

全部点继续投影到原59训练观察：正深度、2像素内边界、原room mask、原3×3 GaussianBlur、RGB均值L1严格小于0.10、support>=3、conflict<=1，全部不变。总计实际评估2070个唯一局部点，包含复算既有点及质心；不使用九视角缩减版判据。

**1704条窗口内既有点／来源判断与缓存逐条完全一致**：accepted、supportBits、conflictBits、unknownBits、maskExcludedBits均一致。旧拒绝350个事件对应331个唯一点，其中16个在冻结池的别的来源下已合法，故350或331也不能解释为全局删除数量。

三个质心出现来源敏感：同一XYZ在不同来源下可由“27支持／32冲突”变为“59支持／0冲突”。这是原参考色判据的敏感性证据；没有替换参考、平均参考、修改原判断，也不把某个通过来源当作真实几何证明。

![上柜门局部原片与点级投影](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-local-sampling-visibility-20260929-a/figures/frame_0025-window.png)

![柜顶局部原片与点级投影](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-local-sampling-visibility-20260929-a/figures/frame_0112-window.png)

绿色=研究质心通过，橙色=研究质心拒绝，紫色=旧来源拒绝点；细线只是原三角假设。新增点主要沿把手、柜门线脚等已有结构，大片低纹理区域仍缺少覆盖。图中没有高斯渲染，不能据此承诺整个房间补齐；本轮不额外计算S面积，避免以一个合法质心推定整三角真值。

## 先核源参考，再核目标可见性

原代码先读取clip后的3×3源色，再检查其他图与该颜色的差异；原逻辑不会因源自身无效而自动丢弃参考。该行为在测试中被原样保留，**实际样点尚未发现无效来源**：

| 源参考检查 | 旧拒绝事件350 | d=2事件466 |
|---|---:|---:|
| 非正深度／原边界无效／room中心无效 | 0 / 0 / 0 | 0 / 0 / 0 |
| 越界clamp取色 | 0 | 0 |
| 3×3跨room mask边界 | 0 | 0 |
| 3×3各通道范围均值>0.10（仅诊断） | 170 | 142 |

9/9 room不意味着9个像素来自同一三维表面。把手与后方白门板同属room，可在一个核内混合；最后一行只描述真实颜色变化，**不是新判据或“已证明错误几何”**。

816个点／来源事件中，共6364个原conflict目标事件：5144在九图外；1220在九图内，其中522投影落在某个固定矩形、93属于相同命名窗口。它们仍全部参与原59视角判据。详细冲突制图只覆盖同窗口的93个事件，共81张点／源对照卡；没有扩展到别的帧或窗口寻找解释。另有17张按预先稳定ID规则选取的正／负样例。

机器标签把“有效room但未证明点可见”留作类别3，将原规则排除另列类别5；一个目标出现6/9 room核的边界风险，记类别4但没有扩窗解释。以下四组实际图像人工复核，以单独的`audit_interpretation`记录类别4的具体风险，不回写原标签或原votes/conflicts。

| 点ID前缀 | 原来源→目标 | 原总支持／冲突 | 该目标RGB差异 | 看到的具体风险；仍不能证明什么 |
|---|---|---:|---:|---|
| 035a31684f3f（旧点） | 0112→0118 | 9 / 45 | 0.2363 | 把手内缘，目标3×3色幅0.4275；未证明候选在两图同一首表面 |
| 07675aab3229（旧点） | 0026→0040 | 5 / 49 | 0.2136 | 源处于把手细边，源核色幅0.4418；投影／细边混色／视向颜色未分离 |
| 113c1d1a2945（新质心） | 0025→0040 | 22 / 33 | 0.1362 | 把手底部邻接白门板，核和图像位置敏感；不能直接改判支持 |
| 270989613676（新质心） | 0040→0025 | 12 / 47 | 0.1846 | 把手上弯角，源／目标核色幅0.5098／0.3137；仍无独立遮挡面 |

![旧点：源与目标的把手边缘差异](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-local-sampling-visibility-20260929-a/local-conflict-figures/original_rejected-07675aab3229-frame_0026.png)

![新增质心仍被原规则拒绝](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-local-sampling-visibility-20260929-a/local-conflict-figures/d2_centroid-113c1d1a2945-frame_0025.png)

没有将当前GS的ED或候选自身z-buffer用于认定首表面，也未因没有记录遮挡面就推断无遮挡。**颜色差异是真的；候选是否应被拒仍不能由颜色差异本身裁决。** 图像对照只定位更具体的未知，不把所有冲突一律撤销。机器全量记录、人工四例和跨窗口去重总数见[复核结果](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-local-sampling-visibility-20260929-a/review-results.json)。

## 最小代码、执行与保护

本轮新增文件：

- `backend/audit_local_sampling_visibility.py`：读取冻结池，有限窗口选取，d=2审计质心，原59点级规则复用、旧证据回归、来源及目标分类、输入hash复核。
- `backend/test_local_sampling_visibility.py`：11项合同测试。
- `backend/plot_local_sampling_visibility.py`：限定窗口诊断图，不重建、不调用高斯绘制。
- 本目录`windows.json`与本报告。生产源码、准备算法和入口没有修改。

实际点级命令（W/backend；输出已存在，勿重用run-id）：

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/self-reconstruction/venv/bin/python -B audit_local_sampling_visibility.py \
  --stage2 .sources/reconstruction-stage2a-20260928-b \
  --prepared /mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e \
  --original-backend /mnt/d/STUDY/College/mine/olay/backend \
  --windows .sources/reconstruction-local-sampling-visibility-20260929-a/windows.json \
  --output .sources/reconstruction-local-sampling-visibility-20260929-a/point-check
```

点级运行耗时82.382秒，含冻结输入读验、59观察取色、缓存回归及记录保存；CPU进程峰值422.656MiB。新训练步数0，没有optimizer/backward/density或CUDA高斯绘制；不将这组资源数字冒充建模速度或8GB训练容量。

实际执行适配器SHA为`1880dc64d236969d6037286a3bfd29d6c5eb723aed39b5f6393f056b11d3cf8a`，完整快照保存为run根目录`audit-executed-snapshot.py`。收尾提交版仅增加“已存在输出目录时不往其中写failure记录”的防误重运行保护，数值路径未变，没有重跑点级对照；提交版SHA为`dbaa3d554ce29f9856ff18c4b649652a3c163ff37fdc4d76d772e6fa79625514`。两版明确区分，不把后改源码声称为实际运行快照。

11项测试通过：d=2单质心；d>=3逐值不变；失败三角不能挽救；三维透视质心区别于屏幕平均；跨winding/d=3/d=6身份去重；全部59观察及第58/59视图仍可否决；原无效参考行为未暗改（此项是合成合同，不是实际发现）；原判定与标签隔离；冻结输入变化检测；禁止训练／全局准备／绘制调用；重复输出拒绝且不污染既有证据。

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/self-reconstruction/venv/bin/python -B -m unittest test_local_sampling_visibility -v
```

[测试日志](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-local-sampling-visibility-20260929-a/contracts-final.txt)。点级结论另由1704条真实冻结缓存回归支持，未重复开发PLY、解析、来源守恒或梯度探针。

保护检查：P既有1639项、历史私人242项、v3私人299项SHA全部一致；P status SHA仍为`26338b0026321936b864a2f5aa875c9b6ea5e9f4a6c22b2625eeff0540d8a883`。244项本轮运行输入在计算结束时复核一致；后来只对新审计入口加上述输出保护，执行版已单独保存，旧输入均未变。[保护记录](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-local-sampling-visibility-20260929-a/preservation-before-commit.json)。本地Git不是忽略资产的独立备份，本轮没有移动、清理或上传它们。

## 下一项与停止边界

下一项只建议“d=2通过原三角检查后单质心保底”的隔离算法改动，须用户另行批准。验收先复用本轮窗口：已有判断保持，357个首次合法点身份和证据可复现、50个失败点仍失败、4个原合法质心不重复。随后是否做全局准备或高斯覆盖检查应独立授权；本轮不提前执行。

不把该改动承诺为大面积房间修复；没有实测U/A/RGB收益。后续可见性修复须拿到具体独立证据，不能把所有conflict变unknown；参考色有效性风险也不能因本轮零实例被宣称全局不存在。

**本轮限定任务完成后停止。** 应用、签名、旧作品、USB/HDC、PlayCanvas、上脸与故事保持。face/hair/glasses/cloth/joint仍独立未完成；v3依然没有face训练、没有density、joint为占位入口。没有坏候选回传或发布，没有降低E1—E5标准。