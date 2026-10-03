# backend —— SELF 重建服务

PC 端两段式重建：Windows 上的 FastAPI 服务（`app.py`，127.0.0.1:8787）负责对话、目录与
`/v1/reconstruction` 采集传输；真正跑 GPU 的建模 worker 在 WSL（`worker.py`），由
`scripts/Start-ReconstructionServer.ps1` 启动。两者不通过 import 通信，只共享一个作业目录
（`SELF_RECON_JOBS_DIR`；worker 强制要求显式设置，未设直接退出，app 端未设时回落到
`%LOCALAPPDATA%/SELF/Reconstruction`；启动器把它指到 `backend/.data/reconstruction/`）：
HTTP 服务把上传的采集写成
`job.json` + `capture.mp4`，worker 轮询目录、建模、把产物写回同一个作业目录。

一篇文档讲清楚三件事：**每个文件是干什么的**（开头速查表一行一个文件；第五节、第六节逐个文件细讲）、
**它是被谁调用、以什么方式加载的**（每个文件条目的"被谁调用 / 加载方式"两行）、
**有没有哪个文件其实没人用**（第四节：没有，67 个根模块全部可达）。

服务源码里不做像素处理；浏览器/平板只走 HTTP。风险边界见 `contracts.py` 与 `recon_transfer.py`
的说明。

## 速查表：每个程序负责什么

67 个根目录程序一行一个（按第五节的分组与顺序排列）。详细职责、"被谁调用"与
"加载方式"见第五节、第六节逐文件条目。

| 分组 | 文件 | 主要负责 |
|---|---|---|
| HTTP 服务链 | `app.py` | FastAPI 服务入口：`/health`、文字对话 `/v1/conversations`、编辑计划 `/v1/edit-plans`，并装配 `/v1/reconstruction` 路由 |
| HTTP 服务链 | `care_catalog.py` | 有来源的护理选项目录：13 品类通用用法、护理意图与拒绝/反馈识别、按圈选部位推荐品类并生成可选项 |
| HTTP 服务链 | `contracts.py` | AI 边界协议与确定性校验：严格 Pydantic 线协议；`validate_plan` 承载全部硬约束；导出 `propose_edit_plan` 工具 schema |
| HTTP 服务链 | `deepseek_client.py` | DeepSeek 编辑计划调用与解析：加载 `.env`、组装上下文与图像、POST `/chat/completions`、解析并至多修复重试一次 |
| HTTP 服务链 | `product_catalog.py` | 审校过的大陆渠道产品查询：延续词接上下文、关键词命中排序取前 3、"请求产品真实效果"识别 |
| HTTP 服务链 | `product_knowledge.py` | 74 条产品身份与档案的唯一 join 层：`identity_index`、`product_detail`、名称归一化精确匹配 |
| HTTP 服务链 | `recon_transfer.py` | `/v1/reconstruction` 采集传输：建作业、1 MiB 分块上传（摘要校验）、封存拼接、心跳健康、资产下载与取消 |
| HTTP 服务链 | `response_quality.py` | 回复环路检测器：句内/历史重复、相似度 ≥0.84、子串与句子集合判定，只判不改写 |
| HTTP 服务链 | `story_conversation.py` | 既有肖像上的纯文字对话：五类意图分类、canned 免模型直答、模型对话与措辞红线 |
| 测试依赖 | `live_depth_scale.py` | 条件深度尺度审计库：按物理点 5 折分窗、每窗单一尺度拟合与验证门限、完整审计入口 |
| 测试依赖 | `run_live_body_appearance_trial.py` | 人工诊断脚本（非发布）：恢复人物监督后只训 body 外观 120 步，前后审计并导出候选 PLY |
| 测试依赖 | `run_live_face_capacity_trial.py` | 人工诊断脚本（非发布）：Rctrl/Rcap 面部容量两臂对比（同种子同预算），bitwise 回滚断言与三指标汇总 |
| 测试依赖 | `run_live_skin_compositing_trial.py` | 人工诊断脚本（非发布）：同几何双背景下只训皮肤外观合成，前后审计并导出候选 PLY |
| legacy 训练链 | `schedule.py` | 纯函数训练调度器：每步给出 (view, mode)，保证每个视角都被 scene/face 两种模式轮到 |
| legacy 训练链 | `train_joint.py` | legacy 人物+房间同一高斯场景训练器：掩膜投票打标签、按调度轮换训练、按 lineage 导出 PLY+provenance |
| 算法闭包 | `appearance_direction_contract.py` | degree-1 SH 头局部颜色 ↔ 冻结 GS PLY 的坐标/方向契约：SH1 基、旋转与系数换算 |
| 算法闭包 | `capture_reference.py` | 唯一捕获参考挑选：±1.75 s 近时窗口 ≥3 训练视图、真实基线/头距比门槛，失败抛结构化收据 |
| 算法闭包 | `capture_registration.py` | 近时窗口的有界静态 2D-3D 定位：地图哈希、物理点折分、掩码 SIFT 投票与留出集验收 |
| 算法闭包 | `checkpoint.py` | 安全 checkpoint 读取/恢复：哈希预检、numpy 白名单反序列化、逐张量 torch.equal 复核 |
| 算法闭包 | `code_identity.py` | 实现确定性指纹：AST 递归展开 52 文件闭包并逐个 SHA-256，合成 `implementationSha256` |
| 算法闭包 | `components_v2.py` | 研究用组件观测+支撑几何准备：掩码/矫正观测、局部拟合、尺度对齐、三角化种子与 `load_prepared` |
| 算法闭包 | `face.py` | 保守头部掩码与面部观测：mediapipe 模型哈希校验、头包络/皮肤掩码、7 类部件标签与数值 QA |
| 算法闭包 | `flame_open_model.py` | 最小隔离的 FLAME 2023 Open 前向模型：pkl 哈希校验、LBS+姿态修正前向、105 点嵌入 |
| 算法闭包 | `joint_visibility.py` | 人物+环境 GS 共享可见性诊断：`posed_points`、一次光栅化双贡献通道、守恒误差检查 |
| 算法闭包 | `live_dense.py` | DA3 深度推理总控：工具源码锁、depth-only 推理、room/hair/body 高斯种子生成与算法快照 |
| 算法闭包 | `live_dense_contract.py` | 深度研究互操作纯工具库：哈希/刚体与相机工具/参数别名补全（部分函数无调用点） |
| 算法闭包 | `live_face_domain.py` | 语义观测 → 观测面部域：连通皮肤成分与空域认定、激活重建训练面/肤掩码、恢复重放 |
| 算法闭包 | `live_fullframe.py` | native-fullframe 兼容转发入口：重导出别名与版本、拒绝 joint_steps≠0、原样转调 `pipeline.run` |
| 算法闭包 | `live_hair_composite.py` | 冻结场景的观测头发外观标定：只训头发 sh/opacity、掩码梯度限制、其余参数位级不变断言 |
| 算法闭包 | `live_hair_motion.py` | 参考系相对的关节 1 头发输运：颅骨刚体近似、参考帧单位阵、协方差/SH 完整输运与收据 |
| 算法闭包 | `live_neck_appearance.py` | 可继承颈部 SH 挑选：全画布光栅化贡献、保护区互斥、≥3 支持视角阈值与选择收据 |
| 算法闭包 | `live_neck_motion.py` | 头与准静态身体间的颈部皮肤输运：平滑权重与雅可比、完整协方差、极分解 SH 旋转 |
| 算法闭包 | `live_opaque_person.py` | 不透明人物训练合同：三区互斥腐蚀掩码、条件颜色与结构误差、有界不透明损失 |
| 算法闭包 | `live_prepare.py` | 逐次拍摄观测准备：真实帧选择、静态相机恢复、FLAME 局部拟合、外观先验与三角化种子 |
| 算法闭包 | `live_room_completion.py` | 已观测房间有界补全：最多 2 参考贪心选择、共享表面求解、增量导出与验证重放 |
| 算法闭包 | `live_room_reference.py` | 房间参考资格评估与排序：fit/held 折分、哈希与相机一致性核验、最多取 2 个参考 |
| 算法闭包 | `live_room_retry.py` | 已失败房间窗口的第二参考重试：严格预算合同、只发起一次求解、收尾不覆盖首轮结果 |
| 算法闭包 | `live_room_self_reference.py` | 旧自身深度票作负证据的有界重放：默认不动作、显式授权、证据逐位核对 |
| 算法闭包 | `live_room_window_recovery.py` | 被拒锚定窗口的有界恢复：提案收据、保守重叠验收、未覆盖观测转正 |
| 算法闭包 | `live_shared_room_surface.py` | 有界 CPU 共享房间表面修正：低维逆深度残差、条件初始化交易、活线适配器 |
| 算法闭包 | `live_skin_compositing.py` | 冻结几何的观测皮肤合成恢复：黑白底一致性、保护掩码、只训 sh/opacity、失败整体回滚 |
| 算法闭包 | `live_surface_binding.py` | 表面组件交付适配层：逐字段/逐面证据校验、环境合并、头发先验替换 |
| 算法闭包 | `live_surface_footprint.py` | 可选新鲜先验皮肤协方差：语义连通区采样密度、切向协方差适配、最多 4 轮回退 |
| 算法闭包 | `local_sampling.py` | 确定性局部采样器：修复偶数观测的几何相位混叠，附收据模拟与不变量保证 |
| 算法闭包 | `observation_domains.py` | 逐帧标签 → 矫正物理观测域：置信度门槛、room/cloth/skin 域、幂等挂载 |
| 算法闭包 | `observations.py` | 每作业帧/脸/世界证据打包：frame_selection 校验、逐帧哈希与相机标注、observation_bundle.json |
| 算法闭包 | `observed_surface.py` | 观测域+有限表面支撑（--surface-refine）：Delaunay 加密、静态平面候选、去重并入假设 |
| 算法闭包 | `person_supervision_state.py` | 非 Parameter 训练契约恢复：三方哈希一致、先验证后变异、证据文件逐字节复制 |
| 算法闭包 | `portrait_model.py` | 可复用照片驱动人像模型：四元数/SH 数学、网格行走、LocalPortraitModel 与候选交易回滚 |
| 算法闭包 | `portrait_pipeline.py` | 人像优先重建主引擎：场景装配、三档渲染、训练与审计、候选导出与算法源码快照 |
| 算法闭包 | `portrait_preview.py` | 从 PLY 生成静态预览：256×256 PNG、3D/全场景 LOD 采样、大小上限与原子替换 |
| 算法闭包 | `pose.py` | 人脸姿态测量：canonical 顶点校验、PnP RANSAC+LM、medoid 参考系与姿态质量报告 |
| 算法闭包 | `probe_flame_observations.py` | 研究探针：FLAME 局部/世界观测严格分离，"根旋转只应用一次"契约校验 |
| 算法闭包 | `probe_flame_open_fit.py` | 研究探针：FLAME Open 共享身份拟合到私域 landmark，训练/留出报告 |
| 算法闭包 | `probe_flame_real_appearance.py` | 研究探针：三角面绑定 GS 外观采样，三重可见性过滤、留出帧像素排除 |
| 算法闭包 | `probe_gs_contract.py` | 契约探针：gsplat→标准 PLY→解析回 gsplat 的无损往返验证（`read_float_ply` 供生产复用） |
| 算法闭包 | `probe_portrait_components.py` | 研究探针：2D 六类部件掩码+高分辨率头发掩码，两套掩码分歧测量 |
| 算法闭包 | `probe_static_alignment.py` | 研究探针：静态 vs 人物混入 SfM 的相机一致性比较（中心/朝向残差统计） |
| 算法闭包 | `runtime.py` | 测试引擎路由与执行回执：预算与开关校验、源码未变验证、子进程训练组织、心跳身份比对 |
| 算法闭包 | `scene.py` | 世界坐标房间/衣物观测恢复：环境掩膜、前景净空、实测深度种子与静态表面三角化 |
| 算法闭包 | `shared_v2.py` | 五部件共享前向试验原型：initialize/boxes/mesh_depth、ComponentStrategy 训练与审计 |
| 算法闭包 | `static_planes.py` | 测量 track 支撑的静态平面假设：SVD 平面分组、凸包内采样、多视图颜色认同 |
| 算法闭包 | `surface_density.py` | 有界切向表面分裂（--surface-refine）：父点选择、双子点复制、Adam 状态整体搬移 |
| 算法闭包 | `surface_recovery.py` | 表面初始化证据留存与迁移：哈希校验复制、证明闭包保留、跨平台路径、checkpoint 反查 |
| 算法闭包 | `train.py` | 早期单场景 gsplat 训练器：smoke 自检、`load_scene`、`observed_head_splats`、头部掩膜训练与导出 |
| 算法闭包 | `view.py` | 开场机位推导与覆盖证明：注视中心/fov 反推、前 1/5 帧挑帧、broadSideCoverage 统计 |
| 算法闭包 | `worker.py` | WSL 常驻重建 worker：轮询作业、SHA-256 校验、引擎选路、隔离子进程、flock 单实例与心跳 |

## 一、运行拓扑

```
平板 / 浏览器
   │  HTTP（Bearer；本机 loopback 开发模式可免）
   ▼
Windows: app.py (uvicorn)  ──写入──▶  backend/.data/reconstruction/<jobId>/
   │                                        job.json, capture.mp4, chunks/
   │  scripts/Start-ReconstructionServer.ps1
   ▼                                        ▲
WSL: worker.py（常驻单进程，flock 单实例，心跳写 worker_status.json）
   │  校验 capture 字节数 + SHA-256（fail-closed）
   │  读 engine-profile.json 选路
   ├─ native-fullframe（当前）：runtime.reconstruct_test → 子进程 live_fullframe.py
   │     └─ 52 个文件组成的算法闭包，按固定哈希校验后才允许运行
   └─ legacy（gsplat-colmap）：worker.py:331 子进程 train_joint.py（连带 schedule.py）
   ▼
产物：gaussian.ply / preview.png / preview3d.ply / scene3d.ply / view.json
```

- **app 进程**：`uvicorn` 按 `app:app` 路径加载，启动即装配路由；只做 HTTP 与文件落盘。
- **worker 进程**：`worker.py:542` 会把自身按路径再启动为隔离的作业子进程（supervise_job），
  所以同一份代码既是常驻循环也是子进程入口。
- **算法闭包**：`code_identity.py` 用 AST 导入闭包把 52 个文件钉成一个哈希
  `adb15d15206d565d1543b5d4484d723f42bb3f213b0becabc8d84f6432f167b9`（2026-10-03 换行改写后的现行值）。
  被钉住的文件改一个字节，服务就拒绝产出（`ValueError: test_source_hash_changed`）。

## 二、命名规则与固定哈希（2026-10-03 改名）

在役模块统一去掉 `reconstruction_` 前缀（`worker.py`、`live_fullframe.py`、`code_identity.py` …），
测试统一为 `backend/tests/test_*.py`；本就不带前缀的 `app.py`、`recon_transfer.py`、`probe_*.py` 等不动。
历史批次保留旧名，见 `archive/README.md`。

改名改变了闭包的固定哈希（`fa53df8abce1d19d03417ac0e8c2b189f187a6713a2ff508c5b0e0195ca9daef` →
`e7040005a447ed672a43a6f1dd1d51619b3845c6e8d2e08a4c2def76ad65fcab`），
同日的换行改写（44 个文件、2005 处断行，仅插入换行不改进 token/AST）再次改变
（`e7040005…` → `adb15d15206d565d1543b5d4484d723f42bb3f213b0becabc8d84f6432f167b9`），
`backend/.data/reconstruction/engine-profile.json` 两次均已同步重钉；
服务重启后 worker 心跳 `loadedImplementationSha256 = currentImplementationSha256 =
profileImplementationSha256`，`sourceIdentityVerified=true`。改名前后的完整证据（映射表、
双环境测试 A/B、真实端到端作业）在 `docs/evidence/backend-rename-20261003/`，
换行改写的等价性证明与验证在 `docs/evidence/backend-reformat-20261003/`。
本 README 对 `backend/*.py` 的行号引用（如 `runtime.py:67`）以换行改写前的提交 `886f84e` 为基准；
改写后 44 个文件的行号有位移，换算表见 `docs/evidence/backend-reformat-20261003/line-map.json`。
对 README 自身命令的引用一律用节名（如"第三节"），不随行号变化。

**勿动**：第五节的 52 个闭包文件是哈希钉死的；要改必须与 `engine-profile.json` 一起重算重钉。

## 三、常用命令

```cmd
:: 启动服务（WSL worker + Windows API；文档化的唯一入口）
powershell -File scripts\Start-ReconstructionServer.ps1

:: 跑测试（Windows，快；venv 缺 torch/cv2/scipy，相关模块报 ModuleNotFoundError，属环境不属回归）
backend\.venv\Scripts\python.exe -m unittest discover -s backend -p "test_*.py"

:: 验哈希（应输出下面的固定值）
backend\.venv\Scripts\python.exe -c "import sys;sys.path.insert(0,r'D:\STUDY\College\mine\olay\backend');import code_identity as c;print(c.source_identity()['implementationSha256'])"
```

```bash
# 跑测试（WSL 完整 GPU 环境）
wsl -d Ubuntu-22.04 -- bash -lc 'cd /mnt/d/STUDY/College/mine/olay/backend && /opt/self-reconstruction/venv/bin/python -m unittest discover -s . -p "test_*.py"'
```

基线（2026-10-03 改名后）：Windows 139 用例 / 34 错误；WSL 295 用例 / 13 错误。
全部错误都是环境缺包（Windows 缺 torch/cv2/scipy；WSL venv 缺 fastapi/httpx/PIL），
没有项目模块缺失。

发一个真实作业（五步 HTTP 协议，另有可复用脚本记录在证据目录）：
`POST /v1/reconstruction/jobs`（totalBytes + sha256 + format）→ `PUT` 1 MiB 分块
（带 `x-content-sha256`）→ `POST .../seal` → 轮询 `GET /jobs/{id}` 直到 `gaussian_ready` →
下载 `assets`。

## 四、调用关系总览：所有模块都被调用了嘛？

**结论：67 个根模块全部有真实引用，没有孤儿；但“模块被引用”不等于“每个函数都被调用”——确有一批函数无调用点，见下表后的函数级补注。** 按“被引用”的成色分：

| 可达入口 | 模块数 | 含义 |
|---|---|---|
| `app.py`（HTTP 服务） | 10 | uvicorn 启动即加载（含 `portrait_preview.py`，它同时是闭包成员） |
| `worker.py`（WSL worker） | 54 | worker 启动或作业执行时加载；**52 个闭包成员全部在内** |
| 仅测试引用 | 4 | 生产路径不加载：`live_depth_scale.py`（被 `test_live_dense.py` 真实导入）与三个 `run_live_*_trial.py` 试验脚本（测试只按路径读源码做 AST 校验） |
| 合计 | 67 | 无零引用模块 |

**函数级补注**（2026-10-03 对抗性核验：对全仓库含 `.gitignore` 屏蔽的 `archive/`、`.sources/` 逐名 grep 再回源比对）——下列函数在现役源码树内**没有任何调用点**：

- `live_dense.py`：`rebuild_room_confidence`、`append_hair_prepared`、`append_body_prepared`、`infer_reference_world`（全仓库唯一命中即定义处）；
- `live_dense_contract.py`：`classify_depth`、`validate_manifest`、`validate_surface_source`（`archive/v5` 里另有同名自备实现，属旧副本自身，不是对本模块的调用）；
- `scene.py`：`environment_view_support`、`recover_environment_points`（仅见 `.sources` 快照与 `archive/v1` 旧名副本内部）；
- `shared_v2.py`：`train`、`audit`；`components_v2.py`：`prepare`、`supported_cloth`、`triangulated_garment`（现役 import 名单里都没有它们；只有 `.sources` 旧副本与 `archive/v3` 调用旧名模块的副本）；
- `live_depth_scale.py`：`audit_calibration`。

它们所在的**模块**仍被现役链加载并使用其他函数（如 `components_v2.load_prepared`/`write_json`、`shared_v2.initialize`/`boxes`），属研究整合批次留下的无调用函数，不是整模块孤儿。

三个**看起来像"调用"其实不是**的地方，读代码时别被误导：

1. **快照副本**：`live_dense.py`、`live_room_*.py` 等用 `shutil.copyfile` 把同伴模块复制进
   算法源快照目录（留证用），不是执行它。
2. **必需文件清单**：`runtime.py:67-69` 的 `required` 元组是哈希契约里的文件名列表，不是 import。
3. **ROOTS 元组**：`code_identity.py:12-13` 把文件名列进闭包哈希清单，也不是 import。

两类特殊存在，保留原因明确：

- **`schedule.py` / `train_joint.py`**：只走 legacy 引擎分支（`engine-profile.json` 选
  `gsplat-colmap` 时才执行）；当前 profile 是 `portrait-first-soft-surface-test`，日常不运行，
  但 `worker.py:331` 的启动路径在，删不得。
- **三个 `run_live_*_trial.py`**：目前引用了已归档模块（`reconstruction_live_body_appearance`
  等，归档发生在改名之前的 de40953），自身不可运行；保留是因为
  `tests/test_person_supervision_state.py:113` 会读取它们的源码做 AST 校验。

## 五、文件清单

根目录 67 个在役程序分四组：服务链 9、测试依赖 4、
legacy 训练链 2、算法闭包 52。每个文件给出职责、"被谁调用"（带文件:行号）
与"加载方式"（常驻 / 按需 / 子进程入口 / 仅测试 / 仅快照引用）。

### 5.1 HTTP 服务链（9）

对话、目录、质量闸门与 `/v1/reconstruction` 采集传输。全部由 `app.py` 在服务启动时装配。

#### `app.py`

FastAPI 服务入口与两个 HTTP 端点。第16行创建 FastAPI 应用（docs_url/redoc_url 关闭），第17行把 recon_transfer 的 /v1/reconstruction 路由整体装配进来。端点：/health（29-31）返回进程存活与 DEEPSEEK_API_KEY 是否已配置；/v1/conversations（33-73）纯文字对话，经 SELF_BACKEND_TOKEN Bearer 或 SELF_DEV_LOOPBACK=1 本机回环鉴权，60 秒内限 12 次且并发限 2，请求体流式读取 ≤32 KiB，按 requestId 去重（409 request_in_progress），客户端断开即取消任务（499 client_cancelled），ModelFailure 映射 502；/v1/edit-plans（75-140）编辑计划，body ≤11 MiB，只接受字段集恰为 {snapshot, images} 的 JSON（1~2 张 base64 图），以原始请求体的 sha256 按 requestId 做幂等缓存（最多 64 条，同 id 不同体返回 409 request_id_reused），调用 deepseek_client.propose 后回填缓存。24-27 行的 RequestValidationError 处理器只返回 {"error":"invalid_request"}，避免回显可能含图片或用户原话的报错输入。18-22 行维护进程内 recent/completed/inflight 与 story_recent/story_inflight 状态。

- **被谁调用**：启动方（图 JSON 不含 scripts）：scripts/Start-Backend.ps1:8 与 scripts/Start-ReconstructionServer.ps1:50 执行 `python -m uvicorn app:app --host 127.0.0.1`。导入方（与图 JSON per_module.app.py 的 4 条入边逐条吻合）：backend/tests/test_http.py:7（import app as server）、backend/tests/test_recon_transfer.py:13、backend/tests/test_scene_preview.py:14（from app import app）、backend/tests/test_story_conversation.py:9（import app as server）。
- **加载方式**：子进程入口（uvicorn 按 app:app 路径加载，服务进程启动即执行；两个启动脚本均如此）为主；同一进程内常驻（其顶层 import 的 contracts/deepseek_client/story_conversation/recon_transfer 随启动一并加载）；叠加仅测试（4 个测试用 TestClient 挂载）。
#### `care_catalog.py`

有来源的护理选项目录，docstring 声明其中没有任何一条是已标定的外观效果。导入即从 product_knowledge 取 RECORDS 与 exact_identities（3行）。_ROUTINES/_ROUTINES_EN（5-34）覆盖 13 个品类的通用用法（cream/serum/eye/sunscreen/cleanser/toner/emulsion/mask/set/body_lotion/body_scrub/body_cleanser/body_tint），全部以实物包装为准，不给用量与频次。care_intent（39-42）识别保养/养护/护理/护肤/眼霜/防晒/清洁及痘、泛红、干燥等关键词；products_declined（45-46）与 care_feedback（49-50）识别拒绝推荐和刺痛/过敏/太贵/已有产品等反馈。care_options（53-99）：未启用、已拒绝、有负面反馈、唇/眉/口红/眼影类、纯选项数字（1/2/3/试试）时返回 []；按 area/concern/关键词映射品类集合（痘→cleanser+cream 且洁面排前、注明不是祛痘治疗；防晒→sunscreen；眼→eye；身体→body_*；无 area 时预置全部面部品类含 eye）；只从 record_status ∈ {brand_2026_observed, catalog_only} 的记录生成 {productId,name,category,source,ordinaryUse}。allowed_care_ids（102-103）供 validate_plan 校验 careGuide；care_usage（106-107）按品类返回审校用法；care_reason（110-128）生成选它的理由，痘场景返回“保湿/清洁不是祛痘治疗”的诚实措辞。

- **被谁调用**：图 JSON 4 条入边全部核实：contracts.py:5、deepseek_client.py:15、story_conversation.py:15、backend/tests/test_care_conversation.py:11。实际调用点含 contracts.validate_plan（100-234 内经 allowed_care_ids/care_options/care_reason/care_usage）、deepseek_client.request_body:56、story_conversation.answer_without_model:126 与 converse:175。
- **加载方式**：常驻（app 启动链 contracts.py:5 → care_catalog；deepseek_client.py:15 与 story_conversation.py:15 也都是顶层 import）；叠加仅测试。
#### `contracts.py`

AI 边界的协议与确定性校验层，docstring 声明只有候选方案能穿过这条边界、授权与像素留在手机。用严格 Pydantic（StrictModel extra=forbid/strict，8-9行）定义全部线协议：Region/Layer/DialogueTurn/Snapshot（33-58：requestId 有限字符集、regions ≤32、layers ≤8、dialogue ≤3、uploadAuthorized 必须为 True、图像 8–2048）、Operation（60-66：set_digital_tint/set_effect_level/remove_effect，productProfileId 强制为空串，因为当前没有标定的产品档案）、CareGuide、SelectionObservation、Plan（80-89：decision 四值、operations ≤4）。catalog_language（12-14）：目录用词只有 zh/en，ja/ko 呈现读英文源。listening_only（95-98）识别“只想聊聊/不用修改”等。validate_plan（100-234）承载全部硬约束：listening-only 时禁 edit；把 presetId 映射成展示色名（柔玫瑰/暖陶棕）并在回复出现内部 ID 时拒绝；clarify 之外禁问句；护理剂量/频次、被拒仍推销、护理被替换成试色等模式拒绝；selectionObservations 必须与本次圈选区域一一对应、uncertain 必须 area=unknown；careGuide 必须来自 allowed_care_ids 且 whyHere/howToUse 强制替换为审校文案，出现保证/立刻/复刻等未标定措辞即拒；requests_product_effect 或 explanationRefs 非空时禁 edit（product_effect_not_calibrated）；痘/疤禁做 skin edit；图层/区域/预设/新层一致性；choices 与 stale_choice、ambiguous_numeric_reply；explanationRefs 只能引用已给产品资料或本次 careGuide。TOOL（236-240）导出 propose_edit_plan 的 function schema 供模型 function calling。

- **被谁调用**：图 JSON 7 条入边全部核实：app.py:11、deepseek_client.py:13、story_conversation.py:12、backend/tests/test_care_conversation.py:12、test_contracts.py:7、test_live_dialogue.py:4、test_product_catalog.py:6。我自己的 grep 另找到图外调用者 scripts/export-model-contract.py:5（from contracts import Plan,Snapshot,PRESETS,LEVELS，把两份 schema 与 effect registry 写出 shared/contracts/）——图 JSON 只扫 backend 根与 backend/tests，scripts 不在扫描范围，故该入边缺席。
- **加载方式**：常驻（app.py 顶层 import，服务启动即加载；deepseek_client、story_conversation 也顶层依赖它）；叠加仅测试（4 个测试导入）。
#### `deepseek_client.py`

编辑计划的 DeepSeek 调用与解析层。导入时执行 load_dotenv(backend/.env, override=False)（19行）。PLANNER_SYSTEM（21-30）是长中文系统提示：先判护理意图、对照两张图填写 selectionObservations、产品事实只来自所给资料、calibratedProductEffects 为空、只提交候选不执行。ModelFailure（32-33）只含公开错误类别，绝不携带上游响应体或图像。checked_image（35-48）限制图像 ≤5 MiB、仅 PNG/JPEG、边长 8–2048 并 verify。request_body（50-96）组装上下文：snapshot 去掉 uploadAuthorized，加 presets、productInformation（product_catalog.lookup）、careOptions、productIdentityIndex（74 条身份）、requestIntent、imageMeaning，图像转 data URL；请求 thinking=disabled、max_tokens 2000、tools=[TOOL]、tool_choice 强制 propose_edit_plan；listening_only 时换陪伴版提示，responseLanguage≠zh 时替换措辞并追加对应语言指令。parse_response（98-111）要求恰好 1 个 propose_edit_plan 工具调用、arguments ≤16 KiB，随后交给 contracts.validate_plan。propose（113-169）校验 DEEPSEEK_API_KEY、DEEPSEEK_MODEL（默认 deepseek-flash）、DEEPSEEK_BASE_URL 必须 https，POST /chat/completions（连接超时 10 秒、请求 45 秒、全局预算 48 秒）；计划无效或回复重复、漏填观察时最多在同一快照内修复一次；成功返回 plan + modelEvidence（requestedModel/returnedModel/systemFingerprint/elapsedMs/usage/providerResponseId）。

- **被谁调用**：图 JSON 12 条入边全部核实：app.py:12、story_conversation.py:11，以及 backend/tests/test_care_conversation.py:13、test_contracts.py:8、test_http.py:9、test_live.py:8、test_live_care.py:8、test_live_dialogue.py:5、test_live_http.py:10（该行注释说明专门为加载 .env 而 import）、test_live_language.py:4、test_live_voice.py:4、test_product_catalog.py:7。实际调用：app.py:123 的 /v1/edit-plans 调 propose。
- **加载方式**：常驻（app 进程启动顶层导入，且 import 即读 backend/.env）；叠加仅测试（10 个测试导入，其中 test_live_http.py:10 专为此）。
#### `product_catalog.py`

审校过的大陆渠道产品资料查询层，docstring 要求未知配方必须保持未知。导入即读 shared/products/olay-cn-catalog.json（7行，实测 8 条记录）。lookup（9-29）：先精确身份（product_knowledge.exact_identities）；“1/2/3”或“这款/它/试一下/成分/为什么/用法”等延续词且带 productContextIds 时先接上下文产品；没有显式品牌/产品词且非延续语境就返回 []；按 keywords 命中数排序取前 3，并用 score>0 过滤与 22-24 行注释拒绝把泛称 OLAY 当作推销任意记录的理由；输出字段为 productId/name/market/specification/usageSummary/source/retrievedAt/evidenceType/recordKind/availability/inci/formulaRevision/physicalParameters/efficacyCalibration。allowed_refs（31-32）供 validate_plan 限定 explanationRefs。requests_product_effect（34-51）：识别“用产品做出真实效果”的请求；“通用数字试色 + 另一件独立的 OLAY 护理问题”与明确“不按产品”的通用试色按例外返回 False，点名品牌（olay/玉兰油/小白瓶/超红瓶/黑管）即 True。

- **被谁调用**：图 JSON 5 条入边全部核实：contracts.py:4、deepseek_client.py:14、story_conversation.py:13、backend/tests/test_care_conversation.py:14、test_product_catalog.py:5。实际调用点：contracts.validate_plan:141,198、deepseek_client.request_body:55、story_conversation.answer_without_model:124 与 converse:178。
- **加载方式**：常驻（导入即解析 JSON；app 顶层链 contracts/deepseek_client/story_conversation 均依赖）；叠加仅测试。
#### `product_knowledge.py`

74 条研究身份与产品档案的唯一 join 层（docstring：全部 74 条可检索；历史/搜索身份保持标注，绝不作为主动推荐或外观参数）。导入即读 shared/products/audit-v2/products_cn.json 与 product_dossiers_cn.json（实测各 74 条），两边键集合不一致直接 RuntimeError('product_dossier_join_incomplete')（10-14）。identity_index（21-26）给 AI 传 {productId,name,category,family,status,source,recommendable}，recommendable 仅对 brand_2026_observed 与 catalog_only 为 True。product_detail（29-42）join 出 facts/claims/ingredientHighlights/offers/sourceLinks/fieldCoverage，并强制 efficacyCalibration=None、canRenderProductEffect=False、availability=not-verified、specification 以实物包装为准。exact_identities（45-50）：名称归一化（去非单词字符 + casefold）后做子串匹配，仅名称归一后 ≥4 字符的参与，按长度降序取前 3。contextual_products（53-54）把最多 3 个上下文 id 转成档案。

- **被谁调用**：图 JSON 5 条入边全部核实：care_catalog.py:3、deepseek_client.py:16、product_catalog.py:5、story_conversation.py:14、backend/tests/test_care_conversation.py:15。实际调用点：deepseek_client.request_body:57（identity_index）、story_conversation.converse:178（identity_index）、care_catalog 及 product_catalog 的查询函数。
- **加载方式**：常驻（app 启动经 care_catalog/product_catalog 顶层链加载；导入时读两份 JSON 并做 74/74 join 校验，不一致直接使进程启动失败）；叠加仅测试。
#### `recon_transfer.py`

重建采集的私有可续传传输层，docstring（1-5行）声明不把上传片段当重建结果、只有单独校验过的重建 worker 才能发布资产；第24行 APIRouter 前缀 /v1/reconstruction。数据根 _default_jobs_root（25-33）：Windows 用 %LOCALAPPDATA%\SELF\Reconstruction，其他平台用 XDG，可被 SELF_RECON_JOBS_DIR 覆盖。鉴权 _authorize（48-58）：Bearer SELF_BACKEND_TOKEN，或 SELF_DEV_LOOPBACK=1 且客户端为 127.0.0.1/::1/testclient。端点：create_job（122-151）校验清单 {totalBytes,sha256,format=mp4}、总长 1 KiB~1 GiB、建 0700 作业目录、state=receiving；put_chunk（154-197）校验 x-content-sha256 与精确块长、每作业 threading.RLock、临时文件原子改名、重复上传做一致性检查、进度封顶 25；seal_job（200-228）要求 0..count-1 块齐全，顺序拼接并流式 SHA-256，总大小与整文件摘要复核后原子生成 capture.mp4、state=queued 并删除分块；health（91-108）读 worker_status.json 心跳（ready 且 updatedAt 距今 <30 秒才报 engine=ready，并附 algorithm/algorithmVersion）；echo（111-119）1 MiB 二进制回环验收并回 X-Content-SHA256；job_status（231-240）；ensure_scene_preview（243-272）仅在 gaussian_ready/complete 且 gaussian+view 资产校验通过时，函数内按需 import portrait_preview.create_scene_lod 回填 scene3d 并清删旧版 scene v1/v2 文件；cancel_job（275-298）写 cancel.requested，receiving/failed 直接墓碑化并丢弃素材，其余转 cancel_requested 交给 worker 监督进程回收；asset/asset_chunk（301-346）经 _verified_asset（309-331：kind 白名单、作业状态、文件名必须等于 basename、sha256 格式、按 kind 的大小区间、真实尺寸与摘要全核对）；delete_job（349-357）运行中拒删。

- **被谁调用**：backend/app.py:14（顶层 from recon_transfer import router，app.py:17 include_router 装配）；backend/tests/test_recon_transfer.py:12、backend/tests/test_scene_preview.py:13。与图 JSON per_module.recon_transfer.py 的 3 条入边完全一致（in_app=true）。被调用的实际触发点：HTTP 客户端对 /v1/reconstruction/* 的请求（无仓内调用者，路由本身即入口）。
- **加载方式**：常驻（app 进程启动经 app.py:14 顶层 import 即加载并装配路由）；模块内 portrait_preview 的 import 为按需（仅 ensure_scene_preview 分支）；叠加仅测试。
#### `response_quality.py`

回复环路检测器（docstring：在回复到达用户前拒绝重复句）。normalized（6-7）去掉非单词字符并 casefold。repeats（10-28）：先查新文本内部是否有重复句（仅统计 ≥10 字的句子）；再逐条历史比对——完全相同、SequenceMatcher 相似度 ≥0.84、新文本（≥6 字）是旧文本子串、或新文本全部句子都出现在旧句集合，命中任一即 True。它只做布尔判定、不改写回复：deepseek_client.propose（:146）据此对重复的 plan/question 草稿做一次修复重试，仍重复即 ModelFailure('repeated_response')（:152-153）；story_conversation.converse 在 canned 直答与历史重复时跳过直答、改走模型生成（:146），并对模型输出的重复句追加纠正提示重试一次（:197-201）。

- **被谁调用**：图 JSON 3 条入边全部核实：deepseek_client.py:17、story_conversation.py:16、backend/tests/test_care_conversation.py:16。实际调用点：deepseek_client.py:146；story_conversation.py:146、:197（answer_without_model 不调用 repeats）。
- **加载方式**：常驻（经 deepseek_client 与 story_conversation 的顶层链在 app 启动时加载）；叠加仅测试。
#### `story_conversation.py`

既有肖像上的纯文字对话（docstring：无图像、无编辑权限），由 app.py 的 /v1/conversations 调用。19-64 行定义严格模型：Turn/ConversationRequest（requestId 必须匹配 story-…、sessionId 必须 session-…、assetId 为 32 位 hex、turns ≤4、productContextIds ≤3）/ConversationResponse，校验器拒绝 data:image、base64,、file_id、图片 URL 等内嵌媒体。classify（67-79）分五类：real_effect_boundary（点名品牌+真实效果）、closing（结束语）、product（点名品牌或护理意图）、edit_entry（试色/数字预览/柔玫瑰/暖陶棕）、conversation。CANNED（82-107）提供 zh/en/ja/ko 四种 canned 文案。answer_without_model（110-141）：closing/real_effect_boundary/edit_entry 免模型直接返回（真实效果边界类设 canOfferDigitalPreview=True）；product 类恰好 1 个目录命中时返回名称+用法摘要+来源+evidenceRefs，否则回退 care_options 给一件可选护理，再不行回“你说的是哪一款”。converse（144-214）：先试免模型直答（product 类除外）且与历史去重；无 key 报 missing_key；系统提示词规定不描述五官/不诊断/不假装保存或修改，注入 productIdentityIndex、productInformation、careOptions、dismissedProducts 并声明仅为数据；max_tokens 600、35 秒超时/40 秒预算；回复 1–400 字，重复时向系统提示追加纠正再试一次；出现“我看到你的/已为你保存/真实效果保证”等措辞即 ModelFailure('ungrounded_conversation')；evidenceRefs 由回复中出现的已给产品名反查（≤2），kind 随有无引用在 product/conversation 间切换。

- **被谁调用**：图 JSON 3 条入边全部核实：app.py:13（顶层 import ConversationRequest、converse，供 app.py:60 的 /v1/conversations 调用）、backend/tests/test_care_conversation.py:17、test_story_conversation.py:10（后者还导入 answer_without_model）。
- **加载方式**：常驻（app.py:13 顶层导入，服务启动即加载）；叠加仅测试。

### 5.2 测试依赖（4，勿归档）

生产路径不加载，但被 `tests/` 引用（导入或按路径读源码），删了测试会红。

#### `live_depth_scale.py`

条件深度尺度审计库（无 __main__、无自动调用链）。fit_window_scale(rows)：按 POINT3D_ID 的 sha256(id)%5 做 5 折“物理点级”划分（同一静态点的重复测量绝不拆开），训练折取 median log(measured/predicted) 得到每窗口单一尺度，验证折要求：相对中位误差≤3%、P90≤8% 且相对事前 P90 劣化≤0.002，另需 ≥20 个训练点 ID、≥12 个验证点 ID、≥3 个验证视角、scale∈[0.5,2]，否则 accepted=False；返回收据明确 perFrameScale=False、cameraChanged=False（:23-36）。audit_calibration(original,supplement,output) 是完整审计入口：读两套 depth-manifest 与 prepared 数据，经 observation_domains/physical_masks 取 room 掩码，从 COLMAP 静态 track 重投影生成锚点（要求 cam_from_world 与录制 C 一致到 1e-7，:43），逐窗口拟合后做 reference 短窗与各世界窗的 overlap 对比，写 report.json，固定 training=False、inference=False，并声明静态重建锚点不是独立传感器深度或房间存在性掩码（:92-95）。

- **被谁调用**：tests/test_live_dense.py:13（顶层 import fit_window_scale，测试 :122 与 :128 直接断言尺度值、接受与拒绝行为）。无 app/worker/脚本引用（usage-graph.json：in_worker=false、in_degree=1 仅为测试）。audit_calibration 全仓库无任何调用者（grep 仅命中定义处 live_depth_scale.py:64），也未提供 CLI。
- **加载方式**：仅测试（只在单元测试中被 import；服务、worker、生产子进程均不加载，也不在 code_identity 的源码闭包内）。audit_calibration 目前只能人工 import 调用。
#### `run_live_body_appearance_trial.py`

人工触发的“body SH 有限预算”诊断脚本（非发布路径）。run(parent,output) 要求 GPU（否则 GPU_unavailable_no_training_claim，:40），父 run 的 config 必须是 opaquePerson=True、soft=True、antialiased=False（:42-43），且 checkpoint 的 surfaceContract/sourceSha256 必须与当前场景一致（:55-56），随后恢复 person supervision；只训练 body 外观 120 步、lr 0.008（restore_opaque_body_appearance，:78），前后各跑 audit_full_scene 与 body_audit（逐区域 region_metrics：opaque_cloth/body_skin/skin、observed_neck_cloth/room、hair/glasses visible），导出候选 PLY；config 明记 extraStepsOnlyForFiniteDiagnosisNotQualityAB=True、notProductionDefault=True，报告 status='diagnostic_not_accepted_or_published'（:69-86）。同时复制 cloth_supported_seeds.npz、person supervision 文件，并把 4 个源文件拷进 output/algorithm-source 快照（:61-68）。

- **被谁调用**：tests/test_person_supervision_state.py:113-121（唯一自动引用：用 ast.parse 读取本文件源码，断言 restore_person_supervision 调用早于 audit_full_scene/select_patch，防止审计顺序回归）。usage-graph.json 的 source-read 入边与之一致。无 app/worker/CI 调用（in_app=false、in_worker=false）。
- **加载方式**：仅测试（唯一自动引用是测试读取其源码文本做 AST 校验）；无自动运行路径，需人工按路径启动（自带 argparse：python run_live_body_appearance_trial.py <parent> <output>，运行时要求 GPU）。现状提示：其顶层 :15 import 的 reconstruction_live_body_appearance 与 body_audit 内 import 的 compare_live_opaque_person_runs 现仅存在于 backend/archive/v5（backend 根目录已无这两个文件），:62 的快照名单也含旧名 reconstruction_live_body_appearance.py——当前工作树直接运行会在 import 或拷快照处失败。
#### `run_live_face_capacity_trial.py`

人工触发的 Rctrl/Rcap 面部容量对比脚本（有限预算、不发布）。run() 校验父场景必须是 soft+antialiased=False 且带 observedFaceDomain+denseSurfaces（:25-28），预算被限制在 steps 24..240、max_parents 8..512、rounds∈{1,2}，越界抛 capacity_budget_outside_finite_reviewed_limits（:29-30）；select_patch 硬阻断时先写 status='selection_hard_block_no_training' 的报告再抛出（:71-74）。两臂（capacity=False 的 Rctrl 与 True 的 Rcap）在每臂开始前重置同一 RNG 种子，跑相同步数；每臂先导出候选 PLY 再回滚，随后逐 key 与父 checkpoint 做 torch.equal bitwise 断言（失败抛 capacity_rollback_incomplete，:95-97），最后汇总 sameFixedRegionComparison（rgb/edge/hole 三指标，:99-105），status='finite_capacity_comparison_complete_not_release_approved'。

- **被谁调用**：tests/test_person_supervision_state.py:113-121（唯一自动引用：AST 源码扫描，要求 restore_person_supervision 出现在 select_patch 之前）。无 app/worker 调用（usage-graph.json：in_app=false、in_worker=false）。
- **加载方式**：仅测试（唯一自动引用是测试读源码做 AST 校验）；无自动运行路径，需人工按路径启动（python run_live_face_capacity_trial.py <parent> <output> --steps/--max-parents/--rounds，要求 GPU）。现状提示：run() 内 :19 import 的 reconstruction_live_face_capacity 现仅存于 backend/archive/v5，:52 快照名单亦为旧名 reconstruction_live_face_capacity.py——当前工作树运行会在 import 处 ModuleNotFoundError。
#### `run_live_skin_compositing_trial.py`

人工触发的“同几何双背景皮肤合成”诊断脚本。run(parent,output,steps=180)：校验父场景为 soft+antialiased=False（face_trial_requires_explicit_soft_classic_parent）并从 checkpoint 恢复，校验 surfaceContract/sourceSha256 一致；调用 live_skin_compositing.restore_skin_compositing 只训练皮肤外观（config 明记 resumeKind='same_full_model_new_Adam_only_skin_appearance'、dualBackdropOnlyOnObservedInteriorSkin=True，:46-49），前后跑 audit_stages/audit_full_scene，导出候选 PLY；报告 status='research_not_release_approved'，并写 algorithm-source 源码快照（含 live_skin_compositing.py、自身、person_supervision_state.py，:38-44）。

- **被谁调用**：tests/test_person_supervision_state.py:113-121（唯一自动引用：AST 源码扫描校验 restore_person_supervision 早于 audit 调用）。无 app/worker 调用（usage-graph.json：唯一入边为 test 的 source-read）。
- **加载方式**：仅测试（唯一自动引用是测试读源码做 AST 校验）；无自动运行路径，需人工按路径启动（python run_live_skin_compositing_trial.py <parent> <output> --steps，要求 GPU）。三个 trial 脚本互相无调用；与另两个不同，本脚本顶层 import 的 live_skin_compositing 与快照名单均为现役新名，引用完整可运行（除 GPU 环境外无断链）。

### 5.3 legacy 引擎训练链（2，勿归档）

`engine-profile.json` 的 engine 为 `gsplat-colmap` 时才会走到；AST 导入闭包看不见
`train_joint.py`（按路径启动），所以它们不在 52 个闭包成员里。

#### `schedule.py`

纯函数训练覆盖调度器，保证每个捕获视角都能被 scene/face 两种模式轮到。training_view_and_mode(step, view_count)（4-18）返回该步的 (view_index, mode)：每 50 步触发一次 full（在 train_joint 里等同 scene，且用 epoch*7 平移避免 view_count 为 50 倍数时总是同几个视角 full）；前 4 个 epoch 每 2 个视角轮一次 scene，之后每 4 个轮一次；epoch 偏移专治"view_count mod 4 == 2 时固定取模饿死一半视角"。参数非法（step<0 或 view_count<1）抛 ValueError("invalid training schedule")。无状态、无 RNG。

- **被谁调用**：train_joint.py:25 顶层导入（读取在 train_joint.py:227 每步调用），是唯一调用方；无测试直接 import schedule（已 grep 确认：tests 中只有 local_sampling 的同名函数 schedule_receipt 命中；graph 的 in_tests 为经 tests→worker→train_joint spawn→schedule import 的传递可达性）。
- **加载方式**：按需（只在 train_joint 子进程启动时随顶层导入加载；属 legacy 训练链，不在 worker 的 import 闭包内）。
#### `train_joint.py`

legacy 引擎链的"人物+房间同一高斯场景"训练器，由 worker 直接按路径启动。它把统一 COLMAP 轨迹按多视图掩膜投票打标签（face≥3 且 face>1.5×room 才算人物，101-124），再并入 scene 生成的环境种子作初始点；semantic 与 source_index 是零学习率的 lineage 参数，随 gsplat 的 clone/split/prune 一起继承，保证最终每个高斯都能回溯到初始 COLMAP 点或种子索引。训练按 schedule.training_view_and_mode 在 face（用 pose.py 补偿后的脸部相机 + 脸框 35% 外扩裁切）与 scene（半分辨率）模式间轮换（226-244），两类损失分开加权并加 alpha 惩罚；可选 shared/clean/detail 三个研究分支（199-258，含 source_edge_alignment 的相位对齐损失）。导出前 check_export_policy（45-54）：结构无效（高斯/可编辑数过少或指标非有限）一定失败，画质不达标在 --best-effort 下只记 fidelityWarnings；PLY 按人物优先排序导出，同时写 portrait.provenance.npz（每个最终高斯的初始来源 id/kind/人物分区）并回填 view 的 editableSplats/recordedEnvironmentSplats（300-320）。

- **被谁调用**：worker.py:331 以子进程启动 `train_joint.py <job> --best-effort`（legacy/缺少 engine-profile.json 时生效，最多 7200s）；无测试直接 import（已 grep 确认；graph 的 in_tests 是经 tests→worker→spawn train_joint 的传递可达性；archive/v2 与历史脚本用旧名 reconstruction_train_joint）；自身 CLI train_joint.py:323-330。
- **加载方式**：子进程入口（仅被 worker 按路径启动；不在任何 import 闭包内，属 README 所说的 legacy 训练链之一）。

### 5.4 算法闭包（52，哈希固定，勿改）

按文件名排序。任一文件改动都会使固定哈希失效（见第二节）。

#### `appearance_direction_contract.py`

库模块：degree-1（一阶 SH）头局部颜色到冻结 GS PLY 的坐标/方向契约。定义 C0=0.28209…、C1=0.48860…（:12-13）；unit() 归一化；camera_to_point_in_head() 把 F 变换后的相机系 camera-to-point 射线旋回 head 坐标系（:20-22）；sh1_basis() 按 gsplat 约定构造 SH1 基——SH 路径没有 sigmoid、结果 +0.5 后 clamp（模块 docstring :3-5 明示）；sh1_head_to_reference() 把 head 轴下的 SH1 系数精确旋转到某一冻结 PLY 参考系（只旋转 v=C1·(-c3,-c1,c2) 向量再装回第 1/2/3 通道，:31-41）；sh1_rgb() 用基与系数求方向颜色。生产链写 GS 颜色时实际消费：portrait_model.py:51-53（C0/C1 构造基）、shared_v2.py:115、live_prepare.py:181（(rgb-0.5)/C0 转 SH 直流系数）。

- **被谁调用**：live_prepare.py:19（顶层 import C0）、portrait_model.py:18（顶层 import C0,C1）、shared_v2.py:24（顶层 import C0）、tests/test_components_v2.py:9（sh1_head_to_reference）。usage-graph.json 另外两条边是纯字符串引用而非调用：runtime.py:68-69 与 tests/test_live_fullframe.py:17-18 的 required 文件哈希清单（用于防源码漂移的 sha256 校验，runtime.py:70-75），并非 import 或按路径启动。archive/v2 等历史脚本另有旧引用，非现役。
- **加载方式**：常驻为主：训练子进程两条顶层链都指向它——live_fullframe.py:9 → portrait_pipeline.py:25 → portrait_model.py:18，以及 portrait_pipeline.py:27 → shared_v2.py:24，子进程启动即加载。worker 主进程内为按需（live_prepare.py:19 仅当 runtime.py:340 准备路径 import live_prepare 时才加载）。
#### `capture_reference.py`

为本地人像/身体/稠密交接挑选唯一捕获参考（失败抛 CaptureReferenceUnavailable 且带结构化 receipt）：capture_timestamps 只读经过 captureSha256 校验的 frame_selection.json/frame_manifest.audit.json；choose_capture_reference 要求候选是真实 local∧world 训练观测+刚体 F/C+真实时间戳+有效 landmarks（>454 点、有限），在 ±1.75s 半径内凑 >=3 个不同时间的训练视图且真实相机基线/头距比>=0.005；优先保留旧的"最大表观宽度"参考（否则最正面），preferred 可承接冻结准备；不插值相机、不合成帧、不编造缺失位姿/时间戳，receipt 标记 status=numerically_eligible_short_window_not_verified_rigid_motion。

- **被谁调用**：真调用：live_prepare.py:240-246（拟合后参考资格检查，函数内 import；live_prepare 由 runtime.py:340 在 native 准备阶段加载）；portrait_pipeline.py:748-749（dense_surfaces/dense_manifest 时选参考并写 capture-reference.json）；测试 tests/test_capture_reference.py:4。archive/v5 旧探针调用的是 reconstruction_capture_reference（历史名，非现役）。
- **加载方式**：按需（live_prepare/portrait_pipeline 函数内 import；仅测试顶层）。
#### `capture_registration.py`

真实近时拍摄窗口的有界静态 2D-3D 定位（固定地图不动）：immutable_map_hash 汇总相机参数/已注册位姿/3D 点用于前后比对；track_split 用点 id 哈希把物理 map 点分到 fit/held 两侧（同一物理点不能两边都出现，重复 id 直接报 registration_duplicate_physical_track）；extend_static_short_windows 若已有合格已注册窗口则不救援，否则拷库、按掩码 SIFT 提取+每查询对 6 个近时锚点匹配、对地图 3D 点投票（要求唯一且 track>=3），再用 withheld 点做 median<=2.5px/P90<=6px、网格>=4 格、凸包>=2% 等门限验收，失败查询不产出相机矩阵；产出 report 与 world-additions。

- **被谁调用**：真调用：live_prepare.py:214-215（extend_static_short_windows，函数内 import；调用为现役准备阶段）；live_dense.py:97-98（validate_world_observation_sources 用 immutable_map_hash/quality_accepted，函数内 import）；测试 tests/test_capture_registration.py:6。
- **加载方式**：按需（live_prepare 准备阶段与 live_dense 源校验处函数内 import；仅测试顶层）。顶层 import 很重（pycolmap/cv2），只在需要时加载。
#### `checkpoint.py`

不执行任意 pickle 的安全 checkpoint 读取/恢复器。load_checkpoint（16-34）先做可选的文件 SHA-256 校验（expected_hash 不符即 checkpoint_hash_changed），再用 torch.serialization.get_unsafe_globals_in_checkpoint 把反序列化全局符号限制为 numpy 白名单（numpy.ndarray/dtype/_reconstruct/scalar），以 weights_only=True 加载并要求结果必须是含 'model' 的 dict；restore_tensors（37-59）先要求字段集合完全一致，只对"已声明的 topology 张量"按 saved 形状重建 Parameter/buffer（保持 requires_grad），然后 strict load_state_dict，并逐个张量 torch.equal 逐位复核，任何差异都抛明确标签（checkpoint_fields_differ/type_changed/restore_not_exact）。它是训练执行回执统计初始化分组的底层读取器。

- **被谁调用**：runtime.py:168（training_execution_receipt，仅当 local-init.pt 存在时）与 surface_recovery.py:373 均为函数内导入；仅测试：tests/test_checkpoint.py:6 顶层导入（含恶意 __reduce__ 拒载用例）。
- **加载方式**：按需（仅 runtime/surface_recovery 的特定分支内导入）；另 仅测试。
#### `code_identity.py`

计算"当前磁盘上真正会运行的实现"的确定性指纹。source_identity 从固定 ROOTS=(worker.py, runtime.py, live_fullframe.py, live_prepare.py) 加自身出发，用 AST 递归展开每个本地 .py 的全部 import（含函数内嵌套导入，27-33），逐个算 SHA-256，再取 git rev-parse HEAD，返回 {gitCommit, sourceFiles, implementationSha256（对排序后的文件→哈希 JSON 再哈希）}。它是"编辑/移动闭包内任何文件就会失配、必须重启"的机制来源（当前闭包哈希 adb15d15…），也被训练审计用来冻结源码快照；不含私有 checkpoint/模型/视频。

- **被谁调用**：worker.py:31 顶层导入（进程启动即计算，注释明确"运行中的 worker 绝不静默采用磁盘编辑"，32）；runtime.py:64（pipeline_entry）、runtime.py:97（worker_identity_status）函数内导入；portrait_pipeline.py:836 嵌套导入（保存运行前把 sourceFiles 拷成 algorithm-source 快照）；run_live_body_appearance_trial.py:17 顶层、run_live_skin_compositing_trial.py:12 顶层、run_live_face_capacity_trial.py:20 嵌套导入；其自身 ROOTS/自身文件也被快照。
- **加载方式**：常驻（worker 主进程顶层 import，启动即加载）；在 runtime/portrait_pipeline/trial 脚本中为 按需；在快照拷贝场景下其输出的 sourceFiles 是 仅快照引用。
#### `components_v2.py`

研究专用的"组件观测+有支撑几何"准备库（docstring 明确无生产 job/viewer 导入）：camera_matrix/source_camera（pycolmap 相机→世界矩阵/内参）、make_masks（对每帧取 6 层置信掩码并落盘）、rectified_data（去畸变矫正+组件标签，逐帧挂 observed_* 域）、local_fit_views（冻结 FLAME Open 24/12 先验做局部拟合，可开邻居富化）、shared_scene_scale（用世界系公共相机中心对齐 local/world 尺度）、triangulated_component（新多视图 SIFT+三视图环+重投影门限三角化 hair/glasses/cloth，眼镜线特征只作候选）、load_prepared（加载准备数据并挂观测域/发型拟合契约）、supported_cloth（旧地图经公共投影中心对齐后，点必须在新静态视图已观测服装像素重投影>=3 次）。注意：prepare/supported_cloth/triangulated_garment 当前全仓库无任何调用点（研究整合快照迁移遗留）。

- **被谁调用**：真调用：顶层 import——live_prepare.py:23-24（camera_matrix/source_camera/make_masks/rectified_data/shared_scene_scale/triangulated_component/write_json；调用点 218-264）、portrait_pipeline.py:24（load_prepared ← 666；write_json）、shared_v2.py:26（project/write_json）；函数内 import——live_face_domain.py:40（source_camera）、live_prepare→observations 链、observed_surface 相关；测试 tests/test_components_v2.py:10-11。.sources/integrated-components-v2-20260928-e/algorithm-snapshot 内既有旧名副本 reconstruction_components_v2.py，也有 run_integrated_shared_v2.py:18/20/30 对其 prepare/supported_cloth/triangulated_garment 的调用（历史迁移遗留，非对现役模块的调用；现役源码树与测试无任何调用点）。
- **加载方式**：常驻（被 portrait_pipeline 顶层 import，随重建子进程启动即加载；worker 进程经 runtime→live_prepare 按需加载其子集）。
#### `face.py`

新重建作业的保守本地头部掩码与面部观测：check_models 用内置 SHA256 校验 mediapipe segmenter/landmarker 文件（缺/变即 face_model_missing_or_changed）；head_box 生成宽松头包络（左右 ±0.78 脸宽、上 0.95、下 0.62，保留下颌→颈部衔接、不紧裁）；make_head_mask 在包络内用皮肤/头发置信度+连通域选择（排除近似肤色的手/物体），再按 min(w,h)×0.8% 自适应取 2–7px 半径的椭圆核做闭运算+膨胀保发丝与侧脸（:138-141）；make_static_feature_mask 从静态特征图中去头（对人物核心+头部掩膜用 17×17 椭圆核膨胀后取反，:166-168，供 capture_registration 的掩码 SIFT）；make_component_observations 产出 7 类保守标签（眼镜边缘只作候选、unknown_or_occluded 是不确定带，绝不挖不可见体积）；prepare 逐帧跑 mediapipe（非单张人脸、中心跳变>0.35、尺度比越界 .42~2.4 均计入 missing），落盘 face_masks/person_components/static_feature_masks 与数值 QA（不保存 QA 图像）。

- **被谁调用**：真调用：worker.py:416（PORTRAIT_TEST 引擎把 prepare 作为 prepare_test_faces 传给 reconstruct_test）、worker.py:431（主路径 prepare）、worker.py:611+620（预检 check_models，函数内 import）；components_v2.py:21 顶层 import COMPONENT_MASK_NAMES/make_component_observations（用于 63）；observations.py:34（component_observation_record 内 COMPONENT_MASK_NAMES）；测试 tests/test_face.py:12、tests/test_cancel.py:13。
- **加载方式**：常驻（经 portrait_pipeline→components_v2 顶层 import，在重建子进程启动即加载；worker 预检/主流程另以函数内 import 按需加载）。
#### `flame_open_model.py`

最小、隔离的 FLAME 2023 Open 前向模型（研究用）：加载前校验 pkl 哈希（Open e75a…/Standard 8fb1…），用 _StoredChumpyArray/_LegacyModelUnpickler 在无 chumpy 运行时下读官方旧 pickle；__init__ 严格校验拓扑（9976 面/5023 顶点/shapedirs 5023x3x400/posedirs 5023x3x36/5 关节父母 [-1,0,1,1,1]/权重行和为 1）与 105 点 MediaPipe 嵌入（barycentric 和为 1），构造模板/方向/关节回归/蒙皮权重缓冲；forward(shape,expression,pose[batch,5,3] 轴角) 做 LBS 线性混合蒙皮+pose correctives，返回 posed 顶点与 105 对应点。不含纹理、SMPL-X、图像拟合或发布路径。

- **被谁调用**：真调用：顶层——components_v2.py:18（FlameOpen(24,12) ← 92、363）、live_prepare.py:20（FlameOpen ← 71 fit_local）、live_hair_motion.py:15（+131 函数内按 state 维度重建）、probe_flame_observations.py:18、probe_flame_open_fit.py:21、probe_flame_real_appearance.py:20；函数内——worker.py:623（预检仅当 profile.engine!=gsplat-colmap 时实例化 FlameOpen(24,12)）；测试 tests/test_flame_open_model.py:7、tests/test_flame_observations.py:8、tests/test_live_hair_motion.py:8。live_dense.py:637/698 的 "flame_open_model.py" 字符串是源码快照清单（graph spawn 边），非调用。
- **加载方式**：常驻（components_v2/live_prepare 顶层 import，随重建子进程启动即加载；worker 预检按需；probes 顶层）。
#### `joint_visibility.py`

记录人物+环境 GS 的共享可见性诊断（docstring：非 viewer 遮挡覆写）：posed_points 只把人物 mask 内的点按相对头变换 inv(C_world)@C_corrected 移动/旋转（环境点不动、参考帧处相对变换=恒等，头 SH 对着修正相机、房间 SH 对着世界相机取 ray）；render_shared 一次 rasterization 输出 RGB+人物/环境贡献通道+alpha（可选点探针）；visible_point_scores 用探针反向传播求每点可见贡献（不建 N*H*W 图）；conservation_error 检查 q_person+q_env==alpha；render_components 一次排序/透射输出 RGB+五部件贡献+累加/期望深度（诊断而非 z-buffer）；sha256_file 是通用哈希工具。

- **被谁调用**：真调用：render_shared ← train_joint.py:26+204（worker.py:329-333 以子进程启动 train_joint 的引擎链）；render_components/quaternion_multiply/component_conservation_error/COMPONENTS ← shared_v2.py:27-29+254；sha256_file（:24）← live_prepare.py:25（import；调用 204/224/228/276）、components_v2.py:22（import；调用 51/287/343/356）、observations.py:17（import；调用 44/45/70/92/128）；顶层 import 于 live_prepare.py:25、components_v2.py:22、observations.py:17、shared_v2.py:27、train_joint.py:26；测试 tests/test_joint_visibility.py:8、tests/test_components_v2.py:10。load_recorded_ply 仅 archive/v2-v3 审计脚本使用（经旧名模块 reconstruction_joint_visibility，现仅存于 .sources 快照，非本模块现役路径）；visible_point_scores（:134）与 conservation_error（:146）并非仅 archive——现役测试 tests/test_joint_visibility.py:8-9 顶层导入，:41 调用 conservation_error、:46 调用 visible_point_scores。
- **加载方式**：常驻（train_joint 子进程与重建子进程均顶层 import，启动即加载 gsplat 渲染栈）。
#### `live_dense.py`

采集本地稠密初始化与 DA3 深度推理总控。在固定的 DA3-Base 工具 venv 中对已准备的训练窗口做 depth-only 推理（infer_request：加载 depth_anything_3 网络与 model.safetensors，校验参数别名后逐视图预测深度/置信度），随后 build_components 读入 depth-manifest.json（该文件由 infer_request 于 :473 写出、build_components :484 读入）并生成 room/hair/body 三类高斯种子与 result.json（:602）；算法源码快照由 augment_prepared（:634-638）、rebuild_room_confidence（:610-612）、append_hair_prepared（:696-699）等上层阶段写出，不是 build_components 产物；augment_prepared 在 CUDA 训练场景建立前一次性产出新捕获几何；append_hair_prepared/append_body_prepared/infer_reference_world/rebuild_room_confidence 是补批次与诊断阶段（同深度同预算）。守卫：verify_tool_source_lock/fixed_tool 校验 DA3 源码与权重提交锁定（CODE_COMMIT/MODEL_COMMIT/WEIGHT_HASH），validate_request 校验源哈希、拆分哈希与训练范围；docstring 明确只读本捕获、不得读取或发布旧人物 checkpoint，深度是条件几何而非最终外观。

- **被谁调用**：真调用：portrait_pipeline.py:769（--dense-surfaces 时 import 并调 augment_prepared；augment_prepared 随后在 live_dense.py:659 用固定 venv 以子进程自我执行 --infer）；worker.py:585（预检 dense_tool_preflight 调 fixed_tool）；顶层被房间链 import：live_room_completion.py:17、live_room_reference.py:15、live_shared_room_surface.py:18、live_depth_scale.py:13；测试 tests/test_live_dense.py:8、tests/test_live_hair_motion.py:44、tests/test_live_shared_room_surface.py:79。无调用者：append_hair_prepared、append_body_prepared、infer_reference_world、rebuild_room_confidence（全仓库仅见定义与注释，无调用点）。live_room_completion.py:270 等处的 "live_dense.py" 字符串是 algorithm-source 快照 copyfile 清单（graph 的 spawn 边），非调用。
- **加载方式**：子进程入口（主）：在 DA3 固定 venv 里以 `python -B live_dense.py --infer request.json` 运行（live_dense.py:659/707/743/771 自我重启，__main__ 776-780 分派 infer_request/augment_prepared）；另 按需：worker 预检、portrait_pipeline --dense-surfaces 的函数内 import，以及被房间链模块顶层 import 时随链加载。
#### `live_dense_contract.py`

深度-only 研究互操作契约的纯工具库（docstring：不 import 网络/查看器/worker/发布者）：SHA256 digest、write_json（allow_nan=False）、rigid_check（拒绝非 4x4/非有限/齐次行错/非正交或行列式<0.999 的变换）、resized_camera（先裁剪后缩放的半像素约定，返回 A 与 A@K）、unproject/project、align_camera_scale、bilinear 采样、normalize_cameras、complete_parameter_aliases（只允许同一 Parameter 对象的序列化别名，否则 missing_independent_weight）、classify_depth（遮挡=未知，绝不当作可见矛盾）。生产在用：digest/bilinear/project/unproject/write_json/rigid_check/align_camera_scale/normalize_cameras/resized_camera/complete_parameter_aliases；camera_centres（:37）是 normalize_cameras（:42）与 align_camera_scale（:47）的内部工具函数（非死代码）；classify_depth（:66）、validate_manifest（:76）、validate_surface_source（:99）查无任何调用点（连测试都没调用，属死代码）。

- **被谁调用**：真调用：live_dense.py:23-27 顶层 import（infer_request/build_components 内使用 425,447-461 等）；顶层 import 另见 live_depth_scale.py:14、live_room_completion.py:19、live_room_reference.py:16、live_room_retry.py:12、live_room_self_reference.py:13、live_room_window_recovery.py:15、live_shared_room_surface.py:19；测试 tests/test_live_dense.py:12。live_dense.py:611/636/697/735/764 与 live_room_completion.py:270 的 "live_dense_contract.py" 字符串是源码快照清单（graph spawn 边），非调用。
- **加载方式**：随调用方加载：在 DA3 推理子进程内随 live_dense 顶层 import 于子进程启动即加载（子进程内为常驻）；主 worker 进程无直接入口，相对进程启动属按需（随 live_dense/房间链被加载）。其中 classify_depth、validate_manifest、validate_surface_source 这 3 个函数为无调用代码。
#### `live_face_domain.py`

把语义观测转成“观测面部域”监督：不生成深度、不填未知像素、不改变历史评估掩码。observed_face_domain（:13）在 certainty≥.70 的类 3 面部皮肤中只取与已有 face_core/boundary 8 连通的成分，并加上落在锚点内的类 5 细节（类 2 身体/颈部皮肤被刻意分开）；observed_empty_domain（:25）要求同一 rectify 语义源在 ≥.85 置信度独立标出类 0 背景、且与孤立头部成分一致，同时保护已观测的人脸/头发/眼镜，才对（可选开启的）空域成立；activate（:39）从源标签图+置信图经去畸变重映射重算 training_face/training_skin（可选 training_empty），要求 ≥3 个训练视角有观测（缺观测的视角不会被其他视角填充），重建初始外观 prior 并写 observed-face-domain.json 收据（含逐视角掩码哈希）；restore_recorded（:101）在 resume 时按哈希重放记录的面部域并重算校验，掩码/皮肤/空域/prior 任一漂移即报错。

- **被谁调用**：portrait_pipeline.py:701 在 resume 分支函数内 import restore_recorded，:738 在全新 --observed-face-domain 分支函数内 import activate（:739 调用）；试验脚本 run_live_body_appearance_trial.py:16、run_live_face_capacity_trial.py:18、run_live_skin_compositing_trial.py:23 导入；tests/test_live_face_domain.py:3（顶层 import observed_face_domain/observed_empty_domain）、:52、:72（函数内 import restore_recorded/activate）；该测试 :23/:41/:102 导入的是 portrait_pipeline（head_loss/run/surface_contract_matches），不是本模块。
- **加载方式**：按需（仅 --observed-face-domain 或 resume 分支由 portrait_pipeline 函数内 import）／仅测试
#### `live_fullframe.py`

只做兼容转发的单一可调用流水线入口：顶层 import portrait_pipeline，重导出 ENGINE_VERSION（VERSION）、CAPABILITIES 以及 native_frame/native_draw/NativeScene 别名，让既有传输层资产标识继续有效（实现变更靠 Git 哈希识别）。run()（:20）硬性拒绝 joint_steps≠0（抛 rejected_T2_cannot_enable_new_face_joint_updates），其余参数原样交给 pipeline.run；自身不含任何猴子补丁、独立渲染器或训练算法。__main__（:26）以与脚本相同的 CLI 参数解析后直接运行。

- **被谁调用**：runtime.pipeline_entry 在 executionAdapter=native-fullframe 时把它作为子进程入口返回（runtime.py:67 有 implementationSha256 的分支、:75 按 entrySourceHashes 的分支；运行时由 runtime.py:348-381 的 argv 启动）；code_identity.py:12-13 的 ROOTS 把它列为闭包哈希种子（文件名清单，不是调用）；tests/test_live_fullframe.py:11 顶层导入 native_draw/native_frame/NativeScene，tests/test_runtime_repairs.py:56 按路径读取其源码。
- **加载方式**：子进程入口（native-fullframe 适配器）／仅测试／仅快照引用（code_identity ROOTS 文件名清单作哈希种子，非调用）
#### `live_hair_composite.py`

对已冻结的完整场景做有界的观测头发外观标定（黑底头部拟合无法把颜色与不透明度分开）：restore_hair_in_scene（:20）要求场景已加载稠密观测头发（否则抛 hair_composite_requires_observed_full_scene），步数限 1–240；先冻结全部参数，用房间状态渲染背景后，只取 hair_visible ∧ ¬unknown ∧ 背景 alpha>.9 ∧ 深度有效且 >0 的像素，用于损失；只允许 role==2 的头发 sh 与 opacity 获得梯度，masked_parameter_step（:11）把非允许梯度清零、梯度范数裁剪到 10、并在 step 后恢复冻结行（不透明度额外限制在 ±2 logit 内）；损失 = 观测头发 RGB + 2×人脸保持 + 0.001×SH 先验；结束逐参数断言除头发 sh/opacity 外的所有参数位级不变，明确本阶段不创建头发、不改体积。

- **被谁调用**：portrait_pipeline.py:874-876 当 --hair-steps>0 时函数内 import restore_hair_in_scene（:876 调用）；tests/test_live_hair_composite.py:3 顶层导入 masked_parameter_step。
- **加载方式**：按需（仅 --hair-steps>0 分支）／仅测试
#### `live_hair_motion.py`

参考系相对的 FLAME 关节 1 头发输运（低频颅骨刚体近似，不是完整 FLAME 皮肤 LBS；下颌/眼睛/逐帧表情不拖动头发，根运动留在 F_root 不被二次乘入）。joint1_root_neutral_transform（:20）构造去除根位移的精确关节 1 刚体变换；build_hair_motion（:56）用共享形状+单一固定参考表情算颅骨枢轴，D=G·G_ref⁻¹ 且参考帧被强制为严格单位阵，输出逐帧变换与元数据（含表情/下颌未施加、近似声明）；legacy_hair_motion（:97）是显式旧资产适配（恒等变换、标记 explicit_legacy_root_local，绝不冒充新输运证据）；load_prepared_fit（:107）只读哈希绑定、路径囚笼内的已记录局部拟合检查点，并逐帧断言重算 mesh/F 与准备几何一致；prepared_hair_motion（:147）组合两者；write_motion_contract/verify_motion_receipt（:155/:168）写/校验哈希绑定的 hair-motion.npz+json 收据（含参考单位阵检查与 1e-12 容差）；transport_hair（:214）只移动头发尾部并同步四元数、SH 朝向与完整协方差（_HairCovariantState）。

- **被谁调用**：portrait_pipeline.py:206 函数内 import（initialize_scene 建立绑定；:191-193 经 scene.hair_motion.deform 实际参与渲染）；live_dense.py:399,415,495,647,693 函数内 import prepared_hair_motion/verify_motion_receipt/write_motion_contract（稠密表面推断子进程）；components_v2.py:369 在 load_prepared 内函数级 import load_prepared_fit；live_surface_binding.py:224 在 load_surface_bundle 内校验收据时函数级 import verify_motion_receipt；tests/test_live_hair_motion.py:10。live_dense.py:637,698 的 'spawn' 是把源码拷进 algorithm-source 快照，不是调用。
- **加载方式**：按需（所有生产调用方均在函数内 import；无拟合检查点或无稠密头发时退化为恒等 legacy 适配）／仅快照引用（live_dense 快照拷贝）／仅测试
#### `live_neck_appearance.py`

按真实冻结可见性（而非点中心）挑选可继承的颈部 SH；颜色通道导数被当作所选像素的精确逐高斯合成权重。point_region_contributions（:37）用真实全画布光栅化返回每个高斯对 [neck, protected, all-visible] 三个区域的像素积分贡献，要求原生全幅（rectangle=(0,0,w,h)、nativeScale=1）且观测域齐全；_masks（:16）从观测掩码构造 neck（physical_masks['neck'] 去除 unknown）与受保护区（face_core/face_boundary/hair_visible/glasses_visible），并强制互斥，避免同一像素既投颈部恢复又投面部编辑；select_neck_sh_points（:71）流式消费显式冻结观测：只在 ≥3 个不同的支持视角满足贡献阈值、且任何提供的视角中受保护区贡献≈0 时才选中旧表面前缀内的点（发丝/身体永不合格），对支持观测要求 full_scene、拒绝重复帧，产出选择掩码+收据，零参数更新、零几何/拓扑/不透明度变化。

- **被谁调用**：portrait_pipeline.py:598-615 在 prepare_neck_appearance 内函数级 import select_neck_sh_points（T3 且 dense_surface 时于 :869 调用）；live_skin_compositing.py:93 在 restore_skin_compositing 内函数级 import point_region_contributions（:137 调用）；tests/test_live_neck_appearance.py:5。
- **加载方式**：按需（dense_surface 的 T3 选点与皮肤合成路径）／仅测试
#### `live_neck_motion.py`

在头部与准静态身体之间输运观测到的颈部皮肤：不新建任何样本/颜色/不透明度，衣物与所有非颈部组件原样不变（身体变换显式为单位阵，是短窗口准静态假设而非实测体动）。NeckBinding（:62）校验刚体 C/F，从参考相机计算颈部平滑步权重及其图像空间梯度（fy/cy 在归一化区间内约去，权重固定于参考材质），relative_head（:94）返回相对头变换、参考帧严格单位阵；transforms（:100）给出中心与完整形变雅可比 J（不做 alpha/颜色损失）；deform（:110）在参考帧原样返回，其余帧对 active 颈部点做 JΣJᵀ 完整协方差输运、极分解 SH 旋转、特征值开方导出渲染用 scales/quats，并检查 J 行列式防折叠；TransportedGaussianState/joined_covariant（:14/:28）在拼接组件时保留每段精确协方差图（调用方应 concat covariance 而非用普通 joined_state 丢弃）；build_neck_binding（:150）从 'neck_skin' 层标签构造绑定。

- **被谁调用**：portrait_pipeline.py:182（T2 dense 渲染时 joined_covariant）、:253-255（initialize_scene 里 build_neck_binding 并挂到 scene.neck_binding）、:600（prepare_neck_appearance 观测）均为函数级 import；live_skin_compositing.py:94 函数级 import，:134 使用 joined_covariant；tests/test_live_neck_motion.py:6。
- **加载方式**：按需（dense_surface 的渲染/绑定/皮肤合成路径）／仅测试
#### `live_opaque_person.py`

把“人被观测的不透明内部”当作训练合同而非显示滤镜：房间点不能替代人体覆盖；头发、镜片、未知像素和部件边界绝不强制不透明。OpaquePersonConfig（:15）预先固定透射/颜色/结构权重与 1–8 像素腐蚀边界；prepare_opaque_interiors（:36）在原生未裁剪像素网格上对 skin/cloth/body_skin 三区做互斥腐蚀（排除 hair/glasses/unknown，像素不双重计数），输出 opaque_* 掩码与逐区收据，只改变额外损失的支持集、绝不裁剪或删除几何；person_rgb_features（:83）给合成渲染增加仅含 part 1（头/颈皮肤）与 part 4（实测身体/衣物）的额外通道；conditional_person_colour（:95）用 q 贡献（分母不 detach，防止靠变透明降低颜色损失）分离源辐射；observed_structure_error（:108）只在同一物理区域内比较原生一阶差分；opaque_person_loss（:124）把有界透射损失（q=0 处有限梯度）+ 条件颜色 + 结构损失叠加到调用方既有 RGB 目标之上。

- **被谁调用**：portrait_pipeline.py:394,415 在 train_stage 内按 head/body scope 函数级 import opaque_person_loss，:812 在全新 opaque_person 运行时 import prepare_opaque_interiors；person_supervision_state.py:26 在 restore_person_supervision 内函数级 import（用于恢复/复制监督文件）；tests/test_live_opaque_person.py:4、test_person_supervision_state.py:12、test_pipeline_resume.py:15。
- **加载方式**：按需（--opaque-person/--opaque-body 分支及恢复路径的函数内 import）／仅测试
#### `live_prepare.py`

自动化的逐次拍摄观测准备，不借用其他录制的身份/相机/颜色，并且静态相机恢复明确排除整个人体。capture_observation_names（:34）结合均匀全局视角与一段连续正身窗口挑真实帧（旧均匀采样会留下两秒间隔导致没有近刚性衣物窗口；帧是真实命名观测而非插值相机）；recover_static（:51）用 pycolmap SIFT（≤4500 特征、1600 上限、static_feature_masks 掩码）恢复静态相机；fit_local（:70）逐帧对 FLAME 地标做 PnP-RANSAC + LM 精化，再优化共享形状/逐帧表情与姿态/平移 260 步，训练/开发集分离（开发集形状梯度 detach，颜色不参与），产出 mesh 与 F 并保存可复放检查点；initial_appearance（:155）从训练帧按类 3 皮肤采色（深度半分辨率遮挡、法向朝向、训练面色掩码过滤），组装 head-local-sh1 先验 + 头发种子；prepare_capture（:194）串联稀疏重建、短窗口注册、掩码与矫正观测、局部拟合、房间/hair/cloth 三角化种子，写出 preparation.json、automatic-prepare-audit.json、local_geometry.npz、appearance 等。

- **被谁调用**：runtime.py:340 在无缓存 preparation 时于 reconstruct_test 内函数级 import prepare_capture（仅 portrait-test 作业路径）；live_face_domain.py:41 在 activate 内函数级 import initial_appearance；tests/test_runtime.py:14 顶层导入 selected_names；code_identity.py:13 将 live_prepare.py 列入 ROOTS（闭包哈希种子，文件名清单，不是调用）。
- **加载方式**：按需（runtime 仅在需要现场准备时函数内 import；live_face_domain 函数内 import）／仅测试／仅快照引用（code_identity ROOTS 文件名清单）
#### `live_room_completion.py`

有界多参考的"已观测房间"补全（研究阶段）：只让原本可见的房间像素（含主参考图人物轮廓之后仍被观测到的区域）提议缺失表面，被遮挡像素=未知、绝不当作空；不用推断平面、不生成源 RGB、不换相机。select_completion_references 用真实静态 track 的 fit/held 计数贪心选最多 2 个额外参考（无审计 RGB）；complete_observed_room 逐项核验父资产哈希、深度清单哈希、主表面收据 qualified+roomAssetHash 一致后，经 run_shared_surface 求解并用 export_addition 写成 additionalSurfaceReceipts 增量；verified_completion_replay 在冻结父清单上只重放已记录且合格的解。预算上限：extra_budget<=30000、max_references<=2、max_evaluations<=40。

- **被谁调用**：真调用：live_shared_room_surface.py:468-469（apply_shared_room_correction(complete_observed=True) 内 import；该分支在 live_dense.py:666-668 的 augment_prepared 内部由 if shared_room_surface 触发——:667 函数内 import、:668 调用；shared_room_surface=True 由 portrait_pipeline.py:769-771 的 augment_prepared 调用传入）；select_completion_references ← live_room_window_recovery.py:342；_domains/deduplicate_new_surface ← live_room_self_reference.py:164；export_addition ← live_shared_room_surface.py:308；__main__ CLI live_room_completion.py:334-341；测试 tests/test_live_room_completion.py:9、tests/test_live_shared_room_surface.py:149。live_room_completion.py:270 的 live_dense.py 等字符串是 algorithm-source 快照清单，非调用。
- **加载方式**：按需（只在房间修正链/补全入口被函数内 import 调用；另有 __main__ CLI）。模块顶层 import live_dense、live_dense_contract、observation_domains，被加载时三者随之加载。
#### `live_room_reference.py`

为独立房间参考做资格评估与有界排序，且不改变捕获状态（导出参考、每个 K/C 固定）：候选必须是已缓存且被接受的 world 深度图并带原始 static-map track；用 point_fold 把 map 点分成 fit/held 两侧（物理点不可同时在两边），eligible 需 fit>=20 且 held>=12；inspect_room_references 校验每张深度图哈希、W2C/K 与准备数据一致后统计独立 track 证据，choose_reference_candidates 按 sharedPrimaryTrackCount→held→fit→window 排序去重、最多取 2 个；report.json 明确 KChanged/CChanged/exportReferenceChanged=false、solverInvoked=false，结论是"参考只是待验证假设"。

- **被谁调用**：真调用：live_shared_room_surface.py:420-422（apply_shared_room_correction 的 reference_fallback 内 import 调用）；__main__ live_room_reference.py:81-83；测试 tests/test_live_room_reference.py:2。本模块顶层 import live_dense、live_dense_contract、live_shared_room_surface(point_fold/independent_track_observations)、observation_domains。live_shared_room_surface.py:359 的 "live_room_reference.py" 字符串是快照清单，非调用。
- **加载方式**：按需（live_shared_room_surface 函数内 import + __main__ CLI；tests 顶层）。
#### `live_room_retry.py`

对一次已失败房间窗口的有界第二参考重试：select_second_reference 只挑 independent_validation_failed、仅试过 1 个参考、有 mapTrackEvidence 且 fit>=20、validation>=12 的新参考，按 validation→fit→newAreaCells 取最优；retry_room_reference 强制预算合同（全部 int 且 evaluations<=40、surfaces<=2、budget<=30000）、核验父清单/首次尝试的 sourceSha256 等四项哈希与 acceptedWindows 未变、已有 roomWindowSecondReference 即拒绝重复，随后复用 make_window_proposal/run_shared_surface 只发起这一次求解；complete_room_recovery 是自动链收尾：无合格第二参考或预算耗尽就原样返回，不覆盖第一次尝试文件。

- **被谁调用**：真调用：live_room_window_recovery.py:429（recover_static_window_surfaces 末尾 import 并调 complete_room_recovery）；retry_room_reference ← 本文件 complete_room_recovery:124；测试 tests/test_live_room_retry.py:5、tests/test_live_room_window_recovery.py:40。live_room_retry.py:56 的 "live_room_window_recovery.py"/"live_shared_room_surface.py"/"live_room_completion.py" 是 algorithm-source 快照清单，非调用。
- **加载方式**：按需（被 live_room_window_recovery 函数内 import；本模块无 __main__）。顶层 import live_dense_contract。
#### `live_room_self_reference.py`

把某条已修正表面旧的自身深度投票作为负证据做有界重放（KIND=conditional_corrected_reference）：默认策略下 apply_self_reference_correction 完全不动作（authorized_policy=None 时原样返回 manifestPath），必须显式传 AUTHORIZED_POLICY 且 budget<=6000；不重标定原始投票账本（supportVotesAdded=0、rawFreePreserved=true、otherFreeMaximum=1），旧 self-depth 票只作反证。build_self_reference_candidate 复用已合格表面重放一次（不求解、不推理）；verify_self_reference 逐位核对证据（uid 唯一、各视图二值矩阵一致、support&free 互斥、source_image=参考名、旧 alpha<1/255、旧总覆盖<1%、点集与资产逐字段相等）；retain_self_reference_dependencies 只保留声明的证明叶节点，绝不递归拷贝 capture 图像/视频。docstring 自述"故意不被自动活线路线调用"。

- **被谁调用**：真调用：portrait_pipeline.py:785-786（--room-window-recovery 路径显式授权调用 apply_self_reference_correction）；eligible_self_correction/verify_self_reference ← live_surface_binding.py:47-48、120-121（函数内 import）；retain_self_reference_dependencies ← surface_recovery.py:143、319（函数内 import）；build_self_reference_candidate 由本文件 apply_self_reference_correction:66 调用；测试 tests/test_live_room_self_reference.py:10。live_room_self_reference.py:186 的 "surface_recovery.py"/"live_dense.py" 是快照清单，非调用。
- **加载方式**：按需（portrait_pipeline/live_surface_binding/surface_recovery 函数内 import；无 __main__；tests 顶层）。顶层 import live_dense_contract。
#### `live_room_window_recovery.py`

对"表面修正前被拒的锚定房间窗口"做有界恢复：make_window_proposal 只接受确实被拒（原始 windowComparisons 有拒绝证据）且所有行 scaleGatePassed 的 world 窗口，产出 permitsSolveOnly 收据（原拒绝绝不重写）；verify_window_proposal/depth_agreement/surface_pair_overlap/check_surface_overlap 用固定相机几何+独立 held-out track 只授权"尝试修正"，接受还需保守的相互表面重叠检查；filter_unrepresented_observations 只把父有效 footprint 之外、有 >=3 静态 RGB 认同且冲突<=1 的点转正（allow_typed_conditional 时保留原 free-space 规则与"非测量"标签）；recover_static_window_surfaces 组装一次有界求解并交 live_room_retry 收尾；父 bundle 的点不移动/删除/放大、不变不透明。

- **被谁调用**：真调用：portrait_pipeline.py:777-782（--room-window-recovery，函数内 import）；make_window_proposal/check_surface_overlap/filter_unrepresented_observations ← live_room_retry.py:30；verify_window_proposal ← live_shared_room_surface.py:92；projected_room_footprints ← live_room_self_reference.py:165；live_surface_binding.py:125（导入验证）；__main__ 434-437；测试 tests/test_live_room_window_recovery.py:7、tests/test_pipeline_resume.py:89（断言不得再次恢复）。307/352 行的 "live_room_completion.py" 等字符串是快照清单。
- **加载方式**：按需（portrait_pipeline 与房间链函数内 import；另 __main__ CLI）。顶层 import live_dense_contract（digest/write_json/bilinear/project/unproject）。
#### `live_shared_room_surface.py`

有界 CPU 共享房间表面修正（相机/颜色/点数不变）：用低维逆深度残差（basis_weights/shared_points + lil_matrix/least_squares）在 world 坐标定义"一个"参考表面，所有原始静态 track 观测共同约束它，条件深度只作软先验；run_shared_surface 在已接受的参考 world 窗口（或带提案收据的被拒窗口）上求解并按 fit/held 角色度量；export_shared_room_initialization 生成带 uid、evidence_type（depth_consistent / conditional_shared_surface）、支撑/冲突计数与颜色认同的条件初始化交易（surfaceCorrectionReceipt）；apply_shared_room_correction 是活线适配器：证据不足抛 SharedRoomEvidenceUnavailable 保留输入 bundle，程序/IO/输入变更类错误直接传播，可经 inspect_room_references 换参考重试，complete_observed 时链到 complete_observed_room。

- **被谁调用**：真调用：live_dense.py:667-668（augment_prepared 的 shared_room_surface=True 分支；--shared-room-surface 由 runtime.py:353/portrait_pipeline.py:770-771 门控）；run_shared_surface/export_shared_room_initialization/SharedRoomEvidenceUnavailable ← live_room_completion.py:257、live_room_retry.py:31、live_room_window_recovery.py:343；point_fold/independent_track_observations ← live_room_reference.py:17（顶层）、live_room_completion.py:85；测试 tests/test_live_shared_room_surface.py:8-9、tests/test_pipeline_resume.py。359-360 行的 "live_room_reference.py"/"observation_domains.py" 是快照清单。
- **加载方式**：按需（live_dense 与房间链函数内 import；被 live_room_reference 顶层 import 时随其加载；无 __main__）。顶层 import live_dense、live_dense_contract、observation_domains。
#### `live_skin_compositing.py`

有界、冻结几何的观测不透明皮肤合成恢复；黑白背景只作监督检验、绝不导出为场景内容，头发/镜片/未知边缘绝不强制不透明。opaque_observation_mask（:16）取 training_skin∩face_core 并排除眼镜/头发/unknown，按最小边 1% 宽度腐蚀；backdrop_consistency（:27）要求同一不透明观测像素在黑底与白底合成下都吻合目标；protected_observation_mask（:35）保护所有非目标区域（发丝/镜片/未知/未选脸面）；observed_update_masks（:56）按每视角安全观测决定允许更新的点；restore_skin_compositing（:91）要求 dense_surface 且步数 1–240、≥3 个安全观测视角，先做全区域基线质量审计，只对 sh/opacity 做 Adam（lr .0015/.02），损失 = 合成 RGB + 2×保护像素保持 + 0.001×SH 先验，每步按视角掩码更新；结束后对未选点与全部其他字段做位级不变断言，再做候选质量审计，任一区域 rgb/hole 回退即整体回滚到父状态并清空优化器。

- **被谁调用**：portrait_pipeline.py:877-879 当 --skin-steps>0 时函数级 import restore_skin_compositing（:879 调用）；独立手动试验脚本 run_live_skin_compositing_trial.py:11 顶层导入（:50 调用，脚本本身不被服务调用）；该脚本 :38 处的 'spawn' 只是哈希/快照文件清单里的字符串（files[name]=digest + shutil.copyfile），不是调用；tests/test_live_skin_compositing.py:4 顶层导入其纯函数。
- **加载方式**：按需（仅 --skin-steps 分支；生产主路径）／仅测试（另有手动试验脚本顶层导入）
#### `live_surface_binding.py`

把实测图像的表面组件交付给现有 live 人像训练器的适配层：深度预测只是提案，不是实测真值；保留各向异性协方差而不是退化为 KNN blob 尺寸。load_component（:18）对 npz 逐字段校验形状/有限性/哈希/坐标系/点数为正/不透明度∈(0,1)，并校验条件房间证据（evidence_type、static_image_support/colour_support/depth_free 票数、自参考收据）；verify_room_correction（:59）与 verify_room_completion（:86）逐面验证房间附加表面的来源资产哈希、点数与逐参数相等，阻断“一面墙的证明给其他深度提案背书”，并校验自参考/窗口恢复证明的类型与资格；replace_hair_prior（:155）只替换显式支持的头发、面部前缀 surface_ids/bary 位级保留；environment_from_components（:183）把 room/body 合入同一光栅化环境但源类型（20/21）、UID 与层标签保持分离；load_surface_bundle（:203）校验清单 schema/源哈希/尺度/K/preparation 与 local_geometry 哈希、逐组件哈希、头发运动收据与头发参考帧、并禁止评估视角进入训练范围。

- **被谁调用**：portrait_pipeline.py:214-222 在 initialize_scene 的 dense_manifest 分支函数级 import load_surface_bundle/environment_from_components/replace_hair_prior（:217/:220/:222 调用）；live_room_self_reference.py:166 函数级 import verify_room_correction；模块内部 load_surface_bundle 于 :232 调用 verify_room_completion；tests/test_live_surface_binding.py:6、test_live_room_self_reference.py:12。live_room_retry.py:56、live_room_self_reference.py:186、live_room_window_recovery.py:307,352 的 'spawn' 全是 shutil.copyfile 到 algorithm-source 的快照拷贝，不是调用。
- **加载方式**：按需（dense 初始化与房间自参考验证的函数内 import）／仅快照引用（三个房间模块的 algorithm-source 源码拷贝清单）／仅测试
#### `live_surface_footprint.py`

可选的“新鲜先验皮肤协方差”初始化提案：是局部采样密度的初始化猜测，不是实测皮肤微观几何，不改已训检查点、不动点/颜色/不透明度/绑定，也从不读取 held-out RGB。observed_skin_semantics（:113）只用训练帧的类 3 皮肤支持：每个三角形需至少两顶点+中心被观测，且任意可见探针命中头发/眼镜/unknown/类 5 面部细节即否决该视角（FLAME 深度只作遮挡提案/一致性守卫）；支持三角形经同区域邻接连成连通区域，输出 triangle_regions/point_eligible 与收据；adapt_surface_footprints（:218）只接受 prior_stage='fresh_initialization'，在同区域且法向相容的连通邻域内用 k/(πr²) 采样密度估计目标切向协方差（保持法向方差 nᵀΣn），带尺度比、各向异性、激活范围上下限与角度覆盖检查，用中心+同面中点探针的局部高斯重叠代理做至多 4 轮回退，任何不稳定就把整批改回并放弃交易；adapt_observed_surface_footprints（:363）串联语义+适配，输出原生针孔投影 sigma 诊断。输出是拷贝后的先验（log_scales/local_quats 之外字段位级不变断言）。

- **被谁调用**：portrait_pipeline.py:752-758 仅在 --surface-footprint 且全新初始化（同时要求 --observed-face-domain、无 resume/warm-start）时函数级 import adapt_observed_surface_footprints（:756 调用，随后写 surface-footprint.json 并更新 appearanceHash）；tests/test_live_surface_footprint.py:7。
- **加载方式**：按需（仅全新 --surface-footprint 运行，且必须伴随 --observed-face-domain）／仅测试
#### `local_sampling.py`

只修一个别名缺陷的确定性局部采样器，不动观测/相机/相位。问题：观测数为偶数时 step%n 与几何相位 step%4==3 混叠，某些视角永远拿不到几何更新；scheduled_local_index（15-22）对偶数 count、step≥83 且 step%4==3 的几何步改用独立游标 ((83%count)+(step-83)//4)%count，其余步保持 step%count，因而外观帧序逐帧不变（奇数规模本来就遍历全部几何视角，保持原样）；count<1 或 step<0、以及 bool 入参直接 ValueError。scheduled_local_name（25-26）按结果取名；schedule_receipt（29-47）不接触模型地模拟 steps 步，给出每个观测在"改前/改后"的 appearance/geometry 次数、仍缺几何的名单，并强制参数必须是真实相位 (80,4,3)，明示"恢复只需 ordered names+绝对 nextStep、无隐藏 RNG/游标"与"每完整组合 epoch 不保证每观测一次"。

- **被谁调用**：portrait_pipeline.py:354 函数内导入 scheduled_local_name/schedule_receipt（native 局部训练阶段）；tests/test_local_sampling.py:2 顶层导入（含偶数计数修复与奇偶不变量回归）。
- **加载方式**：按需（仅 portrait_pipeline 局部训练分支内导入）；另 仅测试。
#### `observation_domains.py`

把逐帧标签图+置信图转成"全量、矫正后"的物理观测域：valid=(不在去畸变空白边缘)且 certainty>=0.70；observed_room=class0 且 >=0.85（含白墙，不做人物膨胀排除），observed_cloth=class4，observed_body_skin=class2，observed_neck_cloth=cloth|skin；rectified_domains 用 cv2.initUndistortRectifyMap+remap（标签最近邻、置信度双线性）产出域，缺文件抛 physical_observation_source_missing、尺寸不符抛 physical_observation_size；attach_observation_domains 幂等挂载（已有 observed_room 即跳过）。它定义的是"观测到的像素域"，与特征匹配安全掩码无关，不外推平面、不生成 RGB。

- **被谁调用**：真调用：attach_observation_domains ← live_room_completion.py:26、live_room_reference.py:41、live_shared_room_surface.py:106/257、live_dense.py:502（build_components 内函数级 import 后调用）、live_depth_scale.py:76。顶层 import：live_depth_scale.py:15、live_room_completion.py:20、live_room_reference.py:18、live_shared_room_surface.py:20。live_dense.py:611/636/735/764 与 live_shared_room_surface.py:360 的 "observation_domains.py" 字符串是源码快照清单（graph spawn 边），非调用。注意：components_v2.py:367-368 调用的是 observed_surface 的同名函数（components_v2 未 import 本模块），不要计入本模块。
- **加载方式**：按需（随 live_dense.build_components 或房间链模块顶层 import 加载；没有任何进程启动即加载它的路径）。
#### `observations.py`

每作业的帧/脸/世界证据打包器，只记录估计、不发明相机位姿。build_observation_bundle（53-173）先校验 frame_selection（≥18 个唯一帧、源索引与时间戳严格递增、capture 哈希一致、已注册帧必须是选中帧子集、姿态与 landmark 文件名子集），逐帧写：PNG 哈希、解码尺寸与相机内参宽高一致性、K 与 COLMAP w2c/相机参数（明确标注 "COLMAP_estimated_not_independently_calibrated"、trustedForFinalJointTraining=False）、头部/场景排除/可见环境/人物部件/静态特征候选五类 mask 的哈希与 null 值、头部与补偿姿态的有限性+行列式检查、productionFit/development 角色（development 每 ~1/10 帧抽样），最终 observation_bundle.json 里显式写 trustedStaticWorldCount=0、joinKey=相对图像名。component_observation_record（31-50）按精确图像名而非位置 zip 连接部件证据，并为每种掩膜记 SHA-256。

- **被谁调用**：worker.py:445 函数内导入（legacy 链，446 调用）；components_v2.py:23 顶层导入 component_observation_record；tests/test_cancel.py:16 顶层导入；CLI observations.py:176-187 无调用者。
- **加载方式**：按需（worker legacy 分支导入）；在 native 链随 components_v2 顶层导入而 常驻；另 仅测试。
#### `observed_surface.py`

物理观测域+有限表面支撑（--surface-refine 研究阶段）：含与 observation_domains.py 同源的 observation_domains/rectified_domains/attach_observation_domains 三件套；finite_triangle_samples 只在短近刚性窗内对已测 garment/neck 三角做 Delaunay 加密（每样本需 >=3 个真实训练视图颜色认同、保留父 track/barycentric 身份、require_plane 时用局部 PCA 判平面），不制造新证据；prepare_surface_stage 是入口：先对 room 加密（budget 6000、max_edge 192、要求平面），再让 static_planes.finite_plane_support 生成平面候选（budget 10000），两批先减去与父点重复者（距离<=scale*1e-6）才并入 room-surface-hypotheses.npz；身体部分因局部运动证据不足则维持原种子（body_local_motion_required）。

- **被谁调用**：真调用：rectified_domains ← components_v2.py:86（rectified_data 内，live_prepare.py:221 触发）；attach_observation_domains ← components_v2.py:368（load_prepared 内，portrait_pipeline.py:666 触发）；prepare_surface_stage ← portrait_pipeline.py:797-798（--surface-refine）；finite_triangle_samples 由本模块 prepare_surface_stage 内部调用；测试 tests/test_surface_stage.py:7 顶层（import 的是本模块的 observation_domains 函数）。live_room_* 房间链用的是 observation_domains.py 的副本，不是本模块。
- **加载方式**：按需（components_v2 的 rectified_data/load_prepared 函数内 import、portrait_pipeline --surface-refine 函数内 import）。
#### `person_supervision_state.py`

与训练模型一起恢复"非 Parameter"的训练/渲染契约，防止 warm-start 悄悄继承旧开关。restore_person_supervision（19-85）在模型 load 之后、任何 render/export 之前：校验 opaque 标志是布尔且 body⇒head、checkpoint.sourceSha256 与 data.sourceHash 及 config 三方一致、appearanceHash 一致、checkpoint 内记录的 personSupervision 契约（opaqueHead/opaqueBody/appearanceSha256）与请求一致（旧 checkpoint 无此元数据只允许在全 False 的 legacy 记录下通过）；若配置了 observedFaceDomain，还要求 observed-face-domain.json 与先验 npz 的字节哈希一致、data 内回执一致；opaque 模式下按 opaque-interiors.json 收据用 prepare_opaque_interiors 逐视角重算掩膜并逐一比对收据与 mask 哈希，全部通过后才把掩膜写回 labels 并设置 scene.opaque_person/opaque_body（先验证后变异，避免内存中残留旧掩膜）。copy_person_supervision_files（88-104）把 face domain、先验、opaque interiors、surface footprint 及诊断、room window recovery 的原始收据文件逐字节复制给下一次独立运行，目的地已有不同字节则拒绝覆盖。

- **被谁调用**：portrait_pipeline.py:702（保存恢复态时 copy）、portrait_pipeline.py:834（resume 加载时 restore）函数内导入；run_live_body_appearance_trial.py:18、run_live_face_capacity_trial.py:12、run_live_skin_compositing_trial.py:13 顶层导入，且这三个脚本在 run_live_body:63、run_live_face:53、run_live_skin:39 的 provenance 快照名单里按文件名把它拷进 algorithm-source（该 spawn 边是快照引用，不是执行）；tests/test_person_supervision_state.py:13 顶层导入。
- **加载方式**：按需（仅 portrait_pipeline 的 resume 分支内导入）；另有 仅快照引用（三个 trial 脚本拷入 algorithm-source 快照）；另 仅测试。
#### `portrait_model.py`

可复用的照片驱动人像模型，FLAME 只作可移动的软先验（模块声明 E1–E5 接受候选前没有任何发布器导入它，且保留已知有问题的旧头发初始化，不静默修复）。提供：四元数/球谐数学（quat_product、quaternion_matrix、rotate_sh1、evaluate_sh1，:21-54）与头局部→世界的 scaled_head_transform；GaussianState 数据类（解析协方差 covariance() 与 to_world 变换，:67-84）；网格邻接与三角形行走（mesh_adjacency 只走流形、同区域、法向相容的边；walk_embeddings 用跨边铰链旋转展开切向位移，遇屏障投影回边而非跳邻域，:92-160）。LocalPortraitModel（:163）在观测网格上保持同一身份残差与可动高斯嵌入：surface/local_state 生成表面点+法向偏移+头发尾尾；soft/strong 两种约束；soft_regularization 以原生像素尺度约束皮肤软带、表面平滑、身份残差与法向偏移；walk/replace_skin_parents 负责图表行走与经逐子观测验证的表面点一分为二。CandidateTransaction（:373）提供整模型+Adam 快照、≤48 步有界恢复与证据审计：仅在 held-out 指标不劣化时接受，否则完整回滚。

- **被谁调用**：portrait_pipeline.py:25 顶层导入（LocalPortraitModel/GaussianState/CandidateTransaction/joined_state/evaluate_sh1），:448 函数内再取 quaternion_matrix；live_hair_motion.py:16、live_neck_motion.py:10 顶层导入；live_hair_composite.py:24 函数内导入 GaussianState；surface_density.py:10 顶层导入 quaternion_matrix（surface_density 由 portrait_pipeline.py:505 按需调用）；tests/test_portrait_model.py:9、test_live_fullframe.py:9、test_live_hair_motion.py:9、test_live_neck_appearance.py:4、test_live_neck_motion.py:5。live_dense.py:637,698 的 'spawn' 只是把该源码拷进 algorithm-source 快照，不是调用。
- **加载方式**：常驻（被 portrait_pipeline、live_hair_motion、live_neck_motion、surface_density 顶层 import）／按需（live_hair_composite 及 portrait_pipeline:448 函数内 import）／仅快照引用（live_dense 快照拷贝）／仅测试
#### `portrait_pipeline.py`

人像优先（portrait-first）重建主引擎，是可调用的后端脚本而不是发布器：接收已验证的拍摄准备目录（preparation.json），把 FLAME 嵌入的高斯人像与实测房间/衣物种子装配成一个场景并完成全部训练与审计。关键构件：SceneAssembly（:143）合成场景，render() 分 T0 头局部 / T1 世界 / T2 全场景共用一次 alpha 合成三档渲染；initialize_scene（:196）装配人像、环境、头发运动绑定、稠密表面组件与 neck_binding，写出 portrait-import.json（含 pointCount/denseSurfaceManifest/体动状态等）；train_stage（:344）做 local/T3/T4 交替外观-几何优化，房间/衣物只用观测像素监督并带防反覆盖保护，支持 surface_density 密度事件与 checkpoint；audit_stages/audit_full_scene（:272/:311）产出逐阶段指标与 npz/png 审计（含 T0→T1 相机点/协方差一致性）；prepare_neck_appearance（:598）选可编辑颈部 SH；export_candidate（:535）导出 portrait.gaussian.ply、portrait.components.npz、portrait.view.json、trained-state.pt；surface_contract/surface_contract_matches（:575/:584）固化可复放合同；warm_start_portrait（:618）在源/引擎/几何/头发运动全等的前提下复用已训头部；run（:654）解析 CLI 开关（--resume-state、--dense-surfaces、--observed-face-domain、--opaque-person、--surface-footprint、--room-window-recovery、--hair-steps、--skin-steps 等）串起流水线，写 config.json/report.json，并把源码闭包快照到 output/algorithm-source（:839）。

- **被谁调用**：runtime.reconstruct_test 在 executionAdapter=legacy（默认）时把它作为子进程入口返回（runtime.py:60），随后 runtime.py:345-381 构造 argv 并用注入的 command() 启动；live_fullframe.py:9 顶层 import 它（native-fullframe 入口转调 pipeline.run）；函数内按需被 live_face_domain.py:42,103、live_hair_composite.py:22、live_skin_compositing.py:92 导入；试验脚本 run_live_body_appearance_trial.py:13、run_live_face_capacity_trial.py:16、run_live_skin_compositing_trial.py:9 导入；tests/test_live_face_domain.py:23,41,102、test_live_fullframe.py:10,17、test_live_hair_motion.py:45、test_pipeline_resume.py:14 导入或按路径读源码。
- **加载方式**：子进程入口（legacy 适配器，由 runtime 按路径启动）／常驻（native-fullframe 子进程启动时经 live_fullframe 顶层 import 即加载）／按需（各阶段模块在函数内 import）／仅测试
#### `portrait_preview.py`

从已核验的 gsplat PLY 生成小型静态预览（docstring：低开销导航缩略图，不是质量评估，也不替代完整 3DGS 查看器）。_read_splats（19-38）解析 binary_little_endian PLY 头（≤8 KiB），必须含 x/y/z/f_dc_0..2/opacity，顶点数 100–200 万，并校验字节长度。create（41-95）：按 portrait.view.json 的相机把高斯中心与 DC 颜色投影到 256×256 RGBA，只保留头部体积（半径 ≤0.32×相机距离）内 opacity>0.08 且深度合法的点，远→近绘制，轻度 GaussianBlur(0.35)，产出 portrait.preview.png（≥100 个投影点、≤512 KiB，超限即删并报错）。create_3d_lod（98-142）：取脸中心半径 0.34×距离、opacity>0.055 的候选（≥1500），按 opacity 加权随机采样到 ≤24000（种子 20260924），产出 portrait.preview.gaussian.ply（4 KiB–12 MiB）。create_scene_lod（145-227）：全场景 LOD ≤28000（种子 20260925），按半径四分位配额，剔除半径 94 分位之外的极端离群点与超大 splat，对远层用 smoothstep 把 opacity 最多压 99.2%，产出 portrait.scene-v3.gaussian.ply（4 KiB–12 MiB），tmp 文件原子替换。230-234 行的 __main__ 支持 `portrait_preview.py JOB_DIR` CLI，但全仓没有以该路径启动的脚本。

- **被谁调用**：图 JSON 3 条入边全部核实：worker.py:369（函数内 from portrait_preview import create, create_3d_lod, create_scene_lod，实际被 worker.py:420 的 PORTRAIT_TEST 分支与 worker.py:462 的 legacy 训练后分支调用，两处异常均被吞掉以保模型不因缩略图失败）、recon_transfer.py:260（ensure_scene_preview 端点内 from portrait_preview import create_scene_lod，仅 gaussian_ready/complete 状态）、backend/tests/test_scene_preview.py:15（顶层 import create_scene_lod, _read_splats）。
- **加载方式**：按需（worker 进程与 FastAPI 进程都在函数体内 import，仅在生成预览或回填 scene LOD 时加载）；叠加仅测试（test_scene_preview 顶层导入）；不是子进程入口（__main__ 无调用者）。注意：worker.py:369 的函数内 import 仍被 code_identity.py 的 ast.walk 闭包扫描（12-13 行 ROOTS、27-33 行递归）捕获，本机实测 source_identity(backend) 的 52 个算法源码文件中包含 portrait_preview.py，因此改动/改名会改变 implementationSha256；另外 9 个模块都不在该闭包内。
#### `pose.py`

人脸姿态测量（只提供约束，绝不造或改世界相机）。canonical_vertices（52-62）加载钉死的 MediaPipe 468 点规范脸 models/canonical_face_model.obj，校验 SHA-256 与 (468,3) 拓扑；pose_from_landmarks（65-82）用 PnP RANSAC（160 次迭代、≥160 内点）加 LM 精修求头部姿态，重投影 RMSE>12px 判不可靠；refit_local_pose_same_camera（15-39）在真实相机模型下做一次固定形状/表情的局部刚体 PnP 精修（每第 5 个 landmark 排除拟合、单独作开发检查报告，世界相机不变）。prepare_face_views（85-161）逐帧解头部姿态，用相机位移在脸部射线上的投影估每视角尺度（scale≤0 即失败），由中位数距离+旋转中位数挑 medoid 参考系，产出 face_camera_poses.npz（补偿后 w2c）、face_head_to_camera.npz（局部头→相机 F_t×scale）与 face_pose_quality.json（注册视角须 ≥max(16, 观测数 75%)，含旋转/中心漂移统计、scale 标注为"估计值、非独立标定"）。

- **被谁调用**：worker.py:442（legacy 链 prepare_face_views）、worker.py:612（preflight canonical_vertices）函数内导入；components_v2.py:24 顶层导入 refit_local_pose_same_camera，而 components_v2 又被 portrait_pipeline.py:24、live_prepare.py:23 顶层导入，因此 native 链子进程启动即加载 pose；tests/test_cancel.py:14 顶层导入。
- **加载方式**：按需（worker 特定阶段内导入）；在 native 链中随 components_v2 顶层导入而 常驻（相对该子进程）；另 仅测试。
#### `probe_flame_observations.py`

研究探针：把 FLAME 局部人脸观测与世界坐标相机观测严格分离，并守护“根旋转只应用一次”的约定。核心函数 root_neutral_contract() 用同一组 shape/expression/pose 分别计算 root 旋转置零的局部网格与完整 posed 网格，解析构造 F 矩阵（R、t 经 root joint 修正），比较两条路径的最大顶点误差，>1e-5 直接抛 AssertionError('root_applied_twice')（:36-44,:83-84）。run() 逐帧遍历 1..160，为 TRAIN 14 帧与 HELD 8 帧生成 faceObservation（局部 head-to-camera F、表达式/姿态、可见区域、faceMask sha256），为研究可信帧生成 worldObservation（临时可信的 COLMAP 静态相机 C/K），最终写出 private-observations.audit.json，并显式保持 headInWorldCount=0：拒绝用 H=C⁻¹F 合成头部世界位姿，理由是局部 K 忽略畸变、场景尺度未独立标定（:115-126）。守卫：capture manifest 的 sha256 必须等于 SOURCE_SHA256（:56-57），可信帧缺相机抛 trusted_camera_missing（:100-101）。生产链消费其 root_neutral_contract 来校验 FLAME 拟合根约定：components_v2.py:104、live_prepare.py:146。

- **被谁调用**：components_v2.py:19（顶层 import，使用于 :104）；live_prepare.py:21（顶层 import，使用于 :146）；tests/test_flame_observations.py:9（测试直接调用）。与 usage-graph.json 的 3 条 import 入边一致。.sources/integrated-components-v2-20260928-e/algorithm-snapshot 内为快照拷贝，archive/v2、archive/v5 为历史脚本旧引用，均非现役调用。
- **加载方式**：常驻为主：live_fullframe.py:9 → portrait_pipeline.py:24 → components_v2.py:19 的顶层 import 链，训练子进程启动即加载；worker 主进程中当 runtime.py:340 的缓存未命中路径 import live_prepare 时被按需拉入。另有 __main__ CLI（python probe_flame_observations.py <job> --variant）供人工研究运行。
#### `probe_flame_open_fit.py`

研究探针：把共享的 FLAME 2023 Open 身份拟合到已有私域视频 landmark（E2 一次性拟合）。将 468 点 MediaPipe landmark 映射到 FLAME 的 105 点，对 14 个训练帧（TRAIN=(5,12,...,150)）用 cv2.solvePnPRansac 初始化 head-to-camera 局部姿态（内点 <45 抛 flame_open_pnp_insufficient_static_landmarks），随后 Adam 联合优化 shared shape(24)、逐帧 expression(12)/pose(5×3)/translation；8 个留出帧（HELD）只用 84 个非留出 landmark 拟合局部姿态与表情、共享身份冻结，且写入 color_training_eligible=False（:172-224）。产出：private-fit-parameters.npz、private-held-local-parameters.npz、fit.audit.json（训练/留出重投影 median/p90/RMSE、拟合曲线、系数幅值、显存峰值），以及 3 张 landmark/mesh 叠加 JPG。守卫：capture.mp4 sha256 必须等于 SOURCE_SHA256（:81-82），landmark 必须 (468,2)（:109-110），报告状态固定为 isolated_local_geometry_probe_only，明确 cameraIntrinsicSource 非独立标定（:250-263）。

- **被谁调用**：probe_flame_observations.py:19、probe_flame_real_appearance.py:21、probe_portrait_components.py:15（均为顶层 import，取 TRAIN/HELD/INTRINSIC/SOURCE_SHA256/filename 常量与函数）。与 usage-graph.json 的 3 条 import 入边一致。archive/v2 多个历史脚本另有旧引用，非现役。
- **加载方式**：常驻（作为上述三个模块的顶层依赖在训练子进程/worker 准备路径启动时被加载；模块顶层即 import cv2/torch）。同时自带 __main__ CLI（--steps/--variant），可人工 python probe_flame_open_fit.py <job> 运行整条拟合。
#### `probe_flame_real_appearance.py`

研究探针：三角面绑定的 GS 外观采样（head-only，绝不声称完整肖像）。barycentric_samples() 按三角形面积加权永久采样 face_id+barycentric（固定种子 260927）并给出受限屏幕空间 splat 足迹 scale；bound_points() 在任意形状/姿态变形后把同一些三角形重新绑定点位（几何上 verify 在 tests/test_flame_observations.py:23-34）。run() 逐个训练帧把 4 万个 splat 投影到源图，做三重可见性过滤——半分辨率点深度缓冲（±0.0035）、mask 腐蚀、法线朝向 alignment>0.22 剔除背面（:68-89），再以 weighted best-observed 颜色着色（不支持表面保持透明 opacity=0，:196-200）；产出 private-bound-splats.npz（face_ids/barycentric/rgb/support/opacity/scale + 双哈希）与 audit.json + 6 张对比图（3 训练帧 + 3 留出帧；留出帧像素明确排除在着色之外，:243）。守卫：capture 哈希（:141-142）、样本数 5000..100000、色彩支撑 <1/5 抛 real_color_support_insufficient（:193-194）、训练/留出划分被改抛 training_holdout_split_changed（:149-150）；render 用 gsplat rasterization 并记录显存。生产链实际消费其中的 barycentric_samples/bound_points：live_prepare.py:157,160、shared_v2.py:81,101、components_v2.py:20。

- **被谁调用**：components_v2.py:20、live_prepare.py:22、shared_v2.py:25（顶层 import bound_points/barycentric_samples）；tests/test_flame_observations.py:10。与 usage-graph.json 的 4 条 import 入边一致。archive/v2/v5 历史脚本另有引用，非现役。
- **加载方式**：常驻（训练子进程顶层链 live_fullframe.py:9→portrait_pipeline.py:24/27→components_v2.py:20/shared_v2.py:25，启动即加载）；worker 主进程经 live_prepare 按需；另有 __main__ CLI（--variant/--samples/--color-region）人工运行。
#### `probe_gs_contract.py`

契约探针：验证 gsplat → 标准 3DGS PLY → 再解析回 gsplat 的无损往返。main() 合成 4 个 splat（红前景、蓝后景、斜置绿、偏移黄，覆盖深度序/旋转/各向异性尺度轴），用 gsplat.export_splats 写 binary_little_endian 1.0 PLY 到 .sources/gs-contract-probe/anisotropic-occlusion.ply，再用自实现的 read_float_ply() 解析（含 f_rest 从 channel-major 到 coefficient-major 的 reshape+transpose，:74-78），在 3 个水平偏移视角重渲染；要求 maxPixelError≤1e-5、log-scale/opacity/SH 误差≤1e-6，否则 AssertionError（:94-95），报告写 roundtrip.json。硬编码 device='cuda'（需 GPU）。该 PLY 同时是 viewer-gs/tests/ply-contract.test.mjs 校验 PlayCanvas 解析的基准（docstring :3-4）。生产链真正使用的是 read_float_ply：joint_visibility.py:33 读取 PLY 做关节/部件可见性分析。

- **被谁调用**：joint_visibility.py:21（顶层 import read_float_ply，调用点 :33）。与 usage-graph.json 的 1 条 import 入边一致；in_tests=true 是经 joint_visibility 传递（tests/test_joint_visibility.py:8、tests/test_components_v2.py:10），并非测试直接 import 本模块。archive/v2/v4/v5 多处历史脚本引用 read_float_ply，非现役。
- **加载方式**：常驻（joint_visibility 顶层 import 本模块：训练子进程 live_fullframe.py:9→portrait_pipeline→components_v2.py:22→joint_visibility.py:21 启动即加载；旧引擎 train_joint.py:26 顶层也 import joint_visibility，train_joint 子进程启动时同样加载）。main() 仅手动 python probe_gs_contract.py 运行。
#### `probe_portrait_components.py`

2D 部件分割探针：用本地 MediaPipe 模型（.sources/third_party/mediapipe/hair_segmenter.tflite 与 selfie_multiclass_256x256.tflite，sha256 锁死 :21-22）对 TRAIN+HELD 每帧生成 6 类部件掩码（background/hair/body-skin/face-skin/clothes/others）parts-*.png 与高分辨率头发掩码 hair-*.png（confidence≥0.6 且落在 head mask 内），并写 audit.json：类别像素计数、各掩码 sha256、hair 与 face-skin 冲突像素数。刻意两套掩码并存并测量分歧，不静默重标像素、不把高分辨率头发画到 FLAME 皮肤表面（:62-64）；报告明确标注 2d_component_observations_only_not_3d_geometry，2D 标签不能确立头发厚度或 3D 深度（:80-88）。守卫：capture 哈希、两个 tflite 模型哈希（:36-40）、segmenter 标签集合（:45-48）、帧尺寸 1920×1080（:54-55）。生产链取用的是其常量与 segmenter() 工厂而不是 run()。

- **被谁调用**：components_v2.py:48（唯一现役引用：make_masks() 函数体内嵌套 import MODEL_DIR/PART_MODEL/HAIR_MODEL/PART_SHA256/HAIR_SHA256/segmenter）。与 usage-graph.json 的 1 条 nested import 入边一致。archive/v2/probe_component_seed_support.py 为历史引用，非现役。
- **加载方式**：按需（仅当 components_v2.make_masks() 真正执行、生成组件掩码时才会 import；训练子进程启动时不加载）。文件自带 __main__ CLI（python probe_portrait_components.py <job>）可人工整批运行。
#### `probe_static_alignment.py`

研究探针：比较“仅静态掩码”SfM 与当前“人物混入”SfM 的相机一致性。best_model() 在目录中选取注册图像数/3D 点数最多的子模型；run() 用 pycolmap.align_reconstructions_via_proj_centers 把静态重建对齐到参考重建（默认 mixed，即 job/sparse/0），对齐失败抛 static_camera_alignment_failed；随后统计共同视角的相机中心残差（中位/P90，场景单位）、朝向残差（中位/P90，度）、公共尺度、静态注册视图数、每 20 帧分节覆盖、最长缺失 run 与各连通子模型大小，打印 JSON 报告。支持 --source incremental/global/calibrated 与 --stride。

- **被谁调用**：probe_flame_observations.py:20（顶层 import best_model，调用点 :62，用于为 worldObservation 选世界相机模型）。与 usage-graph.json 的 1 条 import 入边一致。archive/v1、v2 约 15 个历史脚本引用 best_model，非现役。
- **加载方式**：常驻（随 probe_flame_observations 在训练子进程/worker 准备路径启动时被顶层 import 拉入；注意本模块顶层 import pycolmap 与 scipy.spatial.transform，这两项重依赖也因此进入启动路径）。也可 CLI 人工运行（--stride/--source/--reference）。
#### `runtime.py`

测试引擎路由与"实际发生了什么"执行回执。training_profile_options（14-54）校验局部/房间/头发/皮肤训练步数预算（local 1–900、room 1–600、hair 0–240、skin 0–240，:23-28）与各 opt-in 开关（必须布尔、必须 native-fullframe 适配器、依赖链如 hair 需 denseSurfaces、opaquePerson 需 observedFaceDomain），拒绝任何隐式进入生产档的组合；pipeline_entry（57-75）决定训练子进程入口：legacy→portrait_pipeline.py（300 步），native-fullframe→live_fullframe.py，且先用 implementationSha256（code_identity 闭包哈希）或四个必需文件的逐个 SHA-256 验证源码未变；engine_profile（78-88）读取 engine-profile.json，拒绝未知引擎并要求 userTestingAuthorized=true。reconstruct_test（330-444）组织整条子进程训练：复用同源缓存（277-289）、拼 CLI 开关、把子进程 stdout 的 JSON 进度行映射成 job.json 进度（359-380）、核验 report 的 sourceSha256/engineVersion、执行 observed-face 与 repair 回执后，才把 PLY/view 复制到传输路径并写 portrait.algorithm.json（含训练步数、显存峰值、执行回执）。worker_identity_status（91-119）在心跳里比对 worker 启动时加载的闭包哈希与磁盘现状，不一致即要求重启；training_execution_receipt（155-205）从 local-init.pt（经 checkpoint 安全加载）统计实际初始化/分组，repair_execution_receipt（208-274）把 opaque-interiors/surface-footprint/room-window-recovery 的声明绑定到真实文件字节。

- **被谁调用**：worker.py:413（run_one 测试分支）、worker.py:571（refresh_worker_capability）、worker.py:598（preflight）三处均为函数内导入，是整个生产链的唯一调用方；仅测试：tests/test_runtime.py:9、tests/test_runtime_repairs.py:10、tests/test_live_fullframe.py:12 顶层导入；code_identity.py:12 把它列入 ROOTS 快照（哈希清单）。
- **加载方式**：按需（仅 worker 特定函数/分支内导入，worker 进程启动时不加载）；另有 仅测试 与 仅快照引用。
#### `scene.py`

在画像世界坐标里恢复已拍摄的房间/衣物观察。make_environment_masks（10-28）把 scene_exclusions 膨胀一个小半径（0.6% 边长的 3–9px 圆核）后取反，得到"可见环境"掩膜；foreground_clearance（31-65）在 -65°..+65° 每个相机轨道（含未拍视角）检查候选房间点是否可能盖住头部轮廓（横向/纵向 ≤ 头半径×1.15+splat 半径，且头后要保持在头后）；environment_view_support（68-98）统计每个高斯的可见次数与被掩膜支持次数（要求 ≥3 且 ≥可见的 18%），并限制屏幕半径 ≤30px；seed_recorded_scene（101-187）在环境掩膜内、通过误差≤3/轨迹≥3 门槛的稀疏点基础上，对 24px 网格用 k=4 实测深度插值（距离<360px、跨距≤0.35）反投影成世界种子，颜色取原始视频像素，最多 2 万点写 environment_seeds.npz 与 environment_quality.json；supported_static_surfaces（209-337）对每视角候选静态点做 Delaunay 三角化，只接受边长 7–80px、深度跨度 ≤6%、法线朝相机的三角形，重心采样需 ≥3 个互一致（颜色差<0.10）的其他视角且冲突 ≤1，输出带逐样本 lineage 的 npz 供 native 链（components_v2/live_prepare）使用。recover_environment_points（340-435）用独立房间 SfM + 共同投影中心 Sim(3) 对齐后导出房间种子——当前无任何调用者（已 grep 确认）；environment_view_support 亦无生产调用者（仅定义）。

- **被谁调用**：worker.py:449 函数内导入 seed_recorded_scene（legacy 链，453 调用）；components_v2.py:25 顶层导入 supported_static_surfaces（components_v2.py:324 调用）、live_prepare.py:26 顶层（live_prepare.py:249 调用）——这两者使 scene 在 native 链子进程启动即加载；observed_surface.py:74 嵌套导入 surface_barycentrics/surface_sample_identity；tests/test_cancel.py:15（patch）、tests/test_scene.py:10、tests/test_surface_stage.py:6 顶层导入。
- **加载方式**：按需（worker legacy 分支内导入）；在 native 链随 components_v2/live_prepare 顶层导入而 常驻；另 仅测试。
#### `shared_v2.py`

SELF 隔离的"五部件共享前向、原生 ROI"重建试验原型（生产训练器不改）：initialize 把 prior 表面绑定与 local 观测投票变成部件化高斯参数与来源表（生产在用）；boxes 给每帧算标签框；mesh_depth 渲 FLAME 网格深度先验；train() 跑 1800 步 gsplat，配 ComponentStrategy（AbsGS 梯度+每部件增长预算/策略，参数替换走安装版 _update_param_with_optimizer，绑定/来源/置信字段跟随真实父替换同步）；audit 在 development+reference 上算 faceCore/room RGB L1、覆盖率、孔洞比；closest_surface_binding 做最近局部三角的精确重心绑定。注意：train/audit/closest_surface_binding 当前无生产调用，仅测试 import ComponentStrategy/torch_sh_rotate/initialization_reference。

- **被谁调用**：真调用：顶层 import portrait_pipeline.py:27（initialize ← 201、boxes ← 297）；函数内 import live_surface_footprint.py:130（mesh_depth）；测试 tests/test_components_v2.py:11、tests/test_shared_reference.py:3。其余函数无调用者。
- **加载方式**：常驻（portrait_pipeline 顶层 import，随重建子进程启动即加载）；train() 等训练试验入口无调用点。
#### `static_planes.py`

有限、由测量 track 支撑的静态平面假设（无房间背景板）：fit_plane_groups 用确定性 RNG(82) 做 320 次三点点采样+最多 3 轮 SVD 精修（每轮精修要求 singular[1] < singular[0]×0.12 才收敛，:27/:29），把 room 点分成若干平面组（tolerance=0.0025*scale、每组>=24 inliers、最多 8 组、记录 residualP90）；finite_plane_support 在每组凸包内投影采样，允许沿真实图像语义/Canny 边缘内的已观测连通区生长但上限 min(h,w)*0.12，逐点要求 >=3 个其它视图颜色认同(|Δ|<0.10)且冲突<=1，按 plane-local 空间格身份去重，产出带 plane_id/法线/父 track 的候选点。平面是几何假设、经训练观测验证，不是测得的稠密墙。

- **被谁调用**：真调用：observed_surface.py:160-161（prepare_surface_stage 内函数级 import）；archive/v4 旧版 reconstruction_static_planes 曾直接调用（非现役）；无任何测试可达：tests/test_surface_stage 只导入 observed_surface 的 observation_domains/finite_triangle_samples 与 surface_density.split_surface_parameters，不触发 prepare_surface_stage。无 __main__、无其它生产调用者。
- **加载方式**：按需（唯一现役入口是 --surface-refine 的 prepare_surface_stage 内 import）。
#### `surface_density.py`

有界切向表面分裂（仅 --surface-refine 试验）：select_surface_parents 从 gsplat 渲染 info 取 environment 侧（gaussian_ids>=头部偏移）、薄（scale_z<0.30*min(scale_xy)）、半径>4px、梯度非零且 generation<2 的 room 父点，按 grad*radius 取前 384；split_surface_parameters 沿父点最大尺度轴 ±0.45σ 复制两个子点、子尺度乘 .70、opacity 按 1-sqrt(1-alpha) 重算，并把 Adam 参数/动量/状态连同全部字段整体搬移（手工重建 optimizer param_groups 与 Adam 状态 :31-39，并逐字段迁移 scene 的 uid/父 uid/generation/来源字段 :40-54；不调用 gsplat 的 _update_param_with_optimizer——该函数只出现在 shared_v2.py），不全局收缩、不重置不透明度、不剪枝。

- **被谁调用**：真调用：portrait_pipeline.py:505-507（训练循环 stage=='T3' 且 scene.surface_refine 且 step==99 且 steps>=200 时函数内 import 并调用）；测试 tests/test_surface_stage.py:8 顶层。无其它调用者。
- **加载方式**：按需（唯一生产入口是训练循环内的函数级 import，且只在 --surface-refine 实验重置的 T3 第 99 步触发）。
#### `surface_recovery.py`

训练产物中"表面初始化证据"的留存与迁移（不改写 checkpoint 身份）：retain_surface_initialization 先校验 manifest 哈希与 source 哈希，再把 room/body 组件与声明过的证明闭包（窗口恢复/第二参考/自身参考依赖）复制进 state_dir，原清单字节原样另存并二次校验，产出 relocation 索引以便临时作业输入被清理后仍能解析；_window_proof_closure 只沿声明的验证图走（窗口收据、深度清单等作为 provenance 叶保留字节精确），绝不递归遍历任意 JSON 路径、不保留 RGB/视频/推理缓存；_historic_identity 用 Windows/POSIX 词法身份跨平台解析旧路径；retain_runtime_surface_initialization 从最终 checkpoint 的 surfaceContract.manifestSha256 反查精确清单再调用前者。

- **被谁调用**：真调用：retain_runtime_surface_initialization ← runtime.py:432-433（训练后 report.denseSurfaces 时函数内 import，属活线收尾）；_window_proof_closure ← live_room_self_reference.py:153；反向：本文件 143/319 又 import live_room_self_reference.retain_self_reference_dependencies；测试 tests/test_surface_recovery.py:4、tests/test_surface_recovery_window_closure.py:8。live_room_self_reference.py:186 的 "surface_recovery.py" 是快照清单。
- **加载方式**：按需（runtime 训练收尾与自参考证明闭包处函数内 import；仅测试顶层）。
#### `train.py`

早期单场景 gsplat 训练器，现在主要作为 smoke 与两个被复用函数。smoke（19-39）用单个 3D 高斯做 64×64 CUDA 光栅化前向+反向，验证 gsplat 在本机种子上可用；load_scene（52-73）把 PyCOLMAP 重建转成 (帧路径, cam_from_world 4×4, 内参, 宽, 高) 相机列表（要求 ≥16 个已注册）与 300–250000 个稀疏点及颜色；observed_head_splats（76-104）只保留在任一视角投影落入真实头部掩膜内的高斯中心（去不支持几何，掩膜已膨胀留边）。train()（107-278）从稀疏点初始化全参数（means/scales/quats/opacities/sh0/shN），按场景尺度设 Adam 学习率与 DefaultStrategy 致密化，逐视图 L1 损失只算头部掩膜内像素并加核心脸框加权与头外 alpha 惩罚，留出视角评 PSNR：均值 ≥18、最差 ≥15、alpha 泄漏 ≤0.12、保留高斯 ≥1200 且 ≥支持数 65%，导出 PLY 并写 training_metrics.json；update_progress（42-49）单调更新 job.json 进度。CLI 支持 `train.py JOB_DIR` 与 `--smoke`。

- **被谁调用**：train_joint.py:24 顶层导入 load_scene/update_progress（train_joint 子进程启动即加载，train_joint.py:84 调 load_scene、:268 调 update_progress）；worker.py:626 在 preflight 内导入 smoke（每个 worker 进程只跑一次，_SMOKE_OK，worker.py:29,625-628）；tests/test_face.py:13 顶层导入 observed_head_splats；setup_reconstruction_wsl.sh:41 在安装时一次性把 `train.py --smoke` 当子进程跑；主训练 CLI `train.py JOB_DIR` 当前无调用者（已 grep 确认，archive/v2 用的是旧名）。
- **加载方式**：按需（worker preflight 里只调 smoke；被 train_joint 顶层导入以复用 load_scene/update_progress）；另具 子进程入口（setup 脚本 --smoke，一次性）；JOB_DIR 训练入口当前无调用者。
#### `view.py`

从已注册源视图推导"开场机位"并给覆盖证明。derive（15-74）读 COLMAP 模型与 face_regions.json：只考虑有姿态且检出脸框的帧，取框内 3D 点中位数（3.5σ 去离群）为注视中心，计算相机中心/前向/深度，按脸框占比反推 fov（钳在 12–70°），以可见轨迹数+脸部占比-偏心度打分，并且只在按名称排序的前 1/5 帧（至少 3 帧）里挑选，避免开场就是后期侧脸；输出 portrait.view.json（schemaVersion/sourceFrame/target/camera/up/fov 等，safeYaw/safePitch 由 worker 追加）。coverage（77-117）只用恢复的相机位置（不用估的头部朝向）绕 target 统计偏航/俯仰，broadSideCoverage 要求 |yaw|≤55° 内 ≥7 个 10° 直方柱且左右各 ≥2 个视角。模块 CLI（120-126）可单独写 portrait.view.json，但当前没有任何脚本调用（已 grep 确认）。

- **被谁调用**：worker.py:348 opening_view 函数内导入 derive/coverage（生产唯一调用点，347-365 追加安全视角区间）；无测试直接 import view.py（已 grep 确认，graph 的 in_tests 是经 worker 闭包的传递可达性，tests/test_cancel.py:69 只是 mock 掉 worker.opening_view）；CLI `view.py JOB_DIR` 无调用者。
- **加载方式**：按需（仅 worker.opening_view 内导入）；另有 __main__ 子进程入口形态但当前无调用者。
#### `worker.py`

WSL 侧常驻单进程重建 worker（与 Windows HTTP 服务共用 SELF_RECON_JOBS_DIR 作业目录，通过文件而非 import 通信）。主循环轮询作业目录：对每个 queued 作业先校验 capture.mp4 字节数与 SHA-256（fail-closed，114-120）；再按 engine-profile.json 选路——engine 为 portrait-first-soft-surface-test 时调用 runtime.reconstruct_test（测试链，413-427），否则走 legacy 链：按时间桶选最清晰帧并记录 ffprobe 逐帧 PTS（123-238）、Haar 人脸区域（241-262）、统一人物+房间 COLMAP SfM 且人脸/房间轨迹数必须达标（265-324）、pose.prepare_face_views、observations.build_observation_bundle、view.derive/coverage 并写入 safeYaw/safePitch（347-365）、scene.seed_recorded_scene（449-453），最后以子进程启动 train_joint.py --best-effort 并校验 PLY 魔数、4KB–256MB 体积（327-344），发布 gaussian_ready。每个作业由 supervise_job 再 fork 一个隔离的 `worker.py --job <id>` 子进程执行，取消时对进程组 SIGTERM→SIGKILL（540-567）；finish_cancel 重试删除所有私有输入后才写 cancelled。main 用 flock 保证单实例（654-658），preflight 校验 RTX 5070/sm_120、≥7.5GB 显存、ffmpeg/ffprobe、模型文件、gsplat 与 train.smoke（596-635），心跳每 5 秒写 worker_status.json 并做源码身份校验。

- **被谁调用**：由 scripts/Start-ReconstructionServer.ps1:44 以 wsl.exe python 启动（唯一真实生产入口）；worker.py:542 对每个作业把自身按路径再启动为隔离进程；仅测试：tests/test_cancel.py:12（调用 supervise_job，:130）、tests/test_runtime.py:8、tests/test_recon_transfer.py:103（嵌套 from worker import finish_cancel）；code_identity.py:12 把它列入 ROOTS 闭包快照（哈希清单，不是调用）；tests/test_cancel.py:114 只是在临时目录写一个同名 worker.py 桩脚本来测试取消逻辑，与生产模块无关。
- **加载方式**：子进程入口（主：ps1 启动、自我再启动）；另被 tests 顶层导入（仅测试）与被 code_identity 快照清单引用（仅快照引用）。

## 六、测试（`backend/tests/`）

52 个用例文件 + `__init__.py`。`__init__.py` 把 `tests/` 与其父目录加入 `sys.path`，
因此 `from test_contracts import …` 与 `import runtime` 在任何启动方式下都成立
（WSL 是 Python 3.10，没有它 discovery 不会进入 `tests/`）。

按文件名排序：

#### `test_cancel.py`

worker 输入留存与取消清理：finish_cancel 在 rmtree 首次 OSError 后重试（重试期间仍是 cancel_requested），成功才置 cancelled 并删除 frames；成功重建在发布前丢弃 capture/frames，目录只留 job.json 与已发布资产；discard_training_inputs 只保留已发布文件；失败作业清掉 capture 并置 failed；posix-only 用例验证 supervise_job 真正终止运行中子进程并删除 capture。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4；posix 类在 Windows 上 skip，WSL 跑）
- **加载方式**：测试
#### `test_capture_reference.py`

capture_reference 采集参考合同：已有合法参考保留并可 preferred 覆盖、稀疏正面峰值回退到真实时间窗口（窗口只有真实三帧）、development 角色与缺失 world 不得借用、仅索引相邻不当作时间证据（no_supported_body_window）、纯旋转报 insufficient_actual_camera_baseline、世界尺度不变、重复时间戳不算三视角、frame manifest 的 captureSha256 不符报 source_mismatch。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4）
- **加载方式**：测试
#### `test_capture_registration.py`

静态 2D–3D 注册合同：existing_static_window 要求真实相机基线且排除 development 图像；propose_windows 用真实文件名/时间戳与训练锚，每窗 ≤9 帧、跨度 ≤1.75s、两锚间隔 >3.5s；track_split 训练/留出轨迹 ID 不相交、对逆序输入稳定、重复 ID 报错；quality_accepted 大匹配数不能绕过留出几何；projection_quality 用 pycolmap 实际投影与正深度算中位像素/网格/凸包占比。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4；需 pycolmap 的用例在 Windows venv 报错）
- **加载方式**：测试
#### `test_care_conversation.py`

眼周圈选后问“怎么保养”的回归：校验 RECORDS 与 DOSSIERS 对齐及 74 条身份索引、眼周意图命中 CN008/CN024、图像解剖部位决定护理品类（脸颊/额头/鼻/下巴不得落 eye、痘肌落 cleanser）、用户拒绝或已推荐过则停止推产品、未核实用量/唇色被拒、同答同问判重；ModelQuality 用 httpx.MockTransport 打桩真实 propose/converse（test-only key），验证重复计划补答一次才展示、repeated_response 永不达用户、缺 selectionObservations 时补检而非编造解剖、文字护理路径不夹带图片。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4，WSL 同 README.md 第三节）
- **加载方式**：测试
#### `test_checkpoint.py`

checkpoint 安全读取合同：只放行张量与 NumPy 白名单（含 np.str_/np.float32 标量作为数据），未批准的 __reduce__ 全局在反序列化前被 unsupported_checkpoint_globals 拒绝；哈希不符在加载前报 checkpoint_hash_changed；restore_tensors 要求字段完整、类型一致，并保持 Parameter/buffer 角色、requires_grad 与 state_dict 取值。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4）
- **加载方式**：测试
#### `test_components_v2.py`

五部件坐标与优化器回归：torch_sh_rotate 与 appearance_direction_contract.sh1_head_to_reference 数值一致（3e-7）；CUDA 下 render_components 五组守恒 <2e-6、组件深度之和等于总深度、实数梯度与 absgrad 存在（无 GPU 时该用例跳过）；ComponentStrategy 父部件替换保持 source_index/generation 绑定、重心归一、Adam 动量形状随参数。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4；CUDA 用例需 GPU）
- **加载方式**：测试
#### `test_contracts.py`

Plan/Snapshot 与 parse_response/validate_plan 的边界合同：多区域试色原子且有界、英文只作展示层不得改区域/预设、明确“只想聊”不得输出编辑、数字回复必须绑定上一轮选项、圈选区域优先于其他登记区、未知/多余字段与伪造引用一律 ModelFailure、上传未授权被拒、图片必须是真实 image_url 块、护理指南产品必须来自已登记 careOptions 且不得宣称产品效果（痘痘护理 CN029 须声明非祛痘治疗）；同时为其他测试导出 snapshot()/plan()/response() 夹具。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4，WSL 同 README.md 第三节）；作为夹具模块被 test_care_conversation/test_http/test_product_catalog/test_live* 等导入
- **加载方式**：测试
#### `test_face.py`

人脸几何小检查（文件注明用 WSL 重建 Python 运行）：head_box 为侧脸保留边距；make_head_mask 拒掉远处背景小连通块并报告占比 <0.4；静态特征掩码把配饰归零、保留相机阴影；train.observed_head_splats 只保留落在相机前方与画面范围内的头部样点。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4；须 WSL 重建环境，Windows venv 因缺依赖报错）
- **加载方式**：测试
#### `test_flame_observations.py`

FLAME 局部 F_t 约定与永久 GS 绑定的回归：非零 shape/neck/jaw 下 root_neutral_contract 误差 <2e-6 且 F 旋转部分明显偏离单位阵、顶点形状为 5023；5000 个重心绑定采样点在 template 位移后增量严格等于重心插值（1e-7）；legacy STANDARD_MODEL 与 Open 模型同拓扑但系数与哈希不同。模型或嵌入文件缺失时整体跳过。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4；需本地 FLAME 资产，缺则 skip）
- **加载方式**：测试
#### `test_flame_open_model.py`

本地 FLAME 2023 Open 模型的数值契约：零参数下顶点等于 template、关键点等于 landmark 面重心插值（容差 2e-6）；根旋转严格等于绕关节的刚体旋转公式；shape/expression/jaw 三个梯度均有限且非零；MODEL/EMBEDDING 缺失时跳过。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4；需官方 FLAME 资产，缺则 skip）
- **加载方式**：测试
#### `test_http.py`

进程内 FastAPI HTTP 边界（httpx ASGITransport 直连 app.app、propose 被 AsyncMock 打桩）：无令牌 401 且绝不触达 planner、上传未授权与多余字段 422 且不回显、Content-Length 非法 400/超大 413、重复请求幂等（上游只调一次）而改载荷 409、模型失败 502 且不写缓存/不残留 inflight、in-flight 409 与限流 429。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4）
- **加载方式**：测试
#### `test_joint_visibility.py`

joint_visibility 共享光栅化：posed_points 让头部随校正变换移动而房间保持世界坐标、恒等时顶点不动；CUDA 用例验证 render_shared 守恒误差 <2e-5、人像 q 高于环境 q、visible_point_scores 在高权重区给出更高可见度且全部有限。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4；CUDA 用例需 GPU）
- **加载方式**：测试
#### `test_live.py`

手工付费能力探针（无 TestCase，0 个 discover 用例，仅 __main__ 守卫）：用自绘红圆/三蓝方块原创合成图发起真实 DeepSeek HTTPS 调用，断言中文 shortMessage 报出主色+形状+数量并为已登记 lip 选出 rose/terracotta 轻度数字试色，结果写 docs/evidence/deepseek/live-results.json；缺 API key 记为 unverified 且不发送请求。

- **被谁调用**：Test-Backend.ps1 -Live（scripts/Test-Backend.ps1:6 显式运行 backend/tests/test_live.py）
- **加载方式**：测试
#### `test_live_care.py`

手工付费视觉/工具探针（无 TestCase，0 个 discover 用例，仅 __main__ 守卫）：自绘合成人脸图上分别发“圈了痘痘”与“圈选脸颊养护”两问，断言返回 careGuide 且产品为 CN029（痘）或 CN001/CN005（养护）、decision 非 edit、operations 为空，结果尝试写 artifacts/live-care-20260926.json（受限 Python 主机可只取已打印的非个人化摘要）。

- **被谁调用**：手动运行（python backend/tests/test_live_care.py）；不在 Test-Backend.ps1 -Live 链路（脚本只跑 test_live.py）；discover 0 用例
- **加载方式**：测试
#### `test_live_dense.py`

live_dense 深度窗口全链路合同：工具源码锁（提交号/逐文件哈希/未登记 .py/空锁/../ 逃逸路径）；静态轨与新增 world 相机必须有 accepted_fixed_map 证据且地图未变；参考帧选择与 body 近时窗口、无 split 与研究 split 的 head/body 边界、连续真实相机窗口；单窗口尺度训练/验证锚互斥（live_depth_scale.fit_window_scale）；半像素裁剪回原生坐标、平面足迹与深度边缘、多视角/遮挡/低置信度支持分开；跨窗冲突不平均、预算不混色、请求拒绝几何变化与训练角色泄漏。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4）
- **加载方式**：测试
#### `test_live_dialogue.py`

手工付费两轮对话探针（无 TestCase，0 个 discover 用例，仅 __main__ 守卫）：用公共许可人脸扫描图先问“淡一点的颜色有哪些”，断言首轮 clarify 且 ≥2 个 choices 且无操作；再回“1”断言解析为 edit、仍是同一圈选区域、保持 light 强度、不得夹带 rose/terracotta/regionId 等内部词；结果写 docs/evidence/interaction-camera/live-dialogue.json。

- **被谁调用**：手动运行（python backend/tests/test_live_dialogue.py）；不在 Test-Backend.ps1 -Live 链路；discover 0 用例
- **加载方式**：测试
#### `test_live_face_domain.py`

live_face_domain 与 portrait_pipeline 联动合同：observed_empty 域排除低置信与冲突像素；head_loss 只在显式 training_empty 掩码存在时生效（否则退回旧掩码并计 reliableEmpty）；observed_empty_space 开关在任何 CUDA/副作用前要求 observed_face_domain；restore_recorded 重放标志并拒绝哈希/标志变化；development 皮肤缺失不填像素也不中止；surface_contract_matches 只容忍枢轴舍入；连通额头保留且未知/无效像素永不划入脸域。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4）
- **加载方式**：测试
#### `test_live_fullframe.py`

检查 native-fullframe 入口与画布合同：pipeline_entry 要求 live_fullframe/portrait_pipeline/portrait_model/appearance_direction_contract 四个源码哈希完全匹配（改一处即 hash_changed）、native_frame 保留原生像素与裁剪 K、CUDA 下 person 颜色通道与全画布协方差相对参考实现的像素和梯度一致、NativeScene 让人物与房间处于同一合成。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节；scripts/Test-Backend.ps1:4）自动收集；backend/tests/__init__.py:8-12 注入 tests/ 与 backend/ 到 sys.path
- **加载方式**：仅测试（unittest discovery 导入；LiveCudaContractTest 无 CUDA 时整套 skip，:43-44）
#### `test_live_hair_composite.py`

检查 live_hair_composite.masked_parameter_step：真实背景可打破黑底下的不透明度歧义（前景=目标时 logit 梯度为负），且 Adam 每步只更新头发行的参数与动量，非头发参数行必须与非经该函数更新的冻结副本逐位相等。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节；scripts/Test-Backend.ps1:4）自动收集
- **加载方式**：仅测试
#### `test_live_hair_motion.py`

检查 live_hair_motion 头发运动合同：保存后重新推理的传输只容数值舍入并能识破变换/数组篡改、凭证不匹配即reinfer_required，稠密相机与 SceneAssembly 共用同一参考传输路径，非恒等头姿下关节链/协方差/SH 极旋转精确，根、下巴与非参考表情不拖拽头发而蒙皮（part<=1）前缀保持不变，identity/legacy 行为显式且坏名字报错。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集
- **加载方式**：仅测试（live_dense/portrait_pipeline 在测试方法内按需导入，:44-45）
#### `test_live_http.py`

手工付费本地后端探针（无 TestCase，0 个 discover 用例，仅 __main__ 守卫）：对运行中的 127.0.0.1:8787 先探 /health 再 POST /v1/edit-plans（red-circle 原创夹具，可选 SELF_BACKEND_TOKEN），断言同一请求重放幂等一致、中文视觉描述匹配、唯一操作是 rose 轻度 set_digital_tint；结果写 docs/evidence/deepseek/live-http-results.json。

- **被谁调用**：手动运行（python backend/tests/test_live_http.py，需先启动后端；docs/model-contract.md:48 记载此链路）；不在 Test-Backend.ps1 -Live 链路；discover 0 用例
- **加载方式**：测试
#### `test_live_language.py`

手工付费英文回复探针（无 TestCase，0 个 discover 用例，仅 __main__ 守卫）：公共许可人脸样图配 responseLanguage='en' 与“保留痣、只想聊”输入，断言无 operations、无 explanationRefs 且回复/提问不含任何 CJK 字符；结果写 docs/evidence/camera-fullscreen/live-english.json。

- **被谁调用**：手动运行（python backend/tests/test_live_language.py；docs/model-contract.md:55 记载）；不在 Test-Backend.ps1 -Live 链路；discover 0 用例
- **加载方式**：测试
#### `test_live_neck_appearance.py`

检查 live_neck_appearance 颈部外观点选择：必须有三张互异的原生全画布支撑视图，观察足迹触及受保护区域会被否决且头发不参与，其他视图可只否决不投票；低颈部占比不扩大编辑范围；point_region_contributions 的通道导数是对模型（means/scales/opacity/sh）完全脱离的精确线性累加。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集
- **加载方式**：仅测试
#### `test_live_neck_motion.py`

检查 live_neck_motion 颈部物理运动：非恒等绝对头姿下参考仍精确、运动只相对头姿；只有前 5 个颈部点变形，布料/房间/alpha/底部颈部逐位不变；解析雅可比与参考场有限差分一致；协方差/导出因子不丢 quats/scales 训练梯度；无或单点颈部不造几何；非法层数/非刚体帧/拓扑变化报错；场景拼接保留两来源协方差与梯度。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集
- **加载方式**：仅测试
#### `test_live_opaque_person.py`

检查 live_opaque_person 不透明人物损失与掩码：房间 alpha 不得顶替人物不透明度、条件颜色不得拿 alpha 换亮度、部件映射只留皮肤/身体不留房间/头发/镜片；掩码排除头发/眼镜/未知区域并记录原生腐蚀半径；空区域零监督、body 阶段不监督冻结脸、结构误差只看原生边缘而非掩码边缘。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集
- **加载方式**：仅测试
#### `test_live_room_completion.py`

检查 live_room_completion 房间补全：未覆盖的观察房间不受人物轮廓限制、只去重兼容的新样本、参考遮挡不等于房间/前景；空参考集必须原样保留父资产且额外预算有硬上界（30000）；补全回放只能按已记录的选择与合格证明在受限预算内重放（文件被改、采集/几何不匹配、未入选解、缺证明均被拒），且不改动原文件。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集
- **加载方式**：仅测试
#### `test_live_room_reference.py`

检查 live_room_reference.choose_reference_candidates：单个 held 轨迹缺口不放宽 held>=12 / fit>=20 阈值也不更换主参考、且不修改输入行；同一参考的多个深度窗口只算一次尝试，去重后保留首个与另一条独立参考。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集
- **加载方式**：仅测试
#### `test_live_room_retry.py`

live_room_retry 的合同单测（非付费探针）：二次参考只按独立验证轨支持度排序（不看名字/RGB）、绝不尝试第三个参考、成功后或有条件通过后不再重试；求解预算必须有限（0/41/True 直接报 budget）；complete_room_recovery 只调一次求解器并把结果嵌到 second-reference/result.json、无可选参考或预算用尽时原样保留首轮结果、程序异常照常抛出且不重复二次尝试。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4）
- **加载方式**：测试
#### `test_live_room_self_reference.py`

live_room_self_reference 的合同单测（非付费探针）：eligible_self_correction 只把一条过时负证据移出且不改原数组；load_component 要求显式 receipt 契约且任何独立 free/colour 失败仍须拒绝；apply_self_reference_correction 在禁用/已尝试/无合格表面时幂等保留原 bundle，合格证明缺失或变化报错，合格时按预算调用一次并盖 invokedByLivePolicy；再用 AST 抽取 portrait_pipeline 恢复分支验证分派 AUTHORIZED_POLICY 与 resume 跳过。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4）
- **加载方式**：测试
#### `test_live_room_window_recovery.py`

live_room_window_recovery 的合同单测（非付费探针）：无合格基础表面时不动捕捉、不选参考、不调求解器并原样保留 bundle（no_qualified_base_surface）；基础 receipt 变化必须报错而非降级；新入口收敛到受限二次参考（extra_budget=30000）；窗口提议固定相机与训练边界、scale 门失败无求解许可；depth_agreement/surface_pair_overlap 阈值、footprint 含画外核且不扩 alpha、alpha 并集与排序无关；预算参数上限校验。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4）
- **加载方式**：测试
#### `test_live_shared_room_surface.py`

检查 live_shared_room_surface 共享房间表面：分区基权重与零状态保持原始世界点、跨相机视差与跨格连续性精确、重复观察不改变物理点折叠、一图一票且冲突来源判为歧义、替换预算绝不重选原表面；apply_shared_room_correction 对证据不足/验证不过/编程错误/深度清单变化/回放不匹配分别保留父资产、记未生效收据或直接抛错，并断言 live_dense 的开关默认关闭。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集
- **加载方式**：仅测试（live_dense.augment_prepared 在测试内按需导入，:79）
#### `test_live_skin_compositing.py`

检查 live_skin_compositing 皮肤合成：被遮挡视图不投票也不全局改标、非激活行保留数值与 Adam 动量、背景一致性用颜色歧义反推不透明度、未知/头发/镜片排除、空观察零损失、单角度退化不能藏在平均值里、椭圆内头发与未监督的脸受保护、无监督的 face 像素不得被改写。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集
- **加载方式**：仅测试
#### `test_live_surface_binding.py`

live_surface_binding 交接合同（非付费探针）：verify_room_completion 逐个校验基础与附加 receipt 及 expected_asset_hash，点参数篡改报 parameters_changed:means、来源索引越界报 unknown_point_proof；conditional 表面不得伪造三票深度、source/坐标系/support 不得静默修补；environment_from_components 保持缩放/UID/部件与层名映射；replace_hair_prior 追加头发样点而不改任何人脸参数。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4）
- **加载方式**：测试
#### `test_live_surface_footprint.py`

检查 live_surface_footprint 表面足迹适配：只改 log_scales/local_quats 并保持法向方差与代理覆盖、非蒙皮/无证据/语义屏障内点逐位不动、追加头发不重定向/缩放、退化三角形不产生假协方差、旋转与单位尺度等变；语义适配只读三张全通过训练视图（dev 行不读），并输出原生 sigma 与未接受质量的收据。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集
- **加载方式**：仅测试
#### `test_live_voice.py`

手工付费语气探针（无 TestCase，0 个 discover 用例，仅 __main__ 守卫）：“不喜欢鼻子”与“痣想留着、只想聊”两句公共许可样图输入，断言无操作、无产品引用、decision 非 edit、短回复 ≤120 字（语气本身须人工复核）；结果写 docs/evidence/interaction-camera/live-voice.json。

- **被谁调用**：手动运行（python backend/tests/test_live_voice.py）；不在 Test-Backend.ps1 -Live 链路；discover 0 用例
- **加载方式**：测试
#### `test_local_sampling.py`

检查 local_sampling 的 900 步局部采样调度：偶数帧数也均摊几何预算（205 几何/695 外观）且不改变外观序列，奇数帧数沿用原非混叠调度，保存的下一步能精确复现余下 900 步序列，非法计数/步号与重名抛 ValueError。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集
- **加载方式**：仅测试
#### `test_olay_discovery.py`

静态产物对角检查（无后端导入）：生成的内嵌浏览器 OlayDiscoveryRepository.ets 非 research 段恰好是 63 个 brand_2026_observed/catalog_only 身份且全部 can_render_product_effect=false，research 段补齐其余 CN/H 编号；官方新闻图库清单恰为 CN001–CN004 四张独立图片，均为 ≤512px 的 RGBA PNG（透明底）。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4）
- **加载方式**：测试
#### `test_person_supervision_state.py`

检查 person_supervision_state 的人物监督恢复：只有检查点 flag 与前次收据、掩码、观察名、足迹凭证、prior 字节全部吻合才恢复不透明头/体标志（且失败不在校验前改状态），legacy 状态清除陈旧 opaque_skin 掩码，复制失败不覆盖已有证据；并用 AST 断言三个 run_live_*_trial.py 都是先 restore_person_supervision 再做 audit。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节；scripts/Test-Backend.ps1:4）自动收集
- **加载方式**：仅测试（用 ast 按路径读取 backend 根目录的 run_live_*_trial.py，:112-121）
#### `test_pipeline_resume.py`

检查 portrait_pipeline.run 的续跑语义：零步恢复不得重新初始化/重读参考/重适配足迹/重恢复房间，必须恢复前次 opaque/soft/足迹/房间凭证并原样带过，resumeKind 记录在 config；改 flag、缺 config、房间凭证变化或检查点监督不一致都在导出前报错；头模型热启动恢复前验但接新房间环境且不载入旧全场景。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集
- **加载方式**：仅测试（GPU 调用全部 mock，torch 顶层导入，:78-98）
#### `test_portrait_model.py`

检查 portrait_model 可动画像几何：导入不筛选不换色、世界投影保持相机系均值/协方差/SH 方向（含非 1 尺度与旋转）、连通行走按语义屏障阻塞、软带只给蒙皮尺度梯度不压头发、共享表面残差获多视图梯度且被第二表情复用、父子替换与完整 Adam 回滚、被接受子点继承来源谱系、无效子点保留父点、非法父索引报错。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集
- **加载方式**：仅测试
#### `test_product_catalog.py`

product_catalog 事实与红线合同：“通用数字试色、不是产品效果”不触发产品而带 OLAY 产品名才触发；产品效果不得挪到未圈选区域、不得伪装成 explanationRefs 产品卡或降级为通用试色；CATALOG coverage=partial 且 inci/配方修订/物理参数/功效校准全为 None（不编造）；普通对话与情绪表达不注入产品；仅能引用本轮提供的资料且请求上下文带来源与未核实状态。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4）
- **加载方式**：测试
#### `test_recon_transfer.py`

/v1/reconstruction 传输与取消合同（TestClient，recon_transfer.ROOT 重定向到临时目录）：echo 回显与 x-content-sha256、分块上传幂等→seal→删除；坏摘要 422、未封存取资产 409、无鉴权 401；接收中/排队取消立即丢弃 capture（已封存经 worker.finish_cancel 转 cancelled）、运行中取消写 cancel.requested、流式上传中取消不得复原视频；完成资产须匹配字节数与摘要（篡改 409）；gaussian 只分块下载不冒充可编辑 mesh、越界分块 422；星形预览有界且校验摘要。

- **被谁调用**：unittest discovery（Test-Backend.ps1:4）
- **加载方式**：测试
#### `test_runtime.py`

检查 runtime/worker 执行路由与身份门：皮肤/头发步骤预算及前置依赖、CLI 参数与进度在 0..N 内钳制、准备缓存释放保留活跃张量、局部拟合字节与清单在像素清理后仍在、测试引擎派发并清理采集且不走 legacy、worker 闭环哈希变化即拒绝就绪并失效缓存、心跳在身份通过后仍保留 GPU 失败原因、训练/观察脸/修复收据只记录实际步骤与缺失计数。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节；scripts/Test-Backend.ps1:4）自动收集
- **加载方式**：仅测试（CUDA 全部 patch，:43-53）
#### `test_runtime_repairs.py`

检查 runtime 修复开关合同：opaquePerson/opaqueBody/surfaceFootprint/roomWindowRecovery 必须显式布尔且各有前置依赖（body 仅研究、不透明头/足迹需 observed face、房间恢复需共享稠密表面），reconstruct_test 只在请求时下发对应 CLI 标志且 live_fullframe 每个标志有且仅有一个定义，请求的修复若未实际应用即 requested_actual_mismatch，各修复收据与磁盘凭证哈希逐位绑定。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集
- **加载方式**：仅测试（ast 按路径读取 live_fullframe.py，:56）
#### `test_scene.py`

检查 scene 的房间可见性与服装连续性：前景净空让房间 splat 不能从正面或 65° 斜角穿过头部（后方与远处点保留），make_environment_masks 让头部以下服装区域仍留在房间掩码中而不被排除圈吞掉。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集
- **加载方式**：仅测试（cv2/numpy）
#### `test_scene_preview.py`

检查场景预览链路：create_scene_lod 的空间采样在限 8000 点时同时保留近端与远端 splat 且文件 <12MB；HTTP 的 scene-preview 必须带令牌（无令牌 401），无源视频也能从已就绪资产回填生成 LOD，重复请求幂等且 scene3d 资产哈希与返回 sha256 一致。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集；使用 fastapi TestClient（:11）
- **加载方式**：仅测试
#### `test_shared_reference.py`

检查 shared_v2.initialization_reference：显式指定的受支持第二参考被保留、缺失/开发集/无世界标定的参考被拒，未指定时选择训练集中人脸标记最宽的帧且不改写输入字典。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集
- **加载方式**：仅测试
#### `test_source_lineage.py`

检查 gsplat 1.5.3 的 split/duplicate/remove 在冻结 source_index 与 semantic 参数上的谱系行为：分裂/克隆让子点继承来源与语义、删除保留剩余来源，Adam 的 exp_avg/exp_avg_sq 与新参数形状同步（先有动量再改拓扑）；这是唯一不导入任何 backend 模块、直接测第三方策略算子的测试。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集；需 gsplat 包，Windows venv 缺 GPU 包时导入即报错
- **加载方式**：仅测试（仅顶层导入 gsplat.strategy.ops，:6；usage-graph 对此外向 0 条边）
#### `test_story_conversation.py`

检查 story_conversation 的纯文本对话边界：请求拒收 images/snapshot 字段与 base64/file_id 文本及 turns 内媒体、缺令牌 401，试色类请求走 edit_entry 且不下发 operations，真实产品效果请求必须落到 real_effect_boundary 且无可引用证据，发往模型的请求体不含 image_url/file_id/tool，取消语不得触发数字预览。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集；httpx ASGITransport 直连 app（:23-24）
- **加载方式**：仅测试
#### `test_surface_recovery.py`

检查 surface_recovery 的按字节保留与恢复：清单/组件/头发运动/求解证明拷进恢复目录后即使原路径被清理仍能按原哈希解析，输入被篡改或相对路径逃逸立即拒绝且不留目标目录，原始视频不落盘，runtime 用最终检查点清单合同恢复。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集；并被 test_surface_recovery_window_closure.py:9 以 `import test_surface_recovery as fixtures` 复用其 fixture/proof_fixture
- **加载方式**：仅测试（同时作为兄弟测试的 fixture 提供模块）
#### `test_surface_recovery_window_closure.py`

检查房间窗口证明恢复的递归闭包：第二参考决策/首次失败尝试/选择记录会随恢复目录字节保留并在原路径清理后可解析；证明链中嵌套的重叠/点证据缺一项、被篡改、被换成视频/凭据文件、或相对路径逃逸都会被拒（不复制 .mp4 与凭据文件）。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集；模块顶层 `import test_surface_recovery as fixtures`（:9）复用其 fixture 与 proof_fixture
- **加载方式**：仅测试（同时依赖兄弟测试模块加载）
#### `test_surface_stage.py`

检查观测-表面-分裂阶段合同：D2 质心与 D3+ 重心坐标一致且样本身份与索引顺序无关、安全护城河不误删真实观察的服装/房间域、三视图有限三角采样需 ≥3 支持且颜色冲突即整面拒绝、分裂退出父点并同步 Adam 与来源谱系。

- **被谁调用**：unittest discover -s backend -p 'test_*.py'（backend/README.md 第三节）自动收集
- **加载方式**：仅测试

## 七、其他目录与文件

| 位置 | 说明 |
|---|---|
| `archive/` | v1–v5 历史批次（不参与运行），逐批说明见 `archive/README.md` |
| `.data/reconstruction/` | 运行数据：作业目录、`engine-profile.json`（哈希钉）、worker 心跳与日志；不进 git |
| `.sources/` | 模型/工具来源快照（如 DA3 权重），不进 git |
| `models/` | 本地模型文件（如 FLAME），不进 git |
| `.venv/` | Windows 侧虚拟环境（无 torch/cv2/scipy） |
| `.env` | `DEEPSEEK_API_KEY`、`SELF_BACKEND_TOKEN` 等本地密钥，永不进 git、永不打印 |
| `requirements*.txt` | Windows（`requirements.txt`）与 WSL（`requirements-reconstruction-wsl.txt`）依赖、`requirements.lock.txt` 锁 |
| `setup_reconstruction_wsl.sh` | WSL 环境一次性安装脚本（CUDA、torch、mediapipe 固定版、`train.py --smoke`） |
| `reconstruction_baseline.json` | 基线记录（保留原名） |
