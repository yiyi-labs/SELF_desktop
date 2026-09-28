# SELF 阶段2A：完整候选收集与预算分配研究记录

日期：2026-09-28。范围仅为已批准的阶段2A。**候选准备与五视角表面支持检查已完成；CUDA 高斯 A/B 绘制尚未完成，不能称本轮全部通过。**

## 本轮结论

同一地图、59 个训练观察、相机、mask、取色及过滤条件下，完整枚举找到了旧 prepared 未记录的 **292 个可用三角假设**；五个开发视角的表面支持仅增加 **0.0373—0.2100 个百分点**。候选池支持仍只有 **4.4545%—13.8619%**，远没有补齐房间。

新分配保留几乎全部候选池的投影支持：四帧没有损失，第130帧少1像素。因此，**旧准备遗漏确实存在，但不是当前大片背景缺失的主要剩余解释；继续重复分配不能解决候选池自身很小的问题。** 这是分支B的支持域证据，并非最终画质结论。U、A、q_room、RGB及共同遮挡尚待原 GPU 路径验证，不能引用阶段0旧结果填本轮空格。

没有训练、优化器、反向传播、density、相机重建、MVS、PLY导出、发布、平板回传或部署。E1仍为研究相机；面部、头发、镜框、衣物与joint的独立缺口均未因此修复。v3仍应表述为face未训练、没有density、joint是占位入口，不能宣称完整方案已实施并失败。

## 保存位置、提交和范围

- P：`D:/STUDY/College/mine/olay`，原工作区HEAD `f68587bb34f8970d21bda9231e15b2536a33df97`，内容和状态均保持。
- W：`C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay`，分支 `codex/reconstruction-v3-audit-20260928`。
- 阶段0检查点：`933f664cd700b7845eca14fe1a5671228366d1f1`，parent `27c9810bf0746d8e4382eb218e89276954767d7d`。只提交审计适配器、其测试、阶段0报告三项。
- 本轮提交另行保存以下五项：`backend/reconstruction_scene.py`（仅新增显式研究函数）、`backend/prepare_surface_candidate_audit.py`、`backend/test_surface_candidate_budget.py`、`backend/test_surface_replay_resume.py`、本报告。提交号见本目录对应本地Git历史及私有审计目录的提交回执，不为写入自引用hash执行amend。
- 既有未跟踪 `reconstruction-v3-targeted-audit-20260928/report.md` 不随本轮提交；私人图像、NPZ、模型、密钥、签名均不入Git。
- 实际候选池和唯一新prepared：`W/backend/.sources/reconstruction-stage2a-20260928-b`。第一次启动的 `-a` 在CUDA检查时停止，**没有开始真实枚举**；原失败记录保留。`-b` 仅做了一次完整枚举、一次分配。

[准备冻结清单](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage2a-20260928-b/preparation-summary.json)；[实际配置](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage2a-20260928-b/config.json)；[保护核验](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage2a-20260928-b/review/preservation-check.json)。

## 固定合同

原片SHA `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`，仅使用保留研究副本。

原prepared位于 `P/backend/.sources/integrated-components-v2-20260928-e`：

- 原 `static_surface_seeds.npz`：`22296697a46475e5099a5fe2430852422876150cfc9aaccc3e0b6f124b11ad35`。
- 原 `local_geometry.npz`：`fae308b496a50dad7c67c58ee2767d20ea9c9957f2c8dcbd811bb337d44f07e0`。
- 新prepared：`681b71264c169cb1892d3dcdc106248a77091d6513288e50e5fe07b027801d81`。
- 所有旧地图bin、RGB、标签、源码快照和当前依赖均按实际输入保存SHA。pycolmap 4.2.0；gsplat 1.5.3；Torch 2.8.0+cu128。没有更新依赖。
- 59个训练观察按imageName关联旧C/K；逐项核验C与原map一致。2000原锚点的XYZ/RGB/support/source_kind/source_id/triangle_sources逐项位级相同。
- 图像保持原去畸变1080×1920，旧remap的uint8经PNG保存后再/255，核验无新增颜色处理。开发检查复用原half合同：RGB AREA、mask NEAREST、K前两行×0.5、540×960。
- 分配前没有读取五张开发RGB/mask，记录于新preparation.json。开发帧15/35/115/130/145已经用于方法选择，不称最终盲测。
- A应为旧prepared经**原initialize**得到的未训练room；B为新prepared经同一initialize得到的未训练room。恢复入口会要求A状态SHA与阶段0 `v3_initial` 完全相同。**本次GPU未恢复，尚未生成或绘制这两个初值；未拿360步或v2终态替代A。**

## 最小实现及过滤粒度

旧 `supported_static_surfaces` 的AST和合成输出均保持原样，旧调用/生产worker未接新路径。新 `collect_supported_surface_pool` 与 `allocate_surface_pool` 只由独立prepare-only入口显式调用。

1. 完整遍历全部59视角，预算不参与枚举。三角身份为地图/准备namespace、source_kind=1、排序后三个原始POINT3D_ID；原有向顶点、法线和每次观察单独记录。相反winding保留证据，S按原双面合同投影；不按空间接近合并不同ID。
2. 原三角过滤不变：边长7—80px、相对深度跨度≤0.06、退化法线检查、绝对normal-ray≥0.25。内部采样divisions仍为`min(10,max(2,int(edge/9)))`。三角日志是**首次拒绝计数**。
3. 同一三角不同有理重心位置生成稳定样点身份；每个原观察的实际采样域分别保留。每个样点仍投影至全部59观察，执行原边界、room mask、3×3模糊RGB、颜色L1<0.10、支持≥3、冲突≤1检查。不能因为三角或别的样点通过而放行。逐点失败可多标签，不相加当缺失面积。
4. 多个有效颜色来源仍按原规则独立计算，确定性选择最多支持/最少冲突/稳定观察名，保存其他有效来源及支持/冲突/unknown/mask排除bitset。没有肤色补齐或生成颜色。
5. 分配只用训练图32px粗格/4px细格和锚点间距构成的世界格。分数为`4×新增粗格+新增细格+4×新增世界格`，重复覆盖边际增益为零。先尝试保留旧有效表面域，再lazy greedy。达到无新增格覆盖时停止，不重复填数。**格上无新增不代表真实高斯光学重叠无价值**，这个限制必须在后续U/A检查中检验。
6. 通用预算从实际anchors数量扣减。本实验2000只是历史合同断言，非未来所有视频的常量。59视角证据使用uint64；超过64时显式报错，尚不支持多字证据，不静默截断。
7. 原anchor中的29个重复XYZ保留。新采样避免重复占用相同float32 XYZ预算，候选池本身不删除或融合几何。旧5249个重复XYZ及旧sidecar都没有原地处理。

完整候选池与最终选点分别存放。新16项等长字段包括point_id、source_kind/id、triangle_sources、surface_id、canonical_point_ids、重心整数、采样观察、四类证据bitset和证据范围。锚点的负证据未重新推断，evidence_scope明确区别于样点全视图投影。

## 实际候选数量与预算

| 阶段 | 数量 |
|---|---:|
| 处理训练视角 | 59/59 |
| 原始三角提议 | 31531 |
| 首拒：边长 / 深度跨度 / 法线 / 退化 / 没有内部样点 | 8970 / 3176 / 4792 / 0 / 9784 |
| 通过几何提议 / 唯一几何三角 | 4809 / 3168 |
| 至少一个合法样点的唯一三角 | 2951 |
| 逐观察样点证据 / 接受 / 拒绝 | 28581 / 22702 / 5879 |
| 合法唯一候选样点 | 16661 |
| 旧三角 / 完整池新增三角 | 2659 / 292 |
| 选中三角 / 选中新增三角 | 2871 / 258 |
| 旧三角未被选中 / 总池未选三角 | 46 / 80 |
| 保留原锚点 / 选中表面样点 / 总数 | 2000 / 10276 / 12276 |
| 未使用预算 / 未选候选样点 | 9744 / 6385 |
| 新总唯一XYZ / 新样点自身重复XYZ | 12247 / 0 |

几何提议同身份重复率34.12%，接受样点提议同身份重复率26.61%。5879个拒绝样点均有conflict>1，其中10个也有votes<3，两种标签重叠。没有改掉冲突规则；颜色不一致是否含反光、姿态或遮挡误判，本轮不能据此直接决定。

旧2659个三角全部存在于合法候选池。46个旧域未获独立样点并非原证据消失，而是格覆盖重叠后无新增分数；对应的S损失只有第130帧1像素，但实际足迹/重叠仍待GPU核验。**没有把12276点写成“相同实际点数”比较：本轮相同的是22020预算上限。**

每视角首次新增/重复三角、样点接受/拒绝、首个合法证据，以及全部未选点可由 [候选汇总](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage2a-20260928-b/candidate-pool/summary.json)、[表面证据](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage2a-20260928-b/candidate-pool/surfaces.jsonl)、[完整合法点池](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage2a-20260928-b/candidate-pool/legal-samples.jsonl)、[选点清单](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage2a-20260928-b/prepared/allocation.json) 复核。未选=完整池pointId减选中pointId，不丢失未选记录。

## 五视角S与合法样点投影

| 开发帧 | S_old | S_pool | S_selected | 候选新增像素 | 预算丢失像素 |
|---|---:|---:|---:|---:|---:|
| frame_0015.png | 7.6960% | 7.7397% | 7.7397% | 135 | 0 |
| frame_0035.png | 7.3643% | 7.4016% | 7.4016% | 121 | 0 |
| frame_0115.png | 4.3921% | 4.4545% | 4.4545% | 186 | 0 |
| frame_0130.png | 13.6518% | 13.8619% | 13.8615% | 621 | 1 |
| frame_0145.png | 10.0965% | 10.2010% | 10.2010% | 310 | 0 |

以上分母是当帧固定room_visible mask，raw/visible分别保存。S是有记录三角的双面透视投影与z-buffer上界；样点合法不代表整个三角内部均有真实连续表面。另存L：合法样点投影中心像素，**L不是U，不是连续面积或累计alpha**。

池L中心像素比例为2.4486%、2.3816%、1.2029%、3.1638%、2.8525%；选中L为2.1356%、2.0853%、1.0063%、2.7045%、2.4037%。不凭整三角S几乎不变就断言稀疏选点的覆盖已成功。

三张固定结构对照（从左到右为原片/S_old/S_pool/S_selected/新增绿与损失橙/合法中心像素）：

![第35帧表面支持](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage2a-20260928-b/cpu-support-resumed/frame_0035/support-comparison.png)

![第115帧表面支持](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage2a-20260928-b/cpu-support-resumed/frame_0115/support-comparison.png)

![第130帧表面支持](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage2a-20260928-b/cpu-support-resumed/frame_0130/support-comparison.png)

可见新增仍沿柜门局部结构和左下边缘，大片门板、天花板没有被补齐。不是一整面新增墙。第15/35/115/145帧最大新增比例在3×3的左上区，第130帧在左下区；完整分区见 [冻结结果补审计](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage2a-20260928-b/review/frozen-analysis.json)。

## 结构与遮挡风险，不能以S增大放行

- S_pool raw与人物mask相交像素依次从998/1952/45/1524/1900变成1052/2014/45/1540/1925；与unknown相交从735/961/346/551/545变成752/964/346/581/579。背景在人物后方也会有2D重叠，**这些是风险定位，不是穿人深度证据**；不能说结构风险已排除。
- 新旧共同射线中，候选最近深度比旧S靠前超过旧深度1%的像素依次173/111/27/207/159。共享射线绝对深度差中位数均0，P99约0.069—0.114世界单位；最大约0.383—0.543。它可能来自重叠三角的不同深度假设，没有独立深度不能判断哪个正确。
- 所有候选仍满足原80px及6%跨度检查，但这两个阈值并不证明没有跨柜门/墙角。当前只是有限三角假设；本轮没有引入新几何估计，也没有放大三角、平面外推或填背景。
- S_pool→S_selected几乎不损失，不能替代S_selected→U；新的近邻分布会通过**同一个原初始化公式**自然改变scale/anchor法线，必须等真实A/B检查，而不能先定性为改善。

## 显卡阻塞、失败记录与复现

Windows本轮把RTX5070标为Present=false / CM_PROB_PHANTOM；WSL Torch返回cudaAvailable=false、deviceCount=0，NVML不能初始化。设备证据见 [主机显卡状态](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage2a-20260928-b/review/gpu-host.json)。用户正在自行恢复独显，本轮没有改显卡模式、驱动或重启。

因此当前 **U、实际累计A、q_room、float RGB、固定人物共同合成均未执行本轮A/B**。没有用CPU画三角或旧图冒充CUDA高斯绘制。显卡不可用不是8GB显存耗尽证据。

准备枚举耗时8.667秒，整个准备至冻结72.209秒（含读取、模型/输入核对、分配、保存和hash）；峰值进程RSS约3.73GiB。预先设定枚举1200秒/10GiB、分配600秒，未触顶。未记录分配单独计时，不猜测。GPU绘制耗时/显存未验证。

第一次CPU支持报告读取未创建的`reference`字段，已保留原failure与部分输出。只修新审计适配器，CPU支持明确不合成人物，reference为null；从已冻结prepared恢复至`cpu-support-resumed`，没有重做候选/分配。准备时执行的源码快照不覆盖；恢复验证除报告适配器外所有冻结源码和输入hash不变，适配器旧快照与当前版本分别留痕。后续CUDA路径由原initialize设定真实参考状态。

在W/backend的现有Ubuntu-22.04环境，原单轮命令：

```sh
PYTHONDONTWRITEBYTECODE=1 CUDA_HOME=/usr/local/cuda-12.8 TORCH_CUDA_ARCH_LIST=12.0 MAX_JOBS=2 /opt/self-reconstruction/venv/bin/python -B prepare_surface_candidate_audit.py \
  --prepared /mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e \
  --run .sources/reconstruction-v3-20260928-a \
  --stage0 .sources/reconstruction-stage0-20260928-fiveviews \
  --output .sources/reconstruction-stage2a-20260928-b
```

这个output已经存在，**不能再次运行准备命令覆盖或重新分配**。CPU支持已用同参数加`--resume-support`完成。独显恢复后，只以同参数加`--resume-replay`进入尚未创建的`gaussian-replay`，验证冻结输入/输出、恢复原初值、同classic模式五视角room-only及固定人物合成。此恢复入口没有候选枚举/分配调用，也没有训练入口。

11项合同测试均通过（8项候选合同+3项恢复防篡改），日志 [合同测试](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/reconstruction-stage2a-20260928-b/review/contracts.txt)：

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/self-reconstruction/venv/bin/python -B -m unittest test_surface_candidate_budget test_surface_replay_resume -v
```

原现场1639项、私有历史242+299项SHA核验无差异；P status SHA仍为`26338b0026321936b864a2f5aa875c9b6ea5e9f4a6c22b2625eeff0540d8a883`。Git仍不包含私人资产，本地存在不等于独立备份。

## 下一项唯一优先动作与停止

**当前只续完已批准的CUDA A/B，等待显卡恢复，不重跑准备。** 原资产和本轮候选都不回传、不替换作品。

若A/B没有发现必须先处理的落地退化，下一项待批准修复方向是“候选生成之前的支持/过滤缺口”，不是继续改预算或全局提高opacity。有限诊断最多三个静态窗口、每窗三个现有训练观察：

1. 上部柜门与门缝：frame_0035作开发定位，训练候选frame_0025/0026/0040。
2. 左侧下方大门板：frame_0130作开发定位，训练候选frame_0133/0134/0136。
3. 天花板与柜体顶部交界：frame_0115作开发定位，训练候选frame_0111/0112/0118。

窗口仅是下一轮建议；先确认可见静态范围，再分别核对稀疏锚、Delaunay提议、首次拒绝及逐点冲突。总计最多9个局部观察，不全局重匹配，不自动放宽阈值、引入平面、MVS或要求重拍。**本轮未执行这些诊断或修复。**

当前状态：准备实现及支持域子能力通过；真实高斯A/B未验证；背景画质、结构风险及完整场景发布未通过。停止于此，不进入阶段2B/2C。
