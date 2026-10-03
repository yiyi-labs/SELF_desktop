# 人像优先、软表面与可选眼镜：2026-09-28 实际实施记录

本轮延续 E1—E5，不更换引擎。重启后 RTX 5070 Laptop GPU 在 Windows 与 WSL 中均恢复可用，Torch 2.8.0+cu128 / gsplat 1.5.3 实际完成反向训练。没有重装驱动；此前独显消失的具体原因仍未确认。

**结论：完成了可复用的研究实现、真实训练、同一资产的电脑连续绕看和失败回滚；没有完成可发布的人像质量修复。没有安装应用、回传候选或覆盖旧作品。**

## 1. 本轮文件与冻结边界

新增或继续完善：

| 文件 | 实际内容 |
| --- | --- |
| `backend/reconstruction_portrait_model.py` | 完整头部导入、精确尺度/协方差/SH 变换、共享表面残差、可移动重心绑定、邻接三角 walking、皮肤软约束、父点替换与 Adam/来源回滚 |
| `backend/reconstruction_portrait_pipeline.py` | T0/T1/T2、真实 local/T3/T4 优化、原生人像 ROI、持续局部监督、阶段检查点、单份参考状态 PLY |
| `backend/reconstruction_portrait_capacity.py` | 有限局部容量实验；真实照片恢复；决策前图像保存；失败完整回滚 |
| `backend/reconstruction_local_lines.py` | 真实眼周线段的有限多视角三角化、第三视角与独立点深度核对；只输出候选 |
| `backend/reconstruction_accessories.py` | 可选眼镜的有证据/无证据/未知/混合状态合同；普通眼周边缘不能直接当成眼镜 |
| `backend/audit_portrait_research_run.py` | 逐帧指标、实际观察方向、同视角图、原冻结文件核对 |
| `backend/test_reconstruction_portrait_model.py`、`backend/test_reconstruction_accessories.py` | 参数、坐标、邻接、回滚、无眼镜与误识别语义回归 |

新入口只接受经过关联检查的 preparation；没有硬编码当前人的名字、视频名、帧 ID 或必须戴眼镜。当前准备适配器仍是研究用 FLAME/观测缓存，**没有宣称所有新视频的自动准备和质量已经验证**。

与重启前 checkpoint 对比，记录中的 9 个受保护文件 SHA-256 全部不变：生产 worker、旧联合训练器、USB 传输、PlayCanvas 源码/打包资源、编辑代码、构建签名配置和依赖锁。旧文件已存在的 Git 修改全部保留。不能把本轮研究文件当作已接入平板生产算法。

## 2. 输入与协议

- 实际源片：`backend/.sources/quality-geometry-20260926-temp/capture.mp4`。
- SHA-256：`7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。
- 模型：FLAME 2023 Open；模型 SHA-256 `e75a0990728ba038c7da2a420ae4396f7ddd7781366c13026066c5b24f127623`。没有再次做 Open/普通版 A/B。
- 输入外观参数：原已校正 head-local-sh1 的 Open 900 步文件 `private-optimized-parameters.npz`，SHA-256 `308da67a299dc98855fa4d3403197130811ec87d96dcb7ad967eee92950d9e46`，旧文件不变。
- preparation：`backend/.sources/integrated-components-v2-20260928-e`。实际本轮是 **91 个局部训练观测、8 个开发观测**，其中 32 个局部训练观测没有世界连接；世界训练使用 59 个观测。它包含原 14 个训练视角的邻近观测，不能说本轮仍是原始 14/8 协议。
- F、K、整流图、crop 采用 preparation 的同一套坐标。C 仍是临时研究静态相机，尺度是共享拟合量，**不是独立标定通过**。没有补造缺失 C。
- 当前开发 8 帧已参与选择方案，不能称最终盲测。另保留的 3 个源帧只登记为后续审计预留，未声称已通过独立审计。
- 强/软实验都从旧 900 步参数再追加 900 步；表中的“900”指本轮追加步数，不能与历史 900 步平均 RGB 直接混用。

所有主要 ROI 误差包括缺失像素，不只计算已覆盖像素。局部放大矩形也没有把黑色空洞从指标中去掉；矩形可能含背景，其数值不能等同纯皮肤误差。

## 3. T0 → T1：不再在迁移时换一套人像

完整保留 11,715 个旧头部点（8,798 表面点、2,917 旧粗发壳点），没有沿用旧完整场景初始化对表面点的筛除。这一步保留坏发壳是控制变量，**不是认可发壳可发布**。

局部 `F` 与世界 `C` 使用同一全局尺度：`C H = [R_F, s t_F]`。位置、尺度、协方差和 SH 同时变换；参考相对运动为恒等，不要求绝对 H 是单位矩阵。near/far 随单位尺度变换。

真实图像验证：T0/T1 相机坐标最大差约 `1.79e-7` 米，协方差最大差约 `4.37e-11`；RGB 平均绝对差约 `1.90e-7～4.09e-7`。个别边缘像素最大差至 `0.00544`，不能称逐像素位完全相同，排序/浮点阈值差异仍存在。

在原片/T0/T1/T2 同视角对照中，T0 与 T1 的脸、坏镜框、坏头发几乎一致。**当前第一处明显细节不足已经在局部 T0 中出现，不是进入世界坐标后才全部糊掉。** 旧管线的筛点确实被绕开，但不是目前所有错误的唯一解释。

## 4. 软表面是真实优化，但尚不能宣称画质改善明显

新增共享顶点残差、可学习重心坐标、法向偏移；越边只沿连接三角走，不用欧氏最近面跨跳到另一片嘴唇/鼻翼。walking 支持语义屏障；当前实际运行仅使用网格连接和法向屏障，尚未加入经核验的完整区域屏障图。

软距离项同时包括中心偏移与法向方差，允许厚度由观测原生像素尺度换算，不把所有高斯压成零厚度皮。此项只用于皮肤，不用于头发/五官细节。现有 scale 激活范围保留，未做全局缩小高斯。

真实执行颜色/SH、alpha、scale、rotation 和共享表面参数的交替 Adam 更新；基础姿态固定，未同时打开所有自由度。没有生成纹理、锐化、磨皮或补假高光。头发位置本轮控制变量中冻结，不能说已经完成头发体积优化。

强约束参照是“同一导入 P 上使用 v2 式 3.5mm/.35 限制”的控制实验，**不是重跑历史 v2 的全部实现**。

| 开发帧 | 初始 T0 | 强约束追加900 | 软约束追加900 | 联合微调后局部 T0 |
| --- | ---: | ---: | ---: | ---: |
| 15 | .027810 | .026415 | .026442 | .025082 |
| 35 | .023045 | .021884 | .022163 | .025919 |
| 55 | .060712 | .054850 | .054262 | .055567 |
| 75 | .028146 | .024053 | .024073 | .023779 |
| 95 | .032316 | .024944 | .024925 | .024653 |
| 115 | .034887 | .034511 | .034753 | .031505 |
| 130 | .035607 | .033262 | .033322 | .030666 |
| 145 | .027533 | .027413 | .027165 | .025893 |

软表面并未稳定优于强限制：部分视角略好，部分更差，镜架位置和短发纹理仍不正确。图像/先验梯度审计也没有显示本轮软先验压倒图像梯度，例如初期法向 image/prior norm 约 `.506/.000455`，共享残差约 `.851/.00242`。因此不能继续只靠放宽阈值或加步数宣称解决。

真实同视角原片、初始化、两种900步和联合结果：

- [35帧对照](../../backend/.sources/portrait-soft-surface-20260928-review/frame_0035.png-controlled-comparison.png)
- [75帧对照](../../backend/.sources/portrait-soft-surface-20260928-review/frame_0075.png-controlled-comparison.png)
- [145帧对照](../../backend/.sources/portrait-soft-surface-20260928-review/frame_0145.png-controlled-comparison.png)

## 5. 完整场景前向与真实失败定位

完整实验共 34,083 点：原头部 11,715 + 测得的环境/衣物 22,368。同一次 gsplat 排序与透明合成中包含所有组，没有用隐藏背景的结果冒充完整场景。

- T2：保留头部，加入冻结环境/衣物。
- T3：300步只更新环境，头部参加遮挡但参数冻结。
- T4：300步受限联合更新，始终保留全部可靠局部 F 监督；无 C 帧只用于局部，不用于房间。

发现并修复两处研究实现问题：初版 T3 梯度审计传入空参数导致中断；第二版 T3 对冻结 embedding 做了重复归一化，均值变化虽仅约 `6.08e-9`，仍违反严格冻结。r3 从已完成的 local900 检查点重放 T3/T4，不重做900步；新增精确相等断言。**r3 的 T3 全部人像参数变化为 0。**

T4 的35帧局部脸误差从 `.022163` 恶化到 `.025919`；其余视角有升有降。因此持续局部监督已经落实，但当前损失分组仍不能保证每个重要视角不退化。需要在阶段结束做关键视角保留/回滚决策，不能按均值直接发布。

房间仍覆盖不足，颈肩衣物只有参考/准静态假设；当前没有通过真实动态连续性验证。实际全景仍出现模糊块和连接问题。没有用羽化贴片、扩大皮肤壳或增加透明度把这一缺口掩盖掉。

## 6. 有限容量实验：失败候选已回滚

用软表面 local900 检查点，选 5,230 个皮肤父点；197个因子点观测支持不足保留父点，实际替换5,033个父点为10,066子点。总头部点数11,715→16,748，目标皮肤点接近2倍，**不是全模型翻倍**。真实多视图支持目前是正面法向+有效投影+人像mask代理，不等于已经解决精确遮挡。

父点实际退休，同步更新 Adam、绑定、语义、置信、代次和来源索引；子点不是冒称独立三角化的新测量。使用48步原片恢复，禁止无限恢复和临时改验收容差。

孔洞率没有明显恶化，但95帧 RGB `.024925→.031062`、130帧 `.032897→.038164`，超过原定逐帧容差，**拒绝并完整回滚到11,715点**。这说明在这次分裂初始化和有限恢复预算下，增加容量并未自动带来质量；不等于证明密度永远无用。

第一次保存的是回滚后图像，证据不足；因此按原参数补跑一次，专门保存 `capacity-r2/candidate-before-decision/` 中的真实决策前结果。没有调整阈值争取通过。

## 7. 镜框与不戴眼镜的用户

本轮查明：当前 `glasses_visible` 来自六类分割中的通用 other 类和眼周 Canny 边缘，**不是眼镜语义分类器**。眉眼、镜片反光也会进入，不能由名字推断用户戴眼镜，更不能给所有人固定添加镜架。

新的有限线几何实验使用已知 F 下的解释平面与射线交点、第三视图线支持和真实颜色剖面，不把16个点任意连成镜框。最初348段几何候选视觉上混入大量眉眼交叉线，明确失败；加独立三维点深度核对后只剩4段短线，主要是鼻梁附近，**不足以代表完整镜架、镜腿和耳侧连接**。没有把这4段塞进旧表面以制造双层眼镜。

新增配件合同：

1. **有眼镜**：明确语义和多视角几何支持共同成立，才允许新建独立部件；镜框不贴皮肤。镜片高光不当实体线。
2. **无眼镜**：眼镜部件可为空，眼睛、眉毛、眼睑和皮肤仍用真实像素监督，不因缺少镜框种子而使整个建模失败。
3. **未知/遮挡**：既不补一副眼镜，也不擦掉现有影像中的配件；保留观测和不确定性。
4. **采集中摘戴**：识别为混合观察状态，不能硬拟合成同一个刚体镜框或据少数帧覆盖整段。

这些逻辑已通过7项回归，实际线候选导出也记录 `automatic_promotion=false`。**这不代表自动眼镜识别模型已经接通，也不代表不戴眼镜的真实视频重建已通过。** 本轮没有无眼镜多视角样本，不能拿清空mask的合成测试代替其画质验收。

核对了可进一步隔离验证的细分脸部语义方案：[BiSeNet face-parsing 官方实现](https://github.com/yakhyo/face-parsing)、[标签代码](https://github.com/yakhyo/face-parsing/blob/main/utils/common.py)。它将眼镜、眼睛、眉毛分开，适合为后续观察提供语义证据；仍需要真实视频的逐帧可见性与跨视图检查，不能直接当几何真值。代码标 MIT，但其说明的训练数据为 CelebAMask-HQ，[数据方条款](https://github.com/switchablenorms/CelebAMask-HQ#dataset-agreement)限制非商业研究；本轮没有下载权重或加入交付依赖，也没有推断代码许可自动覆盖所有权重/数据使用。

LIMAP 2.0.0 核心轮子尝试隔离下载，网络中断后长期未完成，已停止该下载；没有改现有环境。当前线算法为本项目独立实现，并未宣称已由 LIMAP 实跑通过。参考：[LIMAP 官方项目](https://github.com/cvg/limap)。

## 8. 同一 PLY 连续绕看与实际绘制

r3 唯一参考状态资产 SHA-256：

`bf99793534905804f2361a91f7065b382065ed2614aec8e05c6fe8f69e6ce031`

参考观测111；没有转一次相机就重新训练或导出另一份模型。标准 PLY 使用精确 SH1，其他高阶系数补零，PlayCanvas 2.22.4现有打包代码不变。

- [连续左右绕看视频](../../backend/.sources/portrait-soft-surface-20260928-scene-r3/continuous-orbit/private-fixed-asset-continuous-orbit.webm)
- [小范围水平与俯仰绕看](../../backend/.sources/portrait-soft-surface-20260928-scene-r3/continuous-orbit-small/private-fixed-asset-continuous-orbit.webm)
- [相同相机：PlayCanvas / gsplat / 3倍差异图](../../backend/.sources/portrait-soft-surface-20260928-scene-r3/continuous-orbit-small/private-front-start-playcanvas-gsplat-difference.jpg)

两个浏览器运行均无 JS 错误。相同实际相机的可见皮肤跨渲染器 L1 约 `.00800～.00975`，整图 `.01074～.02847`，差异仍存在，不称完全一致。两者仍共同出现坏发壳/镜框，因此不能用加载成功宣布画质成功，也不能据此排除共同的中心深度排序近似。

根据资产实际 H、浏览器实际相机和局部 F 重新计算观察方向：两个标作±60的端点，最近局部训练方向分别相差约2.72°、4.38°；小俯仰端点约6.52°、7.10°。**这些是方向距离，不是每个像素都可见的证据，也不是把 viewer yaw 直接当真人转头角。** 至少不能笼统把左右端点缺陷归因于“用户没有拍到另一边”。

这是电脑 Chrome SwiftShader 图形证据。**本轮鸿蒙、手机/平板性能和编辑兼容未验证。** 既有 Morton 重排与 editable-prefix 点索引风险仍未改动，不能把本次几何显示等同“圈选编辑已兼容”。

## 9. 耗时和8GB显存

| 实验 | 实际优化时间 | 含加载/审计/导出总时间 | Torch峰值分配/保留 | 设备峰值使用 |
| --- | ---: | ---: | ---: | ---: |
| 强约束追加900 | 43.68s | 111.26s | 164.75 / 484 MiB | 881 MiB |
| 软约束900+环境300+联合300（r2） | 45.99+26.21+26.75s | 129.69s | 240.39 / 500 MiB | 897 MiB |
| 修正严格冻结后的T3/T4（r3） | 32.61+35.26s | 103.36s | 244.29 / 536 MiB | 933 MiB |
| 局部容量+48步恢复+决策前图 | 计入总时间 | 34.39s | 未单列Torch值 | 675 MiB |

以上均从现成 preparation/旧外观参数启动，**不包含视频解码、相机求解、FLAME拟合和准备缓存构建**，因此不能称端到端2分钟。设备峰值包含同时存在的显示等开销；Torch峰值不是全部显存。

这组实验无 OOM，显存远未占满8GB。当前画质不应归因于8GB不足；更密集表示和完整新视频任务仍要重新实测峰值，不能无限扩大预算。

## 10. 可复现命令

在 WSL Ubuntu-22.04 的工程 `backend` 目录，Python使用 `/opt/self-reconstruction/venv/bin/python`，CUDA arch为12.0。已有输出不可覆盖，复跑必须换新run-id。

```bash
export TORCH_CUDA_ARCH_LIST=12.0
PY=/opt/self-reconstruction/venv/bin/python
P=.sources/integrated-components-v2-20260928-e
$PY reconstruction_portrait_pipeline.py "$P" .sources/<new-strong> --local-steps 900
$PY reconstruction_portrait_pipeline.py "$P" .sources/<new-soft> --soft --local-steps 900
$PY reconstruction_portrait_pipeline.py "$P" .sources/<new-scene> --soft --resume-state .sources/<new-soft>/local-state.pt --room-steps 300 --joint-steps 300
$PY reconstruction_portrait_capacity.py "$P" .sources/<new-soft>/local-state.pt .sources/<new-capacity>
$PY reconstruction_local_lines.py "$P" .sources/<new-lines> --anchor-support
$PY -m unittest test_reconstruction_portrait_model test_reconstruction_accessories test_flame_appearance_contract -v
```

尖括号是需替换的run-id，命令不可原样带占位运行。资源采样使用原有 `probe_gpu_process_telemetry.py`；没有改测试阈值。

Windows工程根目录复用：

```powershell
node scripts/probe-personal-continuous-orbit.mjs backend/.sources/<new-scene> --full-scene
node scripts/probe-personal-continuous-orbit.mjs backend/.sources/<new-scene> --full-scene --small-interaction
```

再由 WSL 运行 `audit_v2_fixed_playcanvas.py .sources/<new-scene>`。完整结构化证据见 [evidence.json](../../backend/.sources/portrait-soft-surface-20260928-review/evidence.json)。每次运行的config保留当时源代码哈希；r1/r2/r3不是完全相同版本，差别已在上文列出。

最终23项回归全部通过；实际训练与绕看证据另列，不能用单测替代画质。当前代码和相关实验配置另保存最终快照以便复核；原始历史run只留有当时源码哈希的地方，不宣称可恢复未保存的逐字节源码。

## 11. 下一步最小任务及明确未完成项

1. 首先把通用眼周边缘与真实配件语义分离，取得有眼镜/无眼镜/强反光的实际观察测试；当前合同防误用，但分类器、空部件自动初始化和跨用户完整重建尚未联调。
2. 镜框只在真实多视角线段和深度支持成立的区域重建。新部件必须同时处理原来烘在皮肤上的镜框颜色，不能叠两层；不可见眼周不以生成皮肤补齐。
3. 头发需要新的有效局部几何与姿态证据。旧粗壳仍错，本轮没有靠改壳阈值伪装修复。不要重复原9×9 NCC或61点失败实验。
4. 对相对可靠面部区域继续有界姿态/共享表面细化，同时添加逐关键视角的阶段回滚，定位35帧在T4恶化的梯度来源；本轮没有新增F/K自由优化。
5. 环境、颈肩、衣领的真实共同运动与覆盖仍待解决；当前准静态衣物不是通过的连续人体表示。不发布当前全景。
6. 最终只有部件结构和局部细节通过，再做完整场景、真实鸿蒙绘制与编辑索引验收。保持旧作品、签名、传输、上脸和故事不变。

状态：E2/E3局部研究实现有进展，完整人像质量仍失败；E1可信世界连接缺口未被本轮消除；E5电脑实际绘制子能力有证据，鸿蒙新候选未测试。没有重定义或降低原E1—E5发布标准。
