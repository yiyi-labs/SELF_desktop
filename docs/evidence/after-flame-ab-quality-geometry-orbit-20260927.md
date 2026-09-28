# SELF：FLAME A/B 后的方向色、单资产绕看与局部几何复核

日期：2026-09-27。依据当前仓库、`SELF_After_FLAME_AB_Quality_Not_VRAM_20260927.md` 和本机真实运行记录；用户文档中的方案只作待核对建议。原 E1—E5 不变。本轮没有改动鸿蒙应用、签名、旧作品、USB/HDC、上脸与故事链，也没有回传任何候选资产。

## 冻结基线与输入

- 原片：`backend/.sources/quality-geometry-20260926-temp/capture.mp4`，SHA-256 `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。
- FLAME 2023 Open：`backend/models/flame2023open/flame2023.pkl`，SHA-256 `e75a0990728ba038c7da2a420ae4396f7ddd7781366c13026066c5b24f127623`。没有再做普通版选择。
- 冻结 Open 900 步参数：`backend/.sources/quality-geometry-20260926-temp/flame_open_e2_20260927/private-optimized-subset-900-footprint-1.00-ab-20260927/private-optimized-parameters.npz`，SHA-256 `8e0602b0b541e403bf11658ea6de6a62cc758b3f0a0f1871873750e6ab6080ac`。14 个训练、8 个开发验证视角，固定 ROI L1 `0.04125`；八帧已参与研发选择，不称独立最终审计。
- 修改代码后重新载入冻结参数，第 35 帧 ROI L1、hair recall、precision proxy 与保存记录逐项完全一致（差值 0）。

## 1. 方向色合同：确认旧研究路径问题，新增隔离路径

旧 `TrainablePortrait.raster` 的 `means` 是逐帧相机坐标，`sh1` 系数却固定在点上；旧颜色表达是 `sigmoid(base_rgb_logits + sh1·normalize(-means))`。其方向没有由相机转回固定头局部系，且非标准 SH。旧导出只按 14 个训练视角拟合 degree-1 SH，是近似转换。现有冻结资产和应用不受本轮新代码自动替换。

隔离研究模式 `head-local-sh1` 使用同一个 F_t 的 `R`，将 gsplat 的**相机到点**方向 `normalize(p_c) @ R` 转为头局部系，再使用安装的 gsplat 1.5.3 的 degree-1 基底、`+0.5` 和下限截断。导出固定参考第 35 帧时，对一阶系数作精确线性旋转；没有对逐视角重新取原片颜色。7 个回归测试通过，包括实际 gsplat CUDA SH 求值、相机绕看/roll 与精确系数旋转。14 帧训练射线上的数学转换绝对误差均值 `5.05e-9`，最大 `1.72e-7`。

新模式独立运行：`private-optimized-subset-900-footprint-1.00-sh1-head-local-20260927`；参数 SHA-256 `308da67a299dc98855fa4d3403197130811ec87d96dcb7ad967eee92950d9e46`。900 次真实反传/Adam，用时 23.57 秒（已经有编译缓存）。八个开发验证视角的固定 ROI RGB L1 `0.04195`，略差于冻结基线 `0.04125`；面部 `0.04060` 对 `0.03965`；头发 `0.03773` 对 `0.03749`。数学合同修正成立，画质没有因此放行。

代码：`backend/appearance_direction_contract.py`、`backend/train_flame_local_appearance.py` 的可选色彩模式、`backend/export_flame_appearance_research.py` 的精确导出分支、`backend/test_flame_appearance_contract.py`。旧模式仍是默认值。

## 2. 一份 PLY 连续旋转与同相机跨渲染器

固定参考第 35 帧只导出一次，11715 点 PLY SHA-256 `7cec883181b0fa21589970b472cef5debc29d9c3184e9294ae048d88d0f20be4`。实际 PlayCanvas 2.22.4 / Chrome SwiftShader WebGL2 从正面连续经过约 +60°、−60°、回正；130 帧视频，前后 PLY 哈希不变，无浏览器错误。视频：`backend/.sources/quality-geometry-20260926-temp/flame_open_e2_20260927/private-optimized-subset-900-footprint-1.00-sh1-head-local-20260927/private-reference-0035-ply-contract/continuous-orbit/private-fixed-asset-continuous-orbit.webm`，SHA-256 `c8cdbc8fe637a091830ca54bd4af657ac2390e0173b8631f86c3db105797004f`。联系图同目录 `private-fixed-orbit-contact.jpg`。

同 PLY、同捕获相机再用 gsplat 绘制，前方/正侧/反侧前乘 RGB MAE 分别 `0.01299 / 0.03154 / 0.01842`，alpha MAE `0.01221 / 0.01228 / 0.01311`。两种绘制都呈现 +60° 大块头发撕裂、背部异常色和白边；此缺陷不只是 PlayCanvas 解析问题。正侧诊断 ROI 的 alpha 贡献按皮肤/五官细节/头发约为 `20.5% / 0.1% / 79.3%`，来源主要是头发几何和可见性。参考图片：`continuous-orbit/private-yaw-positive-about-60-playcanvas-vs-gsplat.png`、`continuous-orbit/private-yaw-positive-about-60-semantic-rgb.png`。这些是黑底**头部研究样件**，不是完整人像/环境。

## 3. 多视图发点与局部修形：实际尝试但未通过

原 14 个训练视角的双视图 KLT、往返、三角化、角度与重投影筛选产生 61 个头局部发点。八个开发验证帧的直接 hair-mask 命中率约 `75.4%–90.2%`，只能证明二维投影相关，不能证明深度。按训练帧独立命中 ≥8、矛盾 ≤3、离旧壳 3–14 mm 且每父点最多一个，留下 25 个；中位位移 6.28 mm，P90 11.45 mm。采用带来源索引的子点与父点 alpha 分配，并在同一次 gsplat 前向中局部优化 180 步。新 run：`private-observed-hair-geometry-multiview-seeds-20260927`，11715→11740 点，用时 19.03 秒，未改应用。

八个开发验证视角的固定 ROI L1：旧色彩模式下的本轮 SH 基线 `0.04195` → 几何初值 `0.04206` → 局部优化 `0.04199`；头发 L1 `0.03773` → `0.03826` → `0.03782`。hair recall `0.98613` → `0.98575` → `0.98576`；precision proxy `0.54723` → `0.54811` → `0.54807`。第 35 帧原片/基线/候选对照与单 PLY 绕看均没有清楚的主观改善，侧面大块错误仍在。**候选拒绝，不能把点数增加算画质进步。** 候选 PLY SHA-256 `4df9cb545eac8325f57d5bad02663e5fc5a9e6f037593965fe872de08b34646b`，连续绕看视频保留在该 run 的 `private-reference-0035-ply-contract/continuous-orbit/`。

针对旧壳附近 9×9 原片发纹 patch，另用训练帧 40→25/50 和 100→90/110 做有界深度搜索。分别从 277/272 个近壳角点中仅得到 8/4 个同时满足双邻视图 NCC、深度峰值唯一性和有效范围的点。这个视频目前的**可信稠密头发深度证据不足**；不扩大壳、不生成发丝、不把未知区域当确定实体。眼镜原有 6 个种子在多个开发验证帧投影不稳定，仍不足以恢复镜架。暂不做以错误几何为基础的局部分裂。

## 4. 来源色复核：修正了点级训练观测，未改善留出画面

为排查异常亮色，单独计算每个旧发点在原片训练视角中、头发 mask 且壳前向可见时的颜色。不从背景、皮肤或生成模型借色。214 个来源首样本与多视图观察冲突的点，以真实训练像素拟合低阶方向色；这些点训练样本 RGB L1 `0.20776→0.07091`。但同一固定 PLY 侧面白边仍存在，八个开发验证视角整图 L1 `0.041946→0.042338`，头发 L1 `0.037732→0.038251`。**这份纯颜色候选也拒绝**；训练点上的局部数值改善不是模型质量改善，更不能靠“刷黑”处理头发壳。独立 run：`private-observed-hair-color-visible-video-20260927`，候选参数 SHA-256 `93a56c14ba3c815e18f78c6e18330ca28d6be7707c9c629300cc43301e37c750`。

## 5. 头发方向色外推的局部候选

另外以完全相同的 900 步、14/8 划分、几何与色彩坐标，只对**头发方向系数**加有界先验 `0.08 × mean(sh1_hair²)`，避免训练角度以外的一阶 SH 极端外推；这不是取代真实发色或给头发涂黑。独立 run `private-optimized-subset-900-footprint-1.00-sh1-hair-prior-20260927`，参数 SHA-256 `cbcc2a40c9444a5ad83da81a1f7817ca946fdc6953690cf13c5967fec9165d69`，固定 PLY SHA-256 `1075817fb913103b9b08b83ccba424be5b68ff62bbd50584d4708dbc731536fe`。八个开发验证视角头发 L1 `0.03773→0.03759`、precision proxy `0.54723→0.55026`、额头发贡献 `0.02300→0.02184`，但整 ROI L1 `0.04195→0.04198`，无整体进步。同角度 +60° 画面所选右侧 ROI 的极亮像素数 `7054→3441`，白斑有所减轻；大块错误壳与边缘仍在。对照 `private-optimized-subset-900-footprint-1.00-sh1-hair-prior-20260927/private-reference-0035-ply-contract/continuous-orbit/private-hair-prior-side-comparison.png`；连续视频同目录。**这是有限的外推色伪影缓解，不是发型细节或几何修复，仍不放行。**

## 6. 8GB 实际资源记录

本机 RTX 5070 Laptop GPU，`nvidia-smi` 标称 8151 MiB，实验外空载占用约 158 MiB。隔离 SH 900 步过程实际设备占用峰值 633 MiB、GPU 利用率峰 45%；PyTorch allocated/reserved 峰 255.49/300 MiB。局部发点 180 步设备占用峰 825 MiB、PyTorch allocated 峰 418.5 MiB（reserved 见 run 审计）。额外方向先验 900 步设备峰 476 MiB。它们是**头部研究子任务**，不足以证明完整重建的显存/耗时，但足以排除“这些头部画质失败因为 8GB 已用满”。监测原始采样：`private-sh1-head-local-20260927-gpu.json`、`private-hair-geom-20260927-gpu.json`、`private-hair-sh-prior-20260927-gpu.json`。

## 当前门禁结论与下一步

| 项目 | 结果 |
|---|---|
| 冻结 Open 900 步和旧版显示回归 | 通过：第 35 帧关键数值逐项一致 |
| 头局部 SH / PLY 坐标数学合同 | 通过：实际 gsplat evaluator 与精确系数旋转回归 |
| 单一 PLY 的 PlayCanvas 连续绕看与跨渲染器诊断 | 通过图形链路；**画质失败**：侧面撕裂、白边、黑底截断 |
| 25 个真实双视图种子的局部几何候选 | 失败：无可见局部改善，留出误差/覆盖略恶化 |
| 多视图头发来源色候选 | 失败：训练点改善、留出图像恶化 |
| 头发 SH 外推先验候选 | 局部极亮伪影减少；整体 L1 没有改善，几何失败依旧，不放行 |
| 当前 8GB 是否是头部子任务瓶颈 | 不是：实测设备峰值远低于 8151 MiB；完整联合任务未验证 |
| 覆盖保持的局部增密 | 未执行：所依赖的局部几何尚未通过 |
| 最新本人完整场景、平板绘制/回传 | 未验证；所有新候选均未回传，旧作品保留 |

最小后续任务：在现有视频中只对已经有 F_t 且实际有相对视差、清晰发纹的额外短片段求更稳的头部局部姿态和多视图对应，先让足够的真实头发外表面深度通过留出轮廓/遮挡；对镜框另做独立的可见线条与非反光对应。几何通过后，使用已有带来源/语义/优化器重排的有界 split，在发际线、镜框和五官残差区比较分裂前后 alpha、局部画面与固定资产绕看。头颈肩衣物和房间仍需同一空间、同一次遮挡联合检查，不能由黑底头部替代。不得用当前失败 PLY 覆盖用户作品。

复现入口：

```text
python -m unittest test_flame_appearance_contract -v
python train_flame_local_appearance.py .sources/quality-geometry-20260926-temp --stage subset --steps 900 --variant open --run-id sh1-head-local-20260927 --color-mode head-local-sh1
python export_flame_appearance_research.py .sources/quality-geometry-20260926-temp <上述run的private-optimized-parameters.npz> --variant open --reference 35
node scripts/probe-personal-continuous-orbit.mjs <上述run的private-reference-0035-ply-contract>
python probe_personal_fixed_asset_render.py <上述run的private-reference-0035-ply-contract>
python research_local_hair_seed_geometry.py .sources/quality-geometry-20260926-temp <上述run的private-optimized-parameters.npz> --run-id multiview-seeds-20260927 --steps 180
```

所有相对路径以上述 `backend/` 为 Python 工作目录；Node 命令以项目根为工作目录。run-id 目录已存在时研究脚本会拒绝覆盖，需要新 ID。实际使用的模型/原片/中间数据在项目私有 `.sources` 与 `backend/models`，不会移动到下载目录或发布包。

依据：本机已安装 `gsplat 1.5.3` 的源码和 CUDA 求值器；[同版本官方 rasterization 文档](https://docs.gsplat.studio/versions/1.5.3/apis/rasterization.html)说明 SH/N-D 通道、透明合成与 K 梯度限制；[MonoHair 原始项目](https://keyuwu-cs.github.io/MonoHair/)仅启发局部多视图外表面检验，本轮没有移植其模型或声称其结果已在本机复现。
