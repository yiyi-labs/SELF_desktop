# 连续几何、真实头发表面与背景保护修缮：本轮实测

日期：2026-10-01。范围：既有隔离 worktree 的研究后端；不修改生产、应用、查看器、签名、USB/HDC、AI/OLAY/编辑/故事，不部署、不回传。

## 先读结论

本轮完成实际代码与有限 GPU 训练，**尚未实现“人脸、头发、衣物与完整房间同时清晰且没有接缝/薄雾”**。不能因一些指标或短窗纹理改善切换默认模型。

- 颈部：连续形变协方差与材料权重导数已接通，短窗颜色略有改善；头—颈接缝仍在，真实全片身体运动仍不足。
- 面部：新的真实轨迹和共享表面求解确实运行；外观恢复后局部面部 RGB 和肉眼清晰度没有稳定改善。拒绝该几何候选作为新主干。
- 头发：固定相机、原像素合同下实际 OpenMVS 融合得到真实表面。4000 个多视图支持点替换了 695 个旧发壳点，其余 2222 个未知区域旧点保留。部分训练观察的纹理和体积有所改善，但其他观察退化；没有放行整个发型。
- 环境：实际 MVS 表面替换明显减少脸前 room 污染，却造成背景覆盖和颈/衣物退化；完整环境保护门禁拒绝。旧完整场景不变。
- 显示：本轮实际运行 PlayCanvas 2.22.4 与 gsplat，同 PLY/相机/原生尺寸；差异仍显著，未发现 fog 或后处理启用。HarmonyOS 未测试。

所有新候选 `transactionAccepted=false`、`releaseQualityPassed=false`、`published=false`。没有自动替换旧资产。

## 冻结身份与可恢复性

W：`C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay`。
P：`D:/STUDY/College/mine/olay`。
起点 W：`b7f044a5771c47a4db7c3171a4e3051c2475abee`，分支 `codex/reconstruction-v3-audit-20260928`。
P：`3dad0cd5651824cc06d9e88d61aabdd2642c0b30`。

本轮完整研究起点：`backend/.sources/continuity-physical-surfaces-20261001-b/body-transition-sh`，50095 点，参考 `frame_0010.png`；它本身不是质量已通过作品。

| 身份 | SHA-256 |
|---|---|
| 原视频 | `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf` |
| preparation.json | `e67d4dce02f9874e0befe15486532f80458f8a62a23221324fcc5abefc2e5301` |
| R0-frozen.pt | `2468edc379f8b76eac97fccfbf9e9a4c775f980102b95283ee15b2dc4cee7cb8` |
| 完整研究起点 PLY | `a343ccf05292ce1e174c7fd63795122347a8d03bd0202a19395a9a414b691f41` |
| 新观测 tracks.json | `6f951a8b247ab2316fcef009953e5453140e8362e33aa84ad082ea99b4c3097f` |
| 固定恢复 F 的头部 MVS dense.ply | `a8862cd40288eb474a54b494c68551bbf2f58a9ce02f2593f06f93f968592ed0` |

每条实际图像训练控制/候选均保存 initial、mid、candidate-final、restored、Adam、绑定、稳定 ID、来源、RNG、采样器以及当次源码/config。恢复比较源状态逐张量完全一致。原900步没有Adam，未称精确resume；新优化器是从完整恢复源参数开始的独立研究训练。

`.sources` 保留失败模型、原始诊断图和私人研究数据；没有移动/清理旧run，没有上传。Git仅保存显式列出的新代码和无照片的报告。没有独立异盘备份，Git不能恢复被忽略的私人资产。结束状态与资产hash另见 `protection.json`、`summary.json`。

## 实现与真实运行

### 连续颈部场

`reconstruction_surface_continuity.py` 和 `run_continuous_surface_repair.py`：一个共享有界24节点场，H/B材料权重连续过渡；中心、协方差和SH1随局部映射运输，皮肤软接触不连接衣领。

两组相同200步（80几何、120外观），其他人体/衣物/room/相机全部冻结，完整场景共同合成。最大形变量按原生像素等价的每轴4像素设定，不是保证任意视角屏幕位移都小于4像素。

首次对照16个同皮肤近邻；上部neck到旧head的近邻距离 q10/50/90 为15.45/35.98/53.84原生像素等价。这个缺口明显大于允许局部形变范围，近邻不是独立测量真值。参考neck固定mask L1 0.049737→0.044715，但接缝肉眼可见。短窗外B未知，仍是冻结恒等诊断，不是已求得全片身体运动。

最终回归发现材料权重导数重复链乘：正确形式为 `Rblend @ Jfield + (head-body) outer grad_material`，不是整个和再乘Jfield。已加实际变形自动微分对照并在 `neck-material-jacobian` 重做200步控制/候选。修正候选参考neck L1为0.044714，0013为0.065233（旧0.062651），保护计数仍为0，但接缝未通过；其资产SHA为`5536b97e07b165cacf4b55eba264748f600936adf44030fe60523aa2e7fbdd6a`。首次源码与图像全部保留，不把修正后的代码解释成首次执行。

协方差的前向为JΣJᵀ；谱分解特征向量与SH的极分解旋转是detach的，中心/特征值可反传，不宣称完整特征基梯度。它目前是受限研究实现，不能掩盖颈肩观测不足。

### 新测量与面部共享几何

`run_continuous_observed_tracks.py` 按真实timestamp自动选择最多3个短窗、间隔和长度受限；第一/中间/末尾训练源都尝试。原像素LK、前后向、直接/串联循环、对称ECC精化，加条件三角化、留出第三观察与数据Jacobian检查。

不是重复旧56条轨迹：本轮实际得到127条条件face三维轨迹、72条hair三维轨迹和1300条cloth二维轨迹；neck为0。cloth统计中的记录数不等于已通过三维重建。

低自由度上身短窗拟合实际32.72秒；三窗可信三维轨迹分别0/2/5，留出第三观察p90分别14.79/3.74/5.30px，全部拒绝；没有把新的B写进完整起点。原视频仍有两侧本人观察，不写成用户没拍另一侧。

共享面部场固定F/K/C/身份/尺度/拓扑，每条物理轨迹只有一个共享锚，源与目标共同约束，最后第三观察不参加求解。

| face几何，110锚/24控制 | 起点 | 纠正后 |
|---|---:|---:|
| 拟合中位数px | 1.03254 | 0.88902 |
| 拟合p90px | 2.72912 | 1.99071 |
| 第三观察中位数px | 1.50483 | 1.55627 |
| 第三观察p90px | 3.71820 | 2.97119 |
| 源p90px | 约0 | 1.38487 |

源最初接近零来自射线构造，不是三维真值；第三观察中位数略差。1527个实际face点受影响，颜色/alpha/scale各180步等预算恢复，其他参数冻结。参考head-only face固定mask L1：旧0.022889，外观控制0.023613，几何候选0.023740；0015也变差。不能以T2的灰雾遮住变化或中位数下降宣布面部清晰。

![原片／旧头部／共享几何候选](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/continuous-geometry-repair-20261001-a/face-local-evidence/measured-candidate/frame_0010.png.png)

### 真实头发表面

先前紧凑场20锚虽使第三观察p90 4.426→3.092px，但52轨迹离旧壳过远，实际只影响5个旧Gaussian。它不是发型修复。

本轮复用已安装固定OpenMVS 2.4.0独立CPU程序，4线程/360秒上限；不安装新依赖、不修改阈值、不生成皮肤或刷黑头发：

| 实际输入 | 结果 |
|---|---|
| 仅44条hair轨迹、4幅全图 | 0深度图、0稠密点，未生成dense.ply；exit=0不代表成功 |
| 同44条hair轨迹、原像素ROI | 同样失败，不能仅归咎整图面积 |
| 加同短窗59条face可靠轨迹、7图 | 4深度图、18768融合点；使用准备F，与恢复模型F不同，合同拒绝交接 |
| 同103条真实轨迹，用恢复检查点的固定F重新三角化，原像素ROI | 18115融合点；4759点具有至少3个实际融合hair观察及有效原片hair像素支持 |

准备F与恢复F的矩阵最大差曾达到0.00209851，不能直接混用。新入口实际检查相机一致；重三角化不优化相机、不新造位姿、不更换真实二维观测。

ROI是MVS输入的原像素切片，RGB没有绘画、涂黑或重采样，cropK/观测坐标减同一偏移。它不改变gsplat完整1080×1920渲染后切ROI的合同。MVS内部resolution-level=1是真实几何估计分辨率，后续外观训练用完整原片，不能把它称原生深度精度。

[OpenMVS 2.4.0实际导入源码](https://github.com/cdcseacave/openMVS/blob/v2.4.0/apps/InterfaceCOLMAP/InterfaceCOLMAP.cpp)会移除COLMAP半像素主点偏移。新导出对native K/观测+0.5一次，导入后还原；检查实际cameras.txt而不只信JSON标签。旧B-mvs缓存使用整数主点导出，实际导入存在0.5px差；本轮room分支快照保留该限制，新入口现已拒绝这类缓存，不假装room结果来自修正后的输入。

`build_native_head_surface.py`、`run_native_head_surface_repair.py`：按真实融合来源、原片颜色、法线和采样后近邻尺度构建4000点，替换695个在至少3个源观察有有限投影对应的旧hair点；保留2222未知旧hair点。父点对应规则是提议，不是独立可见性真值。固定中心、相机与其他部件，仅SH/alpha/scale/rotation各180步。unknown部分不削掉；所有head共同局部合成，完整T2仍包含所有组件。

| 固定hair区域（head-only） | 旧 | 新表面180步后 |
|---|---:|---:|
| 训练0040 L1 | 0.028283 | 0.025564 |
| 训练0041 L1 | 0.028554 | 0.023602 |
| 训练0042 L1 | 0.028007 | 0.024965 |
| 训练0043 L1 | 0.031144 | 0.027583 |
| 参考0010 L1 | 0.033984 | 0.038536 |
| 开发0035 L1 | 0.030617 | 0.039826 |
| 开发0130 L1 | 0.036163 | 0.049437 |
| 开发0145 L1 | 0.043925 | 0.053882 |

局部纹理可见，但训练0037/0038及开发0035/0130/0145完整合成超过保护容差。其他head-only角度也多有退化。该短窗几何不能当作全片发型，不能以4个训练视图改善取代跨视角验收。

![真实原片／旧发壳／真实MVS头发表面训练后](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/continuous-geometry-repair-20261001-a/hair-native-surface/actual-surface-candidate/final-local/frame_0042.png.png)

### 完整环境保护与薄雾

`run_complete_room_surface_repair.py` 由训练观察贡献提议4个重复遮脸的room点（索引25810/25170/24888/25934；UID与源记录保存），不是删全家族。

旧中心三维椭球把真实后方表面排除，故只把有限真实投影足迹用于候选提议，再由实际MVS融合视图、正深度、room有效3×3原片像素核验支持。线性投影代理不是真实可见性。8000真实点代替4个核，另外26050room点和完整人物参数精确冻结，同240步控制/候选；原来的完整room RGB监督保留，不声称首次实现。

| 参考0010完整合成 | 完整旧场景 | 实际表面替换后 |
|---|---:|---:|
| face L1 | 0.096105 | 0.022937 |
| face q_room | 0.272726 | 0.002849 |
| hair L1 | 0.224791 | 0.036389 |
| neck L1 | 0.049737 | 0.062000 |
| cloth L1 | 0.050128 | 0.053034 |
| room L1 | 0.025701 | 0.153017 |
| room alpha均值 | 0.958449 | 0.894363 |
| room alpha<0.8比例 | 0 | 18.47% |

102项RGB/覆盖/孔洞代理保护检查失败；旧4核外观控制也有25项失败。**脸变清楚但房间丢内容仍失败**。当前7个后段MVS观察支持的表面没有接替旧宽核承担的其他真实环境范围；8000点多不等于覆盖完整。alpha<0.8是覆盖代理，不等于没有几何。还叠加旧缓存半像素约定限制，不把全部损失归因于它。

## 实际显示与绕看

复用锁定PlayCanvas 2.22.4脚本，不改生产设置。Chrome SwiftShader、1080×1920实际canvas/CSS、maxPixelRatio1、COMPACT、minPixelSize2、AA=false、unified=true、无LOD、radialSorting=false、gamma1、toneMapping0、exposure1、fog=none、postEffects0。7次资产加载无错误；不把这写成鸿蒙或硬件fps。

相机最大矩阵差约5.45e-8。原生预乘RGBA8只垂直翻转；无二次alpha/gamma修饰。显示mask与训练mask分别保存，不混成一个指标。

| 相同PLY的gsplat—PlayCanvas差异 | 完整起点 | 实际room表面候选 |
|---|---:|---:|
| 全幅RGB MAE | 0.090770 | 0.042002 |
| face RGB MAE | 0.089696 | 0.006458 |
| hair RGB MAE | 0.203489 | 0.006356 |
| room RGB MAE | 0.121577 | 0.064308 |

背景候选使差异缩小，但因内容损失拒绝；不能拿两个渲染器相似当质量通过。hair真实表面候选全幅差0.090368、face差0.089585、hair差0.186357、room差0.121604，仍继承旧room病态表示和显示差异。没有通过增光、对比度、gamma修改或删背景改善截图。

两份不同研究资产各自固定hash绕看，不能相互拼成一份模型；每个视频121帧由gsplat生成，viewer相对yaw不是人脸真实观察角，未经原片支持的外推区域不称重建正确。

- [颈部首次研究候选连续绕看](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/continuous-geometry-repair-20261001-a/neck-fixed-orbit/frozen-ply/frozen-ply-orbit.mp4)：`d82c752008b19b24943eb5f8fff257c1d794f02ad2c332294c6f1612f0c629de`。
- [真实头发表面候选连续绕看](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/continuous-geometry-repair-20261001-a/hair-surface-fixed-orbit/frozen-ply/frozen-ply-orbit.mp4)：`a5a2923dfb69f08e34d2945e8424e066dca83d66d02f73d4287006f7427f65ee`。

两份来源贡献守恒最大差均7.75e-7，UID命名空间唯一；这些是合同结果，不是整体质量通过。

## 资源、通用性与未完成项

本轮CUDA设备：RTX5070Laptop；torch2.8.0+cu128/CUDA12.8、gsplat1.5.3。实际环境、光栅化源码hash见system.json。12条实际GPU控制/候选累计2360次Adam迭代，最终29项合同回归通过；峰值allocated为1819.19MiB、reserved为2100MiB；没有OOM。Windows采样约1.8—2.3GiB不是连续系统峰值，PyTorch统计也不覆盖全部外部显存。不能据此保证任意新输入都不超8GB。

每组控制/候选包含真实optimizer步数与参数变化；CUDA光栅化反向的浮点累加可能不确定，恢复状态精确不代表另一次训练能生成字节相同资产；累计研究有多条独立分支，不把合计时间称单次服务耗时。部分单分支训练+终态评价约70—145秒，首次face整轮含测量、加载、初终多图和IO为464秒。没有完成原视频准备至可发布完整模型的2—3分钟验收。

原始选帧规则基于timestamp/有效训练角色，提议基于当前样本的真实贡献/实际MVS来源；没有硬编码本人脸坐标、衣服logo或历史失败窗口。验证仍只有此原视频，**跨用户泛化未验证**。8开发/6固定回归已有多次研发使用，不称独立最终盲测。

未实际修复的项：整副镜框（仍不是5个分类点就等于完整镜架）、全片非刚性头发、完整衣物/肩颈运动及连续连接、低纹理房间的跨观察完整物理表面。新的局部hair改善不替代这些任务。没有新的T3/T4，T2仍失败；完整joint发布未通过。

成熟技术的使用边界：本轮使用现有固定版本OpenMVS独立进程与原gsplat，AGPL工具许可仍适用，独立进程不免除分发义务；没有拷贝外部代码进应用。FLAME Open与head-local SH1保留，没有普通版替换、生成皮肤/纹理、屏幕贴片或后处理锐化。

## 接下来唯一优先动作

不再延长同一短窗训练或放宽hair/room门禁。下一次应把**同一恢复F合同下的跨短窗真实表面一致性**做成可复用入口：多个有证据的观察窗分别建立外表面，保留深度/法线与视图来源，检查同一head-local物理区域的冲突、不确定性和遮挡，再决定一个局部连续替换事务。先检查0035/0130/0145等退化是否为新深度结构错位、固定F偏差或未知表面的误替换；未经核对不把多个云直接叠加。

房间另需覆盖旧宽核真实背景职责的多个物理表面，不靠保留它的错误遮脸像素。颈肩另需独立身体运动和有效颈皮肤观测，不能用面部姿态替代。

这是一项具体后续研发方向，不是本轮已完成能力。本轮所有失败候选保持隔离，原应用、作品和有效功能不受影响。

## 交付文件与本地代码提交

- 颈部数学/场/训练：reconstruction_surface_continuity.py、run_continuous_surface_repair.py、test_reconstruction_surface_continuity.py。
- 原像素真实轨迹/上身/共享面部：run_continuous_observed_tracks.py、run_observed_body_motion_repair.py、run_measured_head_surface_repair.py、test_measured_head_surface_repair.py、audit_measured_head_local.py。
- 实际MVS/native合同/头发表面：prepare_measured_hair_mvs.py、scripts/Invoke-FiniteMeasuredMVS.ps1、build_native_head_surface.py、run_native_head_surface_repair.py。
- 背景受限事务：reconstruction_room_surface_repair.py、run_complete_room_surface_repair.py、test_reconstruction_room_surface_repair.py。
- 证据：audit_continuous_repair_results.py；本目录report.md、commands.md、system.json、summary.json、protection.json和测试日志。

本地独立提交：
- `1f572d89cc66687fa532fcc8fbd9b76cd0d12ea2`：颈部连续协方差及研究控制。
- `27416eea41b6fdcd74159390bf10289ba814fc68`：真实背景表面事务及导入内参门禁。
- `869fc7dd5cdae78e76dc9cad4abdf3e722ec7aa6`：真实测量和固定相机MVS合同。
- `edf49439b037a6f7fe3633063d5e179a16c39db5`：实际头发表面研究训练。
- `3b54780a54c00f4babdfb1b9c83159a464f1be29`：材料权重导数修正。

没有提交既有build_continuity_candidates.py修改、observed-coverage未提交文件或任何私人图像、模型、视频。最终证据另单独提交，提交本身不等于发布模型。
