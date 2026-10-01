# SELF：完整场景保留、局部去雾与头发覆盖修缮

2026-10-01。在原隔离 worktree 的有限后端实施。完成真实 GPU 优化、实际 PlayCanvas 2.22.4 绘制和单资产绕看。**局部有进展，整体验收仍未通过；没有部署、回传或切换生产。** 原 E1—E5 不变。

## 先回答结果

- **完整背景保住了吗？** 本轮改用现存 50095 点 body-transition-sh 完整场景作为研究起点，没有再用旧 R0 的 348 身体种子画面替代它。参考画面中的柜门、天花板、肩部、胸前衣物都保留；局部去雾后也没有出现上一轮整体换 room 所造成的大片空洞。但侧面仍有遮挡、薄雾和边界缺口，不能称所有角度无洞。
- **脸更清楚了吗？** 参考画面由 room 造成的脸前污染明显减少。脸本身的几何和外观参数本轮固定；这是解除污染，不是恢复了新的皮肤细节。PlayCanvas 的旧脸本来比 gsplat 清楚，不能把 gsplat 的大幅改善直接当成平板人脸细节同幅度改善。
- **颈肩还割裂吗？** 短窗颈部实际训练改善了颜色；独立颈部候选未触发预设数值回归项。但是下颌—颈部接缝和整段身体运动仍未成立，不能用颜色改善宣布连接修复。
- **头发实际改了什么？** 将有支持的 751 个粗壳点替换为 6000 个去重的原片取色外表面候选，真实优化 offset、scale、rotation、alpha、SH。参考画面的发际线和头顶比旧帽状壳更有结构，覆盖从首版约 60% 恢复到约 92%。仍有三个侧向完整合成观察退化，而且实际 PlayCanvas 的参考 hair RGB 没有优于旧基线。候选拒绝。
- **其他有效内容受到影响了吗？** 原工程、应用、签名、旧作品、USB、生产查看器、AI/OLAY/上脸与故事没有修改。各研究分支通过冻结参数与完整状态恢复检查。但是冻结参数不代表所有画面完全不变；共同遮挡会改变图像，因此逐部位退化也单独记录并拒绝。

## 起点身份和恢复

- W：C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay。开始 HEAD `cdebe50144f1361d40e5f25d91c696ddd24782f5`，分支 `codex/reconstruction-v3-audit-20260928`。
- P：D:/STUDY/College/mine/olay。HEAD `3dad0cd5651824cc06d9e88d61aabdd2642c0b30`；原有 18 个 tracked 修改和未跟踪文件保留。没有 reset、clean、stash、amend、rebase、强推或删除 run。
- 真正本轮完整起点：`W/backend/.sources/continuity-physical-surfaces-20261001-b/body-transition-sh`。
- 原参考 PLY SHA256：`a343ccf05292ce1e174c7fd63795122347a8d03bd0202a19395a9a414b691f41`，50095 点，参考 `frame_0010.png`。
- `audit_complete_baseline.py` 严格恢复全部 model 字段、形状、dtype、值，再导出同一参考状态：**50095 点 PLY 逐字节 hash 相同**。证据在 `.sources/complete-preservation-baseline-20261001-a/result.json`。
- 视频 capture-1790410633104.mp4 SHA256：`7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。
- prepared：`P/backend/.sources/integrated-components-v2-20260928-e`，preparation SHA256 `e67d4dce02f9874e0befe15486532f80458f8a62a23221324fcc5abefc2e5301`。
- 原始 fullframe R0 仍存在，SHA256 `2468edc379f8b76eac97fccfbf9e9a4c775f980102b95283ee15b2dc4cee7cb8`。它是加载完整候选所需历史依赖，不是本轮最终显示起点。
- 头发表面缓存：`.sources/continuity-physical-surfaces-20260930-a/hair-surface`；原片颜色和多视图兼容候选，**相机条件预测深度不是独立几何真值**。未重新下载工具、推断网络、匹配或选择 FLAME 版本。
- 没有读取平板当前作品 hash；不能说上述完整研究起点就是当前平板显示的资产。

完整起点本身未被发布门禁放行。它保留 26054 个旧 room 点，退役旧身体 86 点和旧 head-neck 191 点，加入 12000 个 neck/cloth 表面点；存在短窗外身体运动未知、头发旧壳、镜框和接缝等缺陷。“更完整”不等于“质量已通过”。

## 修改如何保留完整内容

### 局部 room 核分解和恢复

`reconstruction_kernel_factorization.py` 不删除整片背景，也不将 room 整体推远。以真实全幅 alpha×transmittance 对脸区的贡献，在训练观察中选择至少两次出现的最多四个 room 核；本次 room index 为 25810、25170、24888、25934，UID 为 28736、28096、27814、28860。

每个父核沿其最大的两个协方差主轴作 7×7 Gauss–Hermite 分解，四个父核真正退役，196 个子核共同参与完整排序合成。SH 和来源继承原核，不生成新的场景几何。低频覆盖由原片误差、coverage 保护和有限恢复检查约束；不是长期蒸馏旧雾图。

未截断的密度求积保持均值与协方差矩，**不保持 alpha 合成恒等**；opacity 上下限也可能改变密度矩。执行快照原先只记录上限 clamp 数，当前代码补充下限 clamp 和 before-clamp 含义；这是审计口径修正，没有重写旧候选或重跑训练。不得将旧 config 的 `preservesDensityMoments=true` 解读为最终透明度图相同。

A/B 同 23 个训练观察、300 次原生图像反传、同 K/C/F 和图像序列。全幅 1080×1920 绘制后计算 mask 损失；没有小 viewport。SH、alpha、scale、quaternion 实际更新，180 步后每五步一次有界 offset；其他人物和身体源参数保持精确值。

| 参考0010，固定本分支 mask | 完整起点 | 300步分解 | 后续有限恢复 |
|---|---:|---:|---:|
| face RGB L1 | 0.096105 | 0.025333 | 0.025144 |
| face 的 q_room | 0.272726 | 0.042520 | 0.039845 |
| neck RGB L1 | 0.049737 | 0.057424 | 0.037113 |
| cloth RGB L1 | 0.050128 | 0.053049 | 0.052434 |
| room RGB L1 | 0.025701 | 0.027104 | 0.024783 |
| room alpha均值 | 0.958449 | 0.954684 | 0.955379 |
| room alpha<0.8比例 | 0 | 0 | 0 |

alpha 阈值仅是代理；同时看了 RGB、真实场景结构和完整画面。上述不是所有视角统计。另一个0130观察 face L1 从0.032331变为0.034310，neck从0.138589变为0.092183，cloth从0.155563变为0.154036。仍有其他角度超过保护容差。

分解后薄雾移开，暴露出原先 neck 的真实色差；因此做独立明确的240步诊断续训：只开放 room 子核及已知五帧短窗内 neck 的外观/scale，脸、头发、衣物、运动和全部几何固定。它源于失败候选，仅为诊断续训；不是与300步控制组相同预算的单因素A/B，更不是通过基线。

![原片、完整起点、局部去雾与颈部恢复](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/complete-local-preservation-20261001-b/final-images/frame_0010.png.png)

### 颈部独立分支

`contact_pairs` 只对已有 neck 与已有 head-neck 的有限近邻施加同皮肤软接触，不连衣物，不把FLAME或旧头模当测量真值。实际只获得五对近邻，几何证据很弱。

五个有效短窗训练观察、十个完整合成评价观察，240步实际训练3000个neck点，其余cloth点、房间、头部和身体运动精确冻结。参考neck L1从0.049737到0.042107；0130从0.138589到0.134484。预设RGB/alpha/孔洞退化记录为0，但肉眼接缝仍在。

**只保留训练入口、短窗颜色改善及可恢复事务能力；不宣称成熟颈肩结构。** 五个接触近邻不能约束全片的头—颈—肩运动，短窗外原来的身体恒等诊断仍是未知，不因本轮颜色训练变成已验证运动。

### 头发：定位一对一替换的覆盖错误后做有限修正

原751→751方案将宽核换成小表面点。参考头部局部T0的hair contribution从0.93270骤降到0.60287，240步后仅0.67758，局部hair L1由0.03398恶化到0.06997。完整T2总alpha仍接近1，因为缺失hair处由room接管；**总alpha高不表示头发完整**。

这不是增加900步、刷黑、加高光的理由。实际新增 `exterior_patch`：

1. 维持同751个有支持的退役父点集合，其余2166旧hair未知点保留。
2. 从现存hair surface候选选相邻真实样点，最多24近邻、总上限6000；点自身来自原片取色，不复制父核充数。
3. 每点仍需要至少三个原训练hair像素支持、原support>=3及16原生像素对应的有限空间范围；未知/越界不当空区，开发RGB不选点。
4. 按候选index/UID跨父点去重，保留每个父点已有首候选，再按rank-round扩展，来源、父点和缓存hash保存到checkpoint。
5. 保留标准SH、局部坐标、scale/quaternion，使用头部局部训练；所有部件仍在完整T2评价中共同绘制。正常皮肤不压到头发中，不统一放大scale或调高opacity填洞。
6. 同240步，同17个训练观察/22个评价观察。实际31步有界offset更新，其余步骤恢复原片颜色、alpha、旋转和尺度（0.8—1.2范围）。

| 参考0010局部T0 hair | 原完整头部 | 首版一对一终态 | 6000点初值 | 6000点优化后 |
|---|---:|---:|---:|---:|
| RGB L1，缺失计入 | 0.033984 | 0.069972 | 0.051270 | 0.033550 |
| 实际hair贡献 | 0.932701 | 0.677583 | 0.879809 | 0.923528 |

这是**修正首版覆盖严重退化**，并有参考发际线的可见变化；不是证明比旧完整头部全面优越。0035局部hair L1由旧0.030617到0.034286，0130由0.036163到0.041989，0145由0.043925到0.051669。完整T2仍拒绝0134、0139、0145三张hair观察。覆盖与局部几何/颜色一致性是不同问题，不能只看92%宣布发型成立。

![原片、旧头部、真实外表面覆盖恢复](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/complete-attachment-preservation-20261001-d/local-final/frame_0010.png.png)

执行c/d快照的config中 `allComponentsVisible=true` 是评价口径，训练实际是head-only T0。当前源代码已分成 `allComponentsVisibleDuringTraining` 与 `allComponentsVisibleDuringEvaluation`，保留当次快照，未伪改历史字段。T0不算完整joint。

## 双端实际绘制与一份资产绕看

使用现有锁定 `scripts/probe-dense-surface-display.mjs`，没有修改生产查看器。Chrome SwiftShader，PlayCanvas2.22.4，canvas/CSS均1080×1920，maxPixelRatio1，COMPACT、minPixelSize2、AA=false、radialSorting=false、unified=true、无LOD；gamma1、toneMapping0、exposure1、fog=none、postEffects0。读取原始预乘RGBA并按既有合同对齐。六次资产加载均无异常。

原生相机最大差约5.45e-8。以下是同参考PLY的gsplat—PlayCanvas差异，使用显示审计的固定mask，**与训练分支mask口径分别保存，不拼成同一指标**。

| 同资产显示差异 | 完整起点 | 局部分解 | 去雾/neck续训 | hair外表面 |
|---|---:|---:|---:|---:|
| 全幅RGB MAE | 0.090770 | 0.028024 | 0.030623 | 0.090710 |
| face RGB MAE | 0.089696 | 0.007393 | 0.007584 | 0.089549 |
| hair RGB MAE | 0.203489 | 0.012612 | 0.014097 | 0.203583 |
| room RGB MAE | 0.121577 | 0.041832 | 0.045896 | 0.121591 |

去雾续训的PlayCanvas room对原片L1从0.130032改善到0.056808；PC face原来0.025212，候选0.025817，**并没有大的face细节提升**。hair独立候选PC hair对原片从0.044775变成0.046172，未优于旧值。因此头部T0的局部变化不能包装成最终显示改善。

![局部去雾候选的实际PlayCanvas画面](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/complete-preservation-display-20261001-a/playcanvas-01/exposed.png)

单资产参考hash：

- 完整起点：`a343ccf05292ce1e174c7fd63795122347a8d03bd0202a19395a9a414b691f41`。
- 分解：`ec06db955c2a9c876b4c04daebfa6cb1e738329c7aa7a9090d8d231e523068ea`，50287点。
- 去雾/neck续训：`0a65aee553cf2aae2d942ce8d451b95c0599dd0023b20481e1b4d74e405be62e`，50287点。
- 独立neck：`032eff818fb51e4f1fd4302b80f8049d43d757a4faddc61742da14acd6f41cd4`，50095点。
- hair外表面：`35d4302f9a0d35677cdd7612a75afae23ae7ed0aa4d750e8e707b43df623e805`，55344点。

去雾续训及hair外表面的各自同一PLY均完成121帧连续绕看，0→-60→+60→0，不按角度换模型；q守恒最大误差7.75e-7，namespace/UID唯一。录像来自gsplat1.5.3，1080×1920绘制、540×960编码，**不是PlayCanvas或鸿蒙fps**。viewer yaw不等于原片可用的人脸真实观测角。侧面实际截图仍明显有白雾、hair软和颈接缝，录像不能计为画质通过。

- [去雾同一PLY连续绕看](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/complete-local-preservation-20261001-b/asset-check/frozen-ply/frozen-ply-orbit.mp4)
- [hair同一PLY连续绕看](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/complete-attachment-preservation-20261001-d/asset-check/frozen-ply/frozen-ply-orbit.mp4)

## 实际预算、退化与状态恢复

| 独立分支 | 步数 | 训练及评价秒 | Torch allocated/reserved MiB | 退化记录数 |
|---|---:|---:|---:|---:|
| 原四核控制 | 300 | 159.48 | 1831/2150 | 26 |
| 四核→196子核 | 300 | 198.67 | 1831/2150 | 22 |
| 去雾后neck续训 | 240新增 | 174.04 | 1943/2332 | 9 |
| 独立neck | 240 | 58.47 | 795/1134 | 0 |
| hair一对一完整T2训练 | 240 | 90.40 | 749/1102 | 22 |
| hair一对一局部T0训练 | 240 | 95.32 | 873/1050 | 22 |
| hair6000表面点局部T0训练 | 240 | 120.96 | 881/1054 | 3 |

退化数是逐图像/部位/指标记录，不是独立场景数量。预设数值筛查RGB+0.003、平均alpha下降0.015、孔洞代理增加0.02不能代替真实结构/身份/多角度验收。去雾续训9条是cloth0052、room0052、cloth0005、neck0119、cloth0119、neck0042、face0134、face0135、neck0115；详见results.json，不为放行改容差。

后两续训总运行分别300.51秒、238.48秒，含载入及初终完整评价等；没有计入视频准备。RTX5070Laptop本轮计算正常，没有OOM。Torch峰值不是整机总显存；没有证据将这轮缺陷归咎8GB，也不能据此承诺任意完整任务都不超8GB或2—3分钟。

36项合同回归通过，包含新核分解、真实候选去重/预算/可见观察规则及既有连续motion、原生face测量、覆盖保护。各run保存init/mid/candidate-final/restored、Adam、策略、采样器、RNG、绑定、来源和执行源码。七分支初始与restored的model、optimizer、bindings、samplers、rng、strategy、trainable逐字段精确相同。回恢复的是本分支完整状态；新Adam不是旧900步的精确resume。

代码提交不备份被忽略的私人模型资产：影像/PLY/checkpoint仍保留本机原研究目录，本轮没有独立外置备份或上传。标准PLY加载、唯一UID与字段存在不等于AI编辑兼容已验收；本轮未测新个人编辑、HarmonyOS、手机、多用户、重新拍摄或完整端到端耗时。

## 哪些可保留，哪些不采用

可保留：完整场景严格恢复/逐字节导出、局部有界核分解、原片像素保护训练、同皮肤接触限定、真实hair外表面候选去重与覆盖恢复、原生全幅共同评价、双端同资产与可恢复事务。

仍拒绝作为作品：四核控制、分解、去雾续训、全部hair候选。独立neck只过数值不退化筛查，未过完整连续结构门禁。没有把不同失败候选拼起来，假称综合模型通过。

尚缺：可观测的连续head-neck/body运动、可靠发际线/鬓角三维关系、镜架结构、面部原生细节、多角度连续完整环境、真实设备与跨用户验收。脸几何本轮未训练；衣物保持完整起点，不声称本轮重新修好了它们。

当前最有价值的下一项不是再扩大点数或增加步数，而是**同一连续观察窗口的头—颈—上身运动与外表面对齐**：以原片可见轮廓/真实纹理的对称多视图约束，固定参考F、K、身份和尺度，分开限制头F与身B，将颈皮肤作为真实连接，衣领保持独立接触层。先证明源/目标/第三观察同步改善，再为相同点数做外观恢复。现有五帧身体运动和预测hair深度不足以保证整段真实侧面；不通过更多小点或颜色优化掩盖这个几何缺口。

此建议是下一项研发定位，不是已接入成熟motion系统。当前已有的完整背景监督、正确head-local SH1、全幅合同、密度历史与E1—E5保持，不引入互相冲突的渲染深度或颜色表示。

## 复现与文件级交付

工作目录W/backend，Python `/opt/self-reconstruction/venv/bin/python`，Ubuntu-22.04；统一加 `PYTHONDONTWRITEBYTECODE=1` 与 `-B`。实际各执行快照在run的algorithm-source，当前代码后来的元数据澄清不代表历史快照自动改变。

```text
run_complete_local_factorization.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --out <new-room-run> --steps 300
run_complete_attachment_recovery.py --complete <complete> --out <new-neck-run> --component neck --steps 240
run_complete_attachment_recovery.py --complete <complete> --surface .sources/continuity-physical-surfaces-20260930-a/hair-surface --out <new-hair-run> --component hair --steps 240 [--local-hair-training] [--dense-exterior]
run_complete_exposed_recovery.py --complete <complete> --source .sources/complete-local-preservation-20261001-a/factorized --out <new-recovery-run> --steps 240
audit_complete_baseline.py --complete <complete> --out <new-identity-audit>
audit_complete_preservation_display.py --folder <label>=<candidate-folder> --out <new-display-input>
audit_complete_preservation_state.py --folder <candidate-folder> --out <new-state-audit.json>
audit_continuity_asset.py --folder <candidate-folder> --out <new-asset-check>
```

实际room为`.sources/complete-local-preservation-20261001-a/{control,factorized}`；续训为`...-b`；neck/hair四分支为`.sources/complete-attachment-preservation-20261001-{a,b,c,d}`。Chrome输入为`.sources/complete-preservation-display-20261001-{a,b}`，实际浏览器命令在W根目录：

```text
node scripts/probe-dense-surface-display.mjs <absolute-new-display-input>
```

复用 `audit_motion_display_comparison.py --prepared <prepared> --browser-report <playcanvas-01/report.json> --identity-map <identity-map.json> --out <new-comparison>`。不重用已存在out，不覆盖run-id。

本任务显式文件：

- `reconstruction_complete_context.py`、`audit_complete_baseline.py`：严格完整起点恢复及参考字节回归。
- `reconstruction_kernel_factorization.py`、`run_complete_local_factorization.py`：局部room表示和实际对照。
- `reconstruction_observed_attachment.py`、`run_complete_attachment_recovery.py`：真实hair候选及neck限定训练。
- `run_complete_exposed_recovery.py`：明确的去雾后neck外观诊断续训。
- `audit_complete_preservation_display.py`、`audit_complete_preservation_state.py`：双端输入与完整恢复核对。
- `test_complete_local_factorization.py`、`test_observed_attachment.py`：13+3项新增合同回归。
- 本目录`report.md`、`results.json`、`verification.json`：结论、实际配置/曲线/每视角/检查点hash及保护记录。

前一轮已存在的observed-coverage文件和`build_continuity_candidates.py`修改不属于本任务，没有顺带提交或清空。没有新增生产入口、换引擎、模型下载、CUDA/驱动改动或电脑重启。
代码保存首提交：`db3bf80492d6f3615ca0dbfaa53658d13bec864a`（完整场景恢复及局部分解）。附件、双端证据与报告另作后续独立提交；不包含前一轮未提交文件。
