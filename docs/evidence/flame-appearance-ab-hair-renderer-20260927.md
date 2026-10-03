# SELF 本人外观：FLAME A/B、头发与显示合同（2026-09-27）

本记录承接现有 E1—E5 和 [局部外观训练记录](flame-local-appearance-optimization-20260927.md)，只记录当前仓库内真实运行的离线研究结果。没有改鸿蒙应用、签名、旧作品、USB/HDC 协议、PlayCanvas 查看代码、上脸编辑和故事逻辑；没有向平板回传本轮候选。黑底头部不是完整人像重建。**当前候选均不可发布。**

## 1. 固定输入与 A/B 协议

| 项目 | Open A | 普通版 B |
| --- | --- | --- |
| 模型文件 | `backend/.sources/third_party/flame2023_open/flame2023_Open.pkl` | `backend/.sources/third_party/flame2023_standard/flame2023.pkl` |
| 模型 SHA-256 | `e75a0990728ba038c7da2a420ae4396f7ddd7781366c13026066c5b24f127623` | `8fb1af0db1abb51053ead8fd1f2624a63d01c9602f4a4fb4ea23bd2c82017fa0` |
| 训练候选点 | 皮肤 7939、近面细节 859、头发 2917 | 皮肤 7818、近面细节 890、头发 2928 |
| 真实更新 | 900 步，14 帧轮流，未分裂 | 900 步，14 帧轮流，未分裂 |
| CUDA 峰值 allocated | 254.37 MiB | 254.27 MiB |
| 记录的全段耗时 | 73.02 s（重启后首次冷启动） | 20.88 s（热缓存） |

两版均使用同一 `capture-1790410633104.mp4` 对应私有原片 `backend/.sources/quality-geometry-20260926-temp/capture.mp4`，SHA-256 `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。训练帧为 `5,12,25,40,50,60,70,80,90,100,110,120,136,150`；开发留出帧为 `15,35,55,75,95,115,130,145`。解码后直立 1080×1920，原生像素裁剪，不镜像、不缩放；同一估计 K（fx=fy=1181.055，cx=540，cy=960），裁剪仅平移主点，畸变仍未知。两版共用来源像素标注、训练器、足迹系数 1.0、随机种子 260927、损失及参数开放顺序；模型及相应几何拟合参数按版本区别加载。训练器在 A/B 时的 SHA-256 为 `4932166638293fb5cdf81366ba46694bca101b9ca37fa9548a54fc26b54d5e17`。`compare_flame_appearance_ab.py` 核对两份审计的源、代码哈希、帧、K、步数、足迹、阶段和无分裂条件；已实际通过。留出颜色未参与初始化或梯度，但这 8 帧已参与方案选择，**不是完全独立的最终审计集**。

WSL GPU 恢复后的实际命令：

```bash
source /opt/self-reconstruction/venv/bin/activate
cd /mnt/d/STUDY/College/mine/olay/backend
python train_flame_local_appearance.py .sources/quality-geometry-20260926-temp --stage subset --steps 900 --footprint-factor 1.00 --variant open --run-id ab-20260927
python train_flame_local_appearance.py .sources/quality-geometry-20260926-temp --stage subset --steps 900 --footprint-factor 1.00 --variant standard --run-id ab-20260927
python compare_flame_appearance_ab.py .sources/quality-geometry-20260926-temp --run-id ab-20260927
```

两份隔离训练及原片/初始化/优化后三联图分别保存在私有 `flame_open_e2_20260927/private-optimized-subset-900-footprint-1.00-ab-20260927/`、`flame_standard_e2_20260927/private-optimized-subset-900-footprint-1.00-ab-20260927/`。完整逐帧和参数保存在 `backend/.sources/quality-geometry-20260926-temp/flame-appearance-ab-ab-20260927.audit.json`。上述目录已存在且脚本拒绝覆盖同名 run-id。

## 2. A/B 实际结果与画面结论

固定 ROI RGB L1 包含缺失像素，越低越好：

| 开发留出帧 | Open 初始→900步 | 普通版初始→900步 |
| ---: | ---: | ---: |
| 15 | 0.06905→0.03530 | 0.06597→0.03474 |
| 35 | 0.06055→0.03327 | 0.05886→0.03342 |
| 55 | 0.06238→0.05714 | 0.06055→0.05707 |
| 75 | 0.06745→0.04233 | 0.06450→0.04347 |
| 95 | 0.05646→0.03615 | 0.05339→0.03664 |
| 115 | 0.07215→0.04809 | 0.06966→0.04653 |
| 130 | 0.05789→0.03883 | 0.05767→0.03864 |
| 145 | 0.06914→0.03893 | 0.06988→0.04321 |
| **均值** | **0.06438→0.04125** | **0.06256→0.04172** |

35/75/145 的 `private-final-held-0035.jpg`、`0075.jpg`、`0145.jpg` 均为同一 crop 的**原片/初始化/优化后**，每版各一套。每版相应目录还含 `brow_eye_glasses`、`nose`、`lips`、`hairline` 的 `*-100pct.jpg` 局部放大图。视觉复核：普通版在 15/55/115/130 略低误差，Open 在 35/75/95/145 更低；普通版 145 的唇边局部有额外分散亮色，Open 75 的侧向轮廓也仍过软。两者的发际线均圆钝、鬓角/耳上体积不足，眼镜鼻梁处为漂浮高亮而非连续镜框。没有证据证明普通版提供了可直接迁移的眼区或嘴部几何优势。**Open 暂留研究主线，普通版只作研究对照；不能凭 0.00046 的均值差或一次主观观感切换默认。**普通版的正式产品许可亦未建立。

参数确实在变化，但不足以修复部件几何。Open 的头发局部位移均值 0.771 mm、p90 1.427 mm，相对可用 18 mm 每轴上限很小；头发平均 alpha **0.55→0.331**，平均尺度比 0.928，基色变化 0.114。普通版对应 0.767/1.416 mm、alpha 0.55→0.327、尺度比 0.928。近面细节初始来源色支持中位 Open 2 帧、普通版仅 1 帧；其位移 p90 均低于 0.63 mm。完整角色参数在两版 `part-parameters.audit.json`。

## 3. 为什么头发像“盖上去”的壳：按证据排序

1. **粗壳起点和深度欠约束是主因。** `probe_flame_hair_hull.py` 在头局部三维网格上用二维 hair mask 的多视角投影交/并支持形成占据，再做开运算、默认填洞、取表层。它不是多视图稠密深度，也没有发丝/短发方向几何。Open 基线粗壳留出 IoU 仅 0.4359、precision proxy 0.4721；可见面和被遮挡/未知体积未被完整区分。实际训练虽在同一 gsplat 前向参与遮挡，几何起点仍是帽壳。
2. **颜色和透明度比空间位置修正得更多。** 上述参数变化表明训练主要把壳调暗、调薄和染色，移动不足以把发际线/耳上厚度校到原片。代码中确有头局部三维 offset、scale、alpha、颜色/方向项及四元数，不能说“完全没有独立优化”；但约束与观测不足，现有自由度没有产生可靠真实形状。
3. **脸/耳/眼镜冲突约束不完整。** 损失只显式惩罚安全空区 alpha、脸肤区头发贡献和头发 mask 内覆盖；没有独立耳部几何、实际头发-耳/眼镜深度排序、邻近视角连续厚度约束。二维 hair mask 的外部像素也不能一概判为可靠空区。
4. **相机/头姿误差可能放大错位，但当前没有证据把它判为主因。** 两套 FLAME 共用相机协议后仍出现相似帽壳；大幅松动 F/K/姿态会掩盖几何问题，尚未进行有界姿态细化。

从原片训练视角做前后向 KLT、双视角重投影与三角化后，Open 只有 **61 个**去重头发局部种子；到 FLAME 面距离中位 18.6 mm、p90 42.85 mm，到粗壳最近距离中位 4.92 mm、p90 17.73 mm。它们验证头发不是贴头皮，但太稀，不能直接取代完整发型。眼镜高对比候选仅 **6 个**可接受三维种子，远不足以形成镜圈、镜腿、鼻托与耳侧连接；现有 859 个“细节”高斯实际贴近 FLAME 面，导致亮点替代镜框几何。

## 4. 第一轮真实修正：更严格头发占据，不予放行

隔离测试 `--min-support 4 --max-contradictions 0 --no-fill-holes`，只使用相同 14 训练视角，不读取留出颜色。粗壳点 2946→2577，留出几何 IoU 0.4359→0.4587、precision 0.4721→0.5141，但 75 号仍只有 IoU 0.4050。由该粗壳实际生成有来源颜色的 2568 个训练头发点，再在 Open 上按原损失**重新运行 900 次反向/Adam**，路径 `private-optimized-subset-900-footprint-1.00-hair-gate-s4-c0-open/`：留出头发投影 precision 均值 0.5422→0.5819，脸肤区误投贡献 0.02207→0.01741；固定 ROI RGB L1 则 0.0412546→0.0412904，略差。35/75/145 三联图仍显示帽壳、侧面不足与眼镜漂浮。该实验只证明占据门禁能减少部分误遮，**不是已修好头发，更不能替换基线**。

本次 A/B 和上述修正均未增密/分裂（点数变化 0），故没有新的分裂前后视觉结论。先前单独的有限分裂诊断 11715→17315 出现针孔/覆盖下降，见原外观训练记录；未把它计为本次质量提升。下一次若重试局部增密，必须同时审计 optimizer、绑定、语义、来源索引和覆盖缺口。

又加了一个仅供探针使用的三态可见性检查：投在 hair mask 内、却明显位于拟合脸面后方的体素归入“未知”，不算可见头发正样本，也不当成可靠空区。以同样 `s4-c0-open` 条件跑几何探针，头发壳变为 1348 点，留出 precision 0.6596，但 IoU 降到 0.4226；35/145 的 recall 仅 0.5253/0.4581，明显削掉真实可见头发。因此**拒绝这个硬阈值候选，未继续做外观训练**。这同时说明当前脸面深度/局部姿态尚不足以把单一 5 mm 阈值当作可靠发区裁剪规则；不能为了减少误遮把头发磨没。单测验证被脸遮挡的样例保持“未知”语义。

## 5. 颜色表达与现有 PlayCanvas 往返

训练器的颜色是 `sigmoid(base_rgb_logits + sh1 · normalize(-camera_means))`，**不是 PLY 原生 SH 系数**。`export_flame_appearance_research.py` 从训练视角的模型预测颜色（不使用留出源像素）拟合标准 3DGS degree-1 SH，再用 gsplat 1.5.3 导出静态参考帧 PLY。Open/普通版的训练视角每点颜色转换平均绝对误差为 0.000670/0.000685，p95 为 0.00255/0.00257；并非数学上的全视角恒等。

`scripts/probe-personal-playcanvas.mjs` 使用工程现有 `gs-viewer.js` 与 PlayCanvas 2.22.4，在 Windows Chrome/SwiftShader WebGL2 上加载两套各自的研究 PLY，同 35 号参考相机绘制 1080×1920。Open PLY SHA-256 `5b95f90ed3663f1f616eb3525d50c4e0e6212904eb910751e69c80f17e88bea3`，11715 点；普通版 `bda5af842dde20c9b134e36cf9252074252c747ad6985c7b8d1cc627f1400afc`，11636 点。`audit_playcanvas_head.py` 对各自 gsplat 优化图的固定 ROI 差异均约 **0.00608**；对原片误差分别 0.03890/0.03962。Open 安全空区未检出意外亮点，普通版检出 317 个。对照图在各自 `private-reference-0035-ply-contract/playcanvas/private-native-comparison-0035.jpg`。

另外对 Open 的 75/145 号局部姿态分别导出静态 PLY，再以各自的相机合同绘制，固定 ROI 与对应 gsplat 图差异分别为 **0.00598 / 0.00663**，对原片误差为 0.04685 / 0.04500；75 号安全空区仍有 220 个亮点。这是三个参考姿态的独立静态往返，**不是单一资产连续旋转通过**。侧向证据分别留在 `private-reference-0075-ply-contract/playcanvas/`、`private-reference-0145-ply-contract/playcanvas/`。

可重做的一例（其他模型/视角将参数路径和 `--reference` 同步替换）：

```bash
python export_flame_appearance_research.py .sources/quality-geometry-20260926-temp .sources/quality-geometry-20260926-temp/flame_open_e2_20260927/private-optimized-subset-900-footprint-1.00-ab-20260927/private-optimized-parameters.npz --variant open --reference 35
# 在项目根目录执行：
node scripts/probe-personal-playcanvas.mjs backend/.sources/quality-geometry-20260926-temp/flame_open_e2_20260927/private-optimized-subset-900-footprint-1.00-ab-20260927/private-reference-0035-ply-contract
# 返回 backend，再运行 audit_playcanvas_head.py，对同相机两张图做字节资产和画面对照。
```

这证明同一静态研究资产在电脑 PlayCanvas 可显示，且没有大幅颜色走样；白色边缘晕在训练器与浏览器均出现，属于资产问题。**未验证**动态表情/头姿、连续旋转、完整场景或鸿蒙端绘制，不得据此交付。

## 6. 下一步与停止条件

1. 保留 Open 主线和现有应用。用现有已拍视频中更多可可靠拟合的局部头姿视角（不造世界相机）改善头发/眼镜的多视图约束；对低支持/不确定区域记录未知，不把遮挡当空区。优先实际建立镜框独立局部几何与正反面厚度，当前 6 个种子只能作核查，不能强行插值为真值。
2. 将皮肤、五官、眼镜、头发分别绑定和计量：皮肤受限贴面；五官保持源色；眼镜与头发允许独立深度，但需真实高对比线条/可靠空区/多视角轮廓监督。先在 35/75/145 做发际线、鬓角、耳上、镜腿、鼻托、鼻翼、唇边局部放大及遮挡检查，再做受限姿态或 K 细化；不能以大姿态漂移压低 RGB。
3. 若局部几何确实改善，再把头发/眼镜/皮肤与颈肩衣物和有可信世界相机的房间一起进入**同一次**正式前向、深度排序和训练；黑底头部不当成最终资产。分裂和裁剪需维护 optimizer/部件/绑定/来源一致性；后续需另设未参与开发选择的最终审计帧。
4. 凡平均误差下降但局部头发/镜框更差、导出后不同、或只靠延长步数过拟合，一律标记不可放行。普通版仅研究对照，许可未明确前不得并入长期产品。本人新资产仍**不发布、不回传平板**。

本轮验证：10 项语法/合同单测通过；三次真实 900 步训练完成；两版 35 号及 Open 75/145 静态 PLY 的电脑 PlayCanvas 绘制完成。A/B 完成之后，为隔离头发占据实验给训练器增加了**默认关闭**的 `--hair-hull-suffix`；因此当前源码哈希与表内 A/B 实际运行哈希不同。已有审计和候选参数保留原始执行哈希，重跑时必须使用新 run-id、两版都重新训练，不得只重跑一侧混入旧审计。官方接口与许可参考：[gsplat 1.5.3 光栅化接口](https://docs.gsplat.studio/versions/1.5.3/apis/rasterization.html)、[PlayCanvas 高斯资产格式](https://developer.playcanvas.com/user-manual/gaussian-splatting/formats/)、[FLAME 模型许可](https://flame.is.tue.mpg.de/modellicense.html)。
