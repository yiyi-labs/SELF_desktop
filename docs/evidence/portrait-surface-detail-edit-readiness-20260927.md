# SELF 人像表面细节与编辑就绪：本轮实际实施记录

日期：2026-09-27。依据当前仓库、用户的 `SELF_Portrait_Surface_Detail_And_Edit_Readiness_20260927.md` 与本机执行结果。文档建议经过实际代码核对才采用。原 E1—E5 不改名、不降低门槛。本轮只改隔离的电脑端研究训练/导出/探针；没有改鸿蒙应用、签名、USB/HDC、既有上脸算法、故事或历史作品，也没有向平板回传新资产。工作区原有未提交修改均保留。

## 冻结输入与最小文件改动

- 原片 `backend/.sources/quality-geometry-20260926-temp/capture.mp4`：SHA-256 `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。
- FLAME 2023 Open `backend/models/flame2023open/flame2023.pkl`：SHA-256 `e75a0990728ba038c7da2a420ae4396f7ddd7781366c13026066c5b24f127623`。未重复普通版 A/B。
- 主研究基线 head-local-sh1 参数：`.../private-optimized-subset-900-footprint-1.00-sh1-head-local-20260927/private-optimized-parameters.npz`，SHA-256 `308da67a299dc98855fa4d3403197130811ec87d96dcb7ad967eee92950d9e46`；旧 Open 900 步仅保留回归。14 张训练图、8 张开发验证图。现有开发验证帧已参与方法选择，**不是盲测最终审计**。
- `backend/probe_orbit_observation_coverage.py`：原片 F_t 和同一 PLY 轨道转换到头局部坐标，按部位给观察方向、脸宽、清晰度代理、遮挡代理；不会把 viewer yaw 直接当真实人脸角。
- `backend/probe_orbit_micro_attribution.py`：同一冻结 PLY 的小范围轨道，比较完整 SH/DC、alpha、部件贡献、实际投影半径与深度范围；没有换生产渲染器。
- `backend/train_flame_local_appearance.py`：只加可选研究用的共享低维法向残差；基线模式与现有结果保持不变。
- `backend/research_face_surface_refinement.py`：按源视频训练视角自动选帧，训练帧姿态限幅，鼻唇源像素和多视角投票分配局部增密，保持周边画面与alpha；优化法向场、方向色、scale、alpha。无固定“第25帧特例”；本轮入口仍使用当前 E2 的 14/8 帧输入适配器，**尚未接入所有新拍摄任务的正式自动流水线**。
- `backend/probe_face_detail_sampling.py`、`backend/probe_local_face_footprint_budget.py`：在原生像素尺度审计投影 footprint 与真实细节、做局部而非全局缩放诊断。
- `backend/export_flame_appearance_research.py`：可选且故障关闭的研究候选绑定导出。逐点核验原始索引、部件、源图索引、可信度、三角和有界重心偏移；输出按精确 PLY 哈希版本化的私有绑定侧车。候选导出时为现有查看器设置 `editableSplats` 的表面前缀，避免错误发壳误进唇部试色。默认基线导出不启用此分支。
- `scripts/probe-research-edit-contract.mjs`：用实际 PlayCanvas 加载同一候选 PLY，真实圈选、试色、看原样与重放；不是合成点单测。

## 轨道与观察：源片两侧存在，可信局部观测不对称

固定参考第35帧 PLY `7cec883181b0fa21589970b472cef5debc29d9c3184e9294ae048d88d0f20be4`。报告：`backend/.sources/quality-geometry-20260926-temp/flame_open_e2_20260927/private-orbit-observation-source-quality-20260927/audit.json`。原视频曾证实有两侧面容；下表只问**当前已拟合且有颜色/深度代理支持的14个训练 F_t**，不能推断用户没拍到另一侧。

| 固定 PLY 绕看 | 头局部相对参考射线 | 投影皮肤宽度 | 鼻部最近训练方向中位角距 | 头发最近训练方向中位角距 |
|---|---:|---:|---:|---:|
| 前方 | 0° | 243px | 1.94° | 9.41° |
| 查看器 +60° | 63.23° | 239px | 46.66° | 60.61° |
| 查看器 −60° | 57.03° | 207px | 8.50° | 18.80° |

方向是逐点按当前 F_t、语义 mask 和近似深度代理计算；头发壳本身错误，所以发区“支持”仍是上界。所有22帧的源图脸宽和 Laplacian 清晰度代理在报告里逐帧列出。由此确认坏角度同时含观测外推和现有发壳错误；不能用缩窄轨道掩盖覆盖缺口。下一次头发深度试验的新增条件是从原片中已有但**尚无可靠局部 F_t**的相应侧面恢复可核查位姿和视差，旧61种子/9×9 NCC不重跑。

## 共有渲染链与亮边

固定 PLY 在 viewer +54°/+56°/+58°/+60°/+62°/+64°/+66° 用 gsplat 1.5.3 分别渲染完整 SH 和仅 DC，PlayCanvas 2.22.4 的原轨道也保留。实际中间量来自 `radii=[N,2]`、`means2d`、`depths`、`gaussian_ids`。报告：`.../private-orbit-micro-projection-20260927/audit.json`。

在预先固定的右上坏区 ROI，+60° 完整 SH 有 2637 个极亮且 alpha>0.2 的像素，仅 DC 为 0；同一 alpha 约 0.628，两者前乘 RGB MAE 0.07535。该 ROI 投影中心/footprint 相交的 3691 个高斯中，投影半径 P50/P90/P99 为 21/30/37px；1008 个半径>25px，其约91%属粗头发。深度 P10/P50/P90 为 0.3575/0.4447/0.5116m。+54°到+66°极亮计数平滑下降 3343→1810，**这个小范围样本没有看到突然的亮度跳变**。

视觉检查完整 SH/仅 DC 同一相机：`.../private-orbit-micro-projection-20260927/private-yaw-60-full.png` 与 `private-yaw-60-dc.png`。强白斑主要受方向色外推放大；去掉方向项后，大块发壳、错位和边界仍在，说明颜色不能代替结构修复。DC/完整 SH 共用几何、alpha 与 gsplat 排序，所以**没有排除**两渲染器共有的中心深度排序/投影近似；本次证据优先指向错误发壳、外推方向色与宽 footprint，未据此引入新的生产排序器，也没有声称完成精细排序参考。

## 鼻翼/唇部：已经运行真实优化，但候选未放行

`backend/probe_face_detail_sampling.py` 用冻结基线在开发帧 35/75/145 的原生 crop 核对：脸宽280/300/299px，鼻部有源色支持高斯的投影半径 P50 为20/27/22px；鼻部渲染横向梯度/原片仅0.636/0.364/0.603。唇部半径 P50 为21/27/23px。这个 footprint 是 gsplat 投影支持范围，不是固定21px的光学模糊半径；但与源图相比可见显著细节衰减。报告 `.../private-detail-sampling-baseline-20260927/audit.json`。

直接把 3574 个已支持鼻唇皮肤点局部缩放到0.85、0.70、0.55、0.40，开发集鼻唇 L1 依次从0.029984升到0.033549、0.046820、0.076140、0.126347；0.55后开始损失显著覆盖。**缩小高斯本身不是修复**，必须与有依据的局部容量、alpha和位姿约束一同处理。报告 `.../private-local-footprint-multiview-nose-lip-20260927/audit.json`。

实际执行的通用研究步骤：从源图训练视角自动选出可用的14帧；最多1°/1.5mm的每帧受限姿态诊断，只有训练鼻唇区误差下降才接受；源图残差与多视角票数分配局部子点，三角绑定与源点/部件/置信度一起重排；共享12控制点法向场每控制点最多1.5mm；完整头部同次前向，其他部件参数冻结但不隐藏；源图边缘只作为真实像素损失，输出没有锐化/补光/生成纹理；训练图上的覆盖与整图损失选择局部 footprint，开发图只评价。r6为 11715→12715 点、112步几何先行+520步外观，训练图接受的局部 scale 因子0.8；实测26.65秒，PyTorch allocated/reserved 峰766.02/838MiB。研究优化器从冻结参数新建，不声称继承不存在的 Adam 动量；每个新增点的源点和绑定已同步。没有实施裁剪，不能称裁剪已通过。

| 隔离试验 | 八张开发图鼻唇固定皮肤 L1 | 八张开发图完整 ROI L1 | 鼻唇边缘 L1 | 结论 |
|---|---:|---:|---:|---|
| 冻结 head-local-sh1 | 0.029984 | 0.041946 | 0.006405 | 对照 |
| r3：多视角220点，未限制外溢 | 0.029341 | 0.044012 | 未记录 | **失败**：局部数字变好，全脸变差 |
| r5：220点，邻区保留 | 0.029873 | 0.041946 | 0.006397 | 保住整图，但肉眼改善不明显 |
| r6：真实残差1000点，训练图选0.8 footprint | 0.029693 | 0.041972 | 0.006559 | **失败**：整图/边缘略差，仍不放行 |

上述完整 ROI 始终包括缺失像素。r5/r6 鼻唇区 alpha>0.2 覆盖均为1.0，r6 完整 ROI 覆盖0.994839、基线0.994861；这不是“细节已恢复”的证据。r6 法向场最大实际变化0.207mm，未产生可辨识的真实鼻翼/唇缘几何改善。可视原片/基线/候选三联图分别在 `.../private-face-surface-bounded-neighbour-r5-20260927/private-frame-0015-nose-source-baseline-candidate.png`、`.../private-face-surface-source-residual-r6-20260927/private-frame-0095-nose-source-baseline-candidate.png` 等；主观仍偏软。这是已执行的具体阻塞：现有大 footprint/局部相机与表面几何/源图对应不足，不能靠少量表面点分裂或方向色把真实小尺度纹理恢复。下一步应对可靠鼻唇多视角像素对应和局部形状做独立检查，再根据投影采样与覆盖分配容量；不能用更高对比、假毛孔或无限增加点数代替。

## 固定 PLY 绕看与现有编辑兼容

r3候选（**仍不发布**）导出 11935 点单一 PLY，SHA-256 `1da82b0fed159f589f094012bdd5afe977445871fd150932c631affaa701dc66`，精确 SH1 系数旋转训练射线色误差均值约 `5.2e-9`。PlayCanvas 2.22.4/Chrome SwiftShader 连续132帧轨道视频 SHA-256 `e1a520b7d8e163d2f16315fa1bc5a5429fd779f061990c2decfcceb19c6f4761`，没有浏览器异常；+60°坏发壳与白边**依旧存在**。电脑 gsplat/PlayCanvas 同 PLY/相机前乘 RGB MAE 前/+60/−60 分别0.01300/0.03143/0.01707，不等于视觉合格。研究视频和接触图在 `.../private-face-surface-multiview-support-r3-20260927/private-reference-0035-ply-contract/continuous-orbit/`。

研究绑定侧车 `private-edit-binding.json/.npz` 用精确 PLY 哈希防止旧圈选静默套用到新点序；逐点保存原始索引、source index、role、三角/重心或发局部坐标、偏移和源观测可信度。当前 role=1 仍把唇、眼、眼镜混在一起，不能声称完成精细语义保护或成熟编辑基底。实际 PlayCanvas 同资产唇部圈选初次选出523点，含21个错误发壳点；仅为研究资产设置现有查看器已支持的 `editableSplats=9018` 后，选出502点且全部为皮肤、0头发。数字 rose 试色画面有变化；“看原样”字节级截图哈希等于初始，再重放等于变化图；无浏览器异常。记录 `.../edit-compatibility-bounded-v2/audit.json`。这只验证**该研究资产的数字试色与可撤销合同**；未验证跨资产旧mask自动迁移、精确唇语义、OLAY实物效果或鸿蒙真机绘制。

## 门禁与可复现结论

| 既有门禁/事项 | 本轮结论 |
|---|---|
| E1 世界相机 | 仍失败；当前源片有两侧，但相应区间可信世界相机缺失。本轮没有伪造 C_t。 |
| E2 共享本人形状/运动 | 局部姿态、表面场和真实外观实验已运行；头发、镜框、颈肩仍未通过。 |
| E3 人物—房间完整同前向与连续遮挡 | 未通过，本轮黑底头部不代替完整场景。 |
| E4 原片细节与有界增密 | 研究子能力实际运行、绑定和覆盖探针通过；画质闸门失败。 |
| E5 同资产显示/编辑 | 电脑 PlayCanvas 固定PLY轨道及可撤销数字试色通过图形合同；坏角度画质失败；本轮**没有鸿蒙或手机新资产测试**。 |
| 8GB 瓶颈 | 当前头部子实验 766MiB allocated/838MiB reserved、约27秒，未触及8GB；不推算完整场景速度。 |

代码回归：此前在本轮 WSL 研究环境执行 `python -m unittest test_flame_appearance_contract -v` 7/7；Windows `node --test viewer-gs/tests/gs-edit.test.mjs viewer-gs/tests/ply-contract.test.mjs` 8/8；新增 Python 脚本用本机捆绑 Python 执行 `py_compile` 通过；`git diff --check` 通过。末次 WSL 重跑被当前 Windows 会话的 `Wsl/Service/E_ACCESSDENIED` 阻止，不将其记为新一轮通过。本轮未构建 HAP，因为应用代码没有修改，也不使用旧真机记录冒充新结果。

复现实验以 `backend/` 为 Python 工作目录，使用已锁定研究环境 gsplat 1.5.3、PyTorch 2.8.0+cu128：

```text
python probe_orbit_observation_coverage.py <job> <frozen-parameters.npz> <frozen-reference-export> --run-id source-quality-20260927
python probe_orbit_micro_attribution.py <frozen-reference-export> <frozen-parameters.npz> --run-id projection-20260927
python probe_face_detail_sampling.py <job> <frozen-parameters.npz> --frames 35 75 145 --run-id baseline-20260927
python probe_local_face_footprint_budget.py <job> <frozen-parameters.npz> --run-id multiview-nose-lip-20260927
python research_face_surface_refinement.py <job> <frozen-parameters.npz> --run-id source-residual-r6-20260927 --steps 520 --edge-weight .12 --geometry-warmup 112 --max-new-skin 1000
python export_flame_appearance_research.py <job> <r3-parameters.npz> --variant open --reference 35 --allow-research-binding
node scripts/probe-personal-continuous-orbit.mjs <r3-reference-export>
node scripts/probe-research-edit-contract.mjs <r3-reference-export>
```

每个实验用独立 run-id；已有同名目录会拒绝覆盖。`<job>` 是项目私有 `backend/.sources/quality-geometry-20260926-temp`。未合格模型不回传、不自动替换历史作品。
