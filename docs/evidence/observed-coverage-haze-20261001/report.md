# SELF：白雾、清晰度不均与表面覆盖对照

2026-10-01。隔离后端研究；没有部署、回传、切生产或覆盖作品。**白雾原因进一步明确，但本轮没有得到完整自然、可交付的新模型。** 两个实际训练候选均拒绝。原 E1—E5 不变。

## 直接结论

1. 白雾的一部分确实来自旧 room 表示，而不是界面上开启了 fog。本轮保持全部人物参数不变，以新的有限表面替换候选中的旧 room：0010 脸区 RGB L1 从 0.096114 降到 0.022939，旧 room 在脸区的贡献约 0.2727，新表示接近零。**这是解除污染，不是面部几何或细节被重新训练好了。**
2. 代价是背景内容缺失：0010 room RGB L1 从 0.025749 恶化到 0.279459，room 平均贡献从 0.92045 降到 0.53633。不能以脸变清楚就采用这份候选，不能用黑洞代替真实环境。
3. “薄弱区域多分点”有作用，但不是主问题的完整解法。同 22,000 点预算、同初值公式、同 360 次图像反传，受保护的多视角分配带来小幅改善，没有补齐房间。未经保护的首版分配反而损伤一个训练视角，已保留为失败提议。
4. 实际绘制全部 174,402 个现存候选，仍有明显房间缺口。预算不是唯一瓶颈；现有候选几何、筛选与跨窗覆盖本身不足。该池来自相机条件深度的兼容检查，不是完整房间测量真值，更不能推断原视频没有拍到这些地方。
5. 新表面的同一 PLY 在 gsplat/PlayCanvas 上差异明显小于旧病态表示：全幅 RGB MAE 0.007426，face 0.006533，room 0.006200。但两边都显示了不完整背景。**显示接近与重建正确是两件事。**

这次最重要的研发结论是：停止把“继续堆在旧雾核上”或“完全换成当前有孔洞的深度点集”当作解决方案。需要能够接替真实背景内容的连续表面，同时改进人像的运动对齐；局部颜色优化不能代替它们。

## 身份与保护

- W：`C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay`，开始 HEAD `cdebe50144f1361d40e5f25d91c696ddd24782f5`，分支 `codex/reconstruction-v3-audit-20260928`。
- P：`D:/STUDY/College/mine/olay`，HEAD `3dad0cd5651824cc06d9e88d61aabdd2642c0b30`。原有修改及未跟踪文件保留，本轮没有写 P。
- 冻结 R0：`W/backend/.sources/fullframe-surface-patch-20260929-b/R0-frozen.pt`，SHA256 `2468edc379f8b76eac97fccfbf9e9a4c775f980102b95283ee15b2dc4cee7cb8`，结束重新计算相同。
- 视频 capture-1790410633104.mp4，SHA256 `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。
- Prepared `P/backend/.sources/integrated-components-v2-20260928-e`；preparation SHA256 `e67d4dce02f9874e0befe15486532f80458f8a62a23221324fcc5abefc2e5301`。
- 已缓存深度 manifest SHA256 `11391f4d5f55cf1d1d1fa5bd7ba314b006879affa0783be5dc5d8d59cdaeba23`；没有重推网络或更换模型。

本轮输入是可恢复的 R0。此前颈肩、头发等失败候选没有偷偷成为新基线；因此本轮画面中的旧身体仍很差，不是本轮破坏了已经放行的衣物。没有读取平板当前作品身份，不能将研究图当作平板当前显示的截图。

## 为什么会雾、厚、局部忽清忽糊

已证实：旧宽 room 核在人物前产生了实际透明合成贡献；同一旧资产在两端的半径、尾部和投影近似差异显著，历史 COMPACT/LARGE 与 minPixelSize 单因素没有修复。没有启用 fog 或后处理。本轮不再重复这些配置试验，也没有调整曝光、gamma、对比度或补灯。

尚未全部定量分离：共有中心深度排序近似、离轴投影与核尾截断的各自责任。StopThePop 和 3DGUT 的论文解释了相应近似可能产生的视角不一致，但不能据此将本项目全部白雾归因于其中一个公式。

人物本身的问题仍独立存在：前一轮真实纹理第三观察误差仍约 4.4px，而期待恢复的细纹往往更小；对不齐的观察被平均成颜色后会软。旧头发壳、镜框深度、整段上身运动和颈接触仍未成立。这里不能用更强锐化、生成发丝或高亮来“制造立体”。本轮不宣称已经修复这些部件。

清晰度不均不仅是点密度不均，还包括不同位置的视差、遮挡、运动解释和有效原生像素不同。已有完整 room RGB 监督和历史 density 都保留为事实，不再错误地说“以前根本没有全图训练/增密”。

## 本轮实际代码与有限实验

新增可复用 `reconstruction_observed_coverage.py`：投影实际三维协方差到原生相机，建立 8px 采样格的候选足迹；包含中心在画布外但足迹进入画布的点，记录过宽点，不修改其参数。它只用于点预算，**不是真实累计 alpha 或首表面真值**。

同一候选池固定 22,000 点。首版递减收益分配在 0025 的潜在支持从约 0.63 退化到 0.36，未进入训练。新增受保护交换：从原分配出发，每次等数换点，每个已有采样位置保留至少 min(旧潜在质量,0.75)，每次交换必须增加有限目标；5000 次交换后，原支持格损失为 0。全部规则按相机、mask、协方差与来源工作，不硬编码脸、衣服图案或视频帧号。

训练新入口 `run_observed_room_recovery.py`：

- A 为原 UID 均匀选点，B 为有保护的覆盖分配；均源于同一 174,402 点池，候选点自身 means/quats/scales/alpha/SH 初值不被分配算法改写。
- 同 17 个真实训练观察、固定 K/C/F、原生 1080×1920、完整排序合成后计算损失。没有换小 viewport；所有人物部件共同参与。
- 人物完全冻结，room 候选替换旧 room，仅存在于独立研究对象。没有把旧雾片叠回去掩饰孔洞。
- 两组均 360 步 Adam，同图像序列，实际更新 SH、alpha、scale；means/quats 固定，scale 保持初始值的 0.8—1.25 倍，未新增 density。本轮不是新的全组件 joint。
- 全部有效 room 像素持续进入监督；加入固定 96px 区域的均衡项，避免只改善容易区域。人物的真实像素监督仍在，不蒸馏旧雾图。
- 每视角检查固定 RGB、结构、贡献、覆盖和弱区域误差分位数，缺失像素计入。alpha<0.8 只是代理指标，不解释为没有几何。
- 保存真实 init/mid/final/restored、Adam、RNG、采样器、UID、源点、绑定、配置和执行源码；没有改历史检查点。

| 观察 | 原 R0 room L1 | A 终态 | B 终态 | B room 平均贡献 |
|---|---:|---:|---:|---:|
| 0005 train | — | 0.393400 | 0.391185 | 0.38071 |
| 0010 train | 0.025749 | 0.280887 | 0.279459 | 0.53633 |
| 0015 dev | 0.045473 | 0.177380 | 0.177007 | 0.67307 |
| 0025 train | — | 0.130461 | 0.126939 | 0.70355 |
| 0035 dev | 0.036617 | 0.120558 | 0.117819 | 0.71769 |
| 0115 dev | 0.045137 | 0.349582 | 0.347700 | 0.46729 |
| 0130 dev | 0.042746 | 0.160865 | 0.158661 | 0.63719 |
| 0145 dev | 0.037479 | 0.139131 | 0.134488 | 0.72574 |

两组均有 183 条逐视角/部位/指标退化记录，不是 183 个独立场景。B 对 A 有小幅局部改善，**A/B 都远差于完整背景要求**。没有为了表格好看放宽发布标准。

![原片、R0、均匀表面、受保护分配](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/observed-coverage-haze-20261001-b/evidence/frame_0010.png-comparison.png)

完整候选池的冻结重放没有 optimizer/训练：174,402 点在六个固定诊断视角仍有 21.5%—68.2% 的 room 像素贡献小于 0.8。画面也实际有大片空缺，而不只是阈值统计。它不是“给产品盲目翻倍点数”的建议，只是区分分配与支持缺口的一次有界反事实。

## 显示、资源与回归

B 的唯一参考 0111 PLY SHA256：`f06b2abeca3a6ae0abac53437a5934da483190dbee7abb4084c7897e6d1dc67a`，34318 点。同一资产/相机/原生尺寸在 gsplat1.5.3 与实际 PlayCanvas2.22.4 Chrome SwiftShader 绘制；没有切格式、关 gamma 或调曝光。全幅 RGB MAE 0.007426、alpha MAE 0.010070；face 0.006533、room 0.006200。历史相同 R0/0111 的全幅 MAE 约 0.17598，但本次是完整 room 表示变更，不将差值包装成单一核责任比例。

![同一失败候选的原片、gsplat、PlayCanvas](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/observed-coverage-haze-20261001-b/renderer-comparison/source-gsplat-playcanvas.png)

同一 PLY 的连续绕看保存在 `fixed-ply-orbit`。来自 gsplat，非 PlayCanvas/鸿蒙录像；1080×1920 绘制、540×960 编码，viewer 相对角不是测量的人脸观察角。**本轮未测鸿蒙、手机、编辑兼容或新视频。**

| 项目 | 实际耗时 | Torch allocated/reserved 峰值 |
|---|---:|---:|
| A 360步训练循环 | 36.34s | 760.37 / 1190 MiB |
| A 含载入、全幅初/终评价等 | 178.14s | 同上 |
| B 360步训练循环 | 35.45s | 760.83 / 1190 MiB |
| B 含载入、全幅初/终评价等 | 174.70s | 同上 |
| 全174402点冻结重放 | 31.80s | 550.32 / 714 MiB |

RTX5070 Laptop 本轮 CUDA 正常，无 OOM。上述不是系统总显存或完整视频到模型耗时，不能宣称完整 2—3 分钟，也没有证据把本次质量问题归罪于 8GB。

41项本轮及既有合同回归通过；A/B 的 baseline 字段逐项相同，init 与 restored 的模型、Adam、绑定、RNG、采样器、策略、trainable 全部一致。模型图像失败与代码合同通过分别记录。首次入口 import 适配错误发生在创建 run 前，随后改为实际已有导出函数；没有虚构训练。后续只补 sourceHash/reference 元数据与缓存身份检查，未重跑训练或把最终代码冒充当次执行源码。

## 成熟方法应该怎样借鉴，怎样避免冲突

| 主问题 | 已核对的官方方案 | 在 SELF 的合适用途与限制 |
|---|---|---|
| 面部/发际线/颈肩对齐 | [VHAP](https://github.com/ShenhanQian/VHAP) | 借鉴区域外观约束的连续光度跟踪，弥补少量关键点/纹理轨迹。不是直接再放开所有 F；参考 F、K、身份和尺度需要固定。官方 CC-BY-NC-SA 与模型许可须独立核对，不作为现成商业组件。 |
| 脸和头发的表达容量 | [FlashAvatar 官方代码](https://github.com/USTC3DV/FlashAvatar-code)、[论文项目](https://ustc3dv.github.io/FlashAvatar/) | 连续 UV 表面覆盖＋表达条件的受限空间偏移，比将所有头发压在皮肤壳上更合适。官方代码顶层 MIT 不覆盖全部依赖/模型许可。论文性能是 RTX3090/512分辨率条件，不保证本机8GB或原生全场耗时。 |
| 房间连续表面/遮挡 | [PGSR](https://github.com/zju3dv/PGSR)、[2DGS](https://github.com/hbb1/2d-gaussian-splatting)、[GOF](https://niujinshuchong.github.io/gaussian-opacity-fields/) | 借鉴深度、法线和多视图连续表面约束。它们有特定光栅化/深度定义，不能把 gsplat ED 称作相同表面深度，也不能直接将特殊模型丢进现有 PLY 查看器。 |
| 头、颈、衣物运动连贯 | [HUGS](https://machinelearning.apple.com/research/hugs)、[Shape of Motion](https://shape-of-motion.github.io/) | 人物与静态环境采用不同运动模型，但最终共同排序合成。头 F、身体 B 和颈部接触必须跨窗一致；不能把短窗外 B=I 当成熟方案。HUGS 官方约30分钟不能移用为 SELF 2分钟承诺。 |
| 缩放/转动的显示稳定 | [Mip-Splatting](https://github.com/autonomousvision/mip-splatting)、[StopThePop](https://github.com/r4dl/StopThePop)、[3DGUT](https://research.nvidia.com/labs/toronto-ai/3DGUT/) | 分别处理采样/滤波、排序、投影。训练与终端要成对匹配，不能只改训练器。先修病态宽核，不通过取消查看器上限复制灰雾。3DGUT 的滚动快门能力也需要实际运动/读出模型，不能凭“手抖”直接启用。 |

以上是技术思想与接口取舍，不表示已整套移植。本轮没有下载/安装新的第三方库、权重或许可不明的源码。没有替换 gsplat1.5.3、FLAME Open、PlayCanvas2.22.4 或现有 PLY/编辑索引合同。

## 后续最值得推进的路线

总体采用“可观察的连续表面＋受限人物运动＋标准高斯外观”，各模块交接同一时间戳/imageName、K、F/C/B、单位尺度和参考时刻；共同前向保持实际遮挡。不是几个模型各自做好以后靠羽化拼图。

1. **首先让真正连续表面接替雾片承担的内容。** 从现有原片/可信相机出发，跨预测窗对齐深度与法线，并用真实多视图重新投影检验。白墙/柜门可建立有边界、有多视图锚的有限平面；拐角、柜体凸出物分开。低纹理不再被等同于“不存在”，但没有依据的区域不能无限外推。用投影覆盖与结构证明新表面接得住内容，再事务退役旧宽核。这是下一项最优先代码工作；继续改点预算已不是主攻方向。
2. **人脸分支同步转向密集的连续光度对齐。** 不再主要依赖二十条稀疏轨迹/一个小 normal 场。先在短窗用整张脸及稳定发际线/耳侧进行受限对齐，再连接短窗；表情、反光、模糊与遮挡分开建模。几何可靠后才用原生像素恢复小结构。维持同身份、参考姿态和尺度，避免姿态、几何、颜色相互补偿。
3. **颈肩是运动与接触问题，头发是外表面体积问题。** 颈皮肤连续，衣领是另一物理层；身体 B 与头 F 分开且全片连贯。头发不再长期保留旧壳叠新点，真实外轮廓与发际线深度通过后替换；镜框独立线结构，不把镜片反光变实体。没有可靠观测的区域明确保留不确定性。
4. **局部精度与全局完整一起验收。** 保留原固定开发/回归视角，逐部位检查真实边缘、视差、最弱区域、遮挡和双端差；不能只看平均 RGB。每次候选都固定同一参考 PLY，逐端加载和连续绕看，不按角度换资产。成熟工具在公开数据上的效果不构成本项目自然度或跨用户泛化保证。

## 复现与证据位置

研究输出：

- `W/backend/.sources/observed-coverage-haze-20261001-a`：首次无保护提议、原均匀选择与 A 训练。
- `W/backend/.sources/observed-coverage-haze-20261001-b`：保护分配、B 训练、完整池绘制、实际 PlayCanvas、比较、状态恢复和同 PLY 绕看。
- `evidence/state-audit.json`、`evidence/summary.json`：完整恢复与逐视角结果；`selection/protected-exchanges.json` 保存具体交换身份。

WSL Ubuntu-22.04，W/backend，`PYTHONDONTWRITEBYTECODE=1 /opt/self-reconstruction/venv/bin/python -B`：

```text
build_observed_room_coverage.py --prepared <prepared> --depth <frozen-depth> --out <new-selection> --budget 22000 [--pool-cache <existing-uniform>]
run_observed_room_recovery.py --stage <recorded-stage.json> --surface <uniform-or-coverage> --out <new-run> --steps 360
audit_observed_room_pool.py --stage <recorded-stage.json> --pool <supported-pool.npz> --out <new-replay>
audit_observed_coverage_results.py --uniform <A-run> --coverage <B-run> --prepared <prepared> --out <new-evidence>
```

实际 A/B 的执行源码在各自 algorithm-source；当前交付入口包含后来补全的非数值元数据，不能声称历史输出自动已有该字段。所有 out 要求独立目录；没有覆盖 run-id。Git 保存代码与报告，私人模型/影像/检查点保留在本机忽略目录，没有额外独立备份或上传。

**可保留：覆盖保护和逐弱区域评价能力、完整恢复与双端证据。拒绝：本轮全部模型候选。未完成：真实面部细节提升、真实发型/镜架、整段颈肩衣物运动、完整房间、真机与多用户验收。**
