# 脸前残留、人物轮廓与头发：限定证据附录

记录日期：2026-10-03。此附录只汇总已执行检查与失败对照，不修改核心、生产配置、旧作品或主报告，不含私人图片。路径均以仓库根目录为基准；各研究产物在 `backend/.sources/`，不因此进入 Git。

共同原片 SHA-256：`7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。

## 1. 当前房间点中心没有证实位于皮肤之前

对象是 `backend/.sources/live-complete-repair-20261003-room-density-training/` 的 **54,379 个 room 点**，不是下面轮廓诊断的 33,920 点旧候选。

- CPU 实际检查 16 个原训练视图；高置信原图 class-3 皮肤、face_core 内圈，排除镜框，并腐蚀 9 原生像素以避开分割边界。
- 每图投影进该范围的房间中心为 719–2,205 个。在 3%、8%、12% 三个诊断前置余量下，前置中心均为 **0**。
- 核对了每份深度文件 hash、原片/准备身份、`K_processed=A@K_native`、记录的 `F_hair=F_root@D_reference_to_frame`、motion receipt 与尺度。world 相机 Z 除以 `23.24447809019201` 后才与同张原图的 head-local depth 比较。
- DA3 深度仍是条件几何假设，不是独立首表面测量。此结果仅检查**中心**，不能排除框外高斯足迹、错误排序近似、侧绕时遮挡或后景穿过半透明人像。
- 当前实现 `backend/reconstruction_live_dense.py` 中 `support_samples` 的 free 票只在同部件语义内计算，深度方向 `z < depth` 正确。T3 有原始贡献不退化保护和几何范围约束，但没有最终足迹级空射线再验证。这是约束缺口，不能直接当作本模型存在错误前置中心的证据。
- 不据此删除 room、把全部 room 后推、全局缩核或强行提高人像 alpha。需要先识别实际共同排序中的衰减贡献。

核验输入与结果：

| 项目 | SHA-256 |
|---|---|
| 当前 `T3-state.pt` | `c65fdc1e7190100d42e108084cf0ca3105093c1a6d9721ea298abeaecac412a5` |
| `preparation.json` | `b81171155a76f72276a7a99de9818c7ddfa82b44001d06d83aefb087a0d327a5` |
| `local_geometry.npz` | `a330dcd07dcfb0a44cc89c1659058980525f1768265e260009dc90729d76d4b9` |
| head depth manifest | `d5cd0d7cba6c816fc39fa3c997409360626e7a88e388b08072882baeb0804540` |

证据：`backend/.sources/live-complete-repair-20261003-room-front-centres/report.json`、同目录 `summary.md`。工具：`backend/audit_live_room_front_centres.py`，CPU 完整运行 7.04 秒，无 GPU、无新原图保存、无模型变更。

`backend/.sources/live-complete-repair-20261003-strict-skin-context/face-composite-selection.json` 的旧共同合成选择中，参考 0053 的 addedEnvironmentAttenuationPixels 为 0；0011/0022/0032/0037 则有 692/2,881/4,091/2,019 像素。它证明不同视图不能一概而论，**不能代替当前 room-density 终态的足迹验收**，也不能把所有白化归因于前景 room。

## 2. 轮廓黑洞与辅助预算稀疏是两种问题

本节冻结对象是 `backend/.sources/live-complete-repair-20261003-unified-entry/`：room 主参考 0047 + 辅助 0119/0052 + 原范围外点，共 **33,920 点**。不是原始 0053 深度池，也不是当前 54,379 点 density 训练终态。

**先纠正口径：**早期距离变换将无效去畸变画布边缘计成人物边缘。旧“8,943 个人像近边黑洞”不能用于解释耳/肩。旧报告保留；最终采用有效人物与有效 room 之间的距离，无效画布不属于任一类。

已证实：

- 主表面合法候选 15,979，保存 15,750，另保留原范围外 10,170 点，主参考并非严重预算截断。
- 两个辅助表面去重前合法候选为 15,491 / 16,968，几何去重后 14,131 / 14,890，旧预算各只保存 4,000。保持原尺度、alpha 与全部过滤的 CPU 潜力重放显示预算对覆盖有实质影响；它不证明 RGB、几何和共同遮挡已经通过。
- 在参考 0053 的真实人物外侧 0–10px / 10–30px、明确 observed_room 范围中，`alpha<.01 && q_room<.01` 真黑洞为 **0 / 431** 像素。
- 补回整个合法未保留池，431 个黑洞中仅 229 个获得潜力 >.01，**0 个达到 .8**。因此仅补预算不能解决这些具体黑洞。
- 19,830 个已退役旧 room 点对这 431 个黑洞的潜力均为 0，未证实是单参考退役导致；不能盲目恢复全部旧点。
- 最近原网格中心的中位距离为 11.48 原生像素；431 个黑洞中 416 个最近候选的局部导数无效，没有发现近邻被 free-space 冲突直接拒绝。这把排查位置收敛到局部深度/表面断层，**不证明应放宽 3% 深度边界或把人体边界深度坡当背景**。
- 同语义单侧导数实验只补出 219 个独立合法候选（114 strict-depth、105 条件表面点）。它仅使 65/431 个黑洞获得 >.01 潜力，0 个达到 .8。未作为整圈修复放行。

新增 observed-empty-space 负监督减少部分落到 room 像素的人物贡献，但五视图覆盖仍有退化，黑洞基本不减少。它不能替代缺失背景几何，也未作为黑边修复默认启用。

正式修正证据：`backend/.sources/live-complete-repair-20261003-unified-silhouette-corrected/report.json`、同目录 `summary.md`。辅助证据：`backend/.sources/live-complete-repair-20261003-unified-room-pool-audit/`、`backend/.sources/live-complete-repair-20261003-shared-contour-counterfactual/report.json`。其中 CPU potential 不含真实组件间遮挡，不能冒充 GPU 累计 alpha。

工具：`backend/audit_live_boundary_coverage.py`、`backend/audit_live_contour_counterfactual.py`、`backend/audit_live_boundary_footprints.py`、`backend/audit_live_room_budget_coverage.py`、`backend/audit_live_silhouette_cached.py`。`backend/test_audit_live_boundary_coverage.py` 4 项通过，包括无效画布边缘回归。

## 3. 头发不连通窗口不能直接当成多余发量

对象：`backend/.sources/live-complete-repair-20261003-fresh-full-input/result.json` 中的 8,000 点 hair；head-local 接受窗口 0/1/3，参考联通窗口为 0/1。

- 窗口 3 的 1,676 点中，891 点在参考联通观察中仍有至少 3 张不同原图的正支持，521 点无联通正支持。没有跨窗连通证据不等于已证明几何错误。
- 367 点副本抑制实验使用“非联通来源、无联通正支持、至少 3 张条件 room-front 反证、无同图预测歧义”的规则。它仍使头发明显退化：

| 固定开发视图 | T2 hair RGB L1 原值 | 抑制 367 点后 |
|---|---:|---:|
| 0016 | 0.086412 | 0.128179 |
| 0042 | 0.040806 | 0.057443 |
| 0129 | 0.215675 | 0.264682 |

因此 **367 点抑制失败、不启用**；原模型已逐项恢复。条件预测空区不是可靠裁发真值。发际线边界、镜框与未知遮挡不能一律算负票；中心投影进脸也不等于实际可见遮挡。

证据：`backend/.sources/live-complete-repair-20261003-fresh-hair-window-audit/report.json`；`backend/.sources/live-complete-repair-20261003-hair-suspect-counterfactual/report.json` 及其 `local-before/audit.json`、`local-after/audit.json`。工具：`backend/reconstruction_live_hair_window_audit.py`，跨窗计票/同图去重合同测试 5 项通过。

## 4. 本附录允许的结论

可保留：输入身份/尺度核验、正确区分中心与足迹、修正的人物边界口径、辅助合法表面预算不足的独立证据，以及失败候选与其恢复记录。

未证实或不可默认：房间中心前置是当前白雾主因；负监督能补背景洞；单侧导数可修完整轮廓；非联通头发可直接删除；本节旧候选结果可代替最新 density 终态或鸿蒙验收。

剩余几何需要的是有多视图支持的真实背景层连续表面与可见性约束，及真实 hair 外表面/跨窗一致性；不能用 alpha、模板、ED 或单视图分割替代。下一次对当前终态的有限修复，应先按实际共同排序贡献确定前置干扰，冻结不相关人像参数，并同时检查被修改 room 在其它训练视图承担的真实环境内容。此附录不宣称整体画质、完整场景或设备验收通过。
