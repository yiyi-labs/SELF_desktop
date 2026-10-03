# 统一主体建模重构（2026-10-03）

## 1. 正式入口与生效链路（重构前确认）

- 鸿蒙端（`entry/src/main/ets/services/ReconstructionTransportClient.ets`）→
  `http://127.0.0.1:8787/v1/reconstruction` 五步协议（jobs→chunks→seal→poll→assets）。
- Windows：`app.py`（uvicorn）只做 HTTP 与落盘，不做任何像素处理；`recon_transfer.py`
  传输路由；`portrait_preview.py` 从已验证资产派生 preview/preview3d/scene3d LOD。
- WSL：`worker.py` 轮询共享作业目录 → `runtime.reconstruct_test` →
  子进程 `live_fullframe.py` → `portrait_pipeline.run`（52 文件算法闭包，
  `code_identity.py` AST 导入闭包哈希钉死，`engine-profile.json` 持钉）。
- 主资产 = `portrait.gaussian.ply`（客户端 `downloadGaussian` 分块下载 ≤256MB）；
  `preview3d`/`scene3d` 为显式 LOD（≤12MB），仅用于星图预览/星系场景；
  **未发现 preview 误用为正式资产**。

## 2. 定位到的根因（带作业证据）

旧正式作业 `f6d2117f…`（900/400/0 步路线）实测：

| 现象 | 根因（代码位置） |
|---|---|
| 脸纸片化 | 脸表面仅 8034 点、零增密；`live_fullframe.run` 显式拒绝 T4（`rejected_T2_cannot_enable_new_face_joint_updates`）；`pipeline_entry` 恒返回 joint=0 |
| 头/颈/身/环境割裂 | T3 全程冻头（`configure_stage` + 结束位级校验）；身体 part4 走独立 Adam 时钟；颈靠后验 binding 输运，从未联合优化 |
| 环境空洞 | 房间点全部来自 DA3 预算提案（30000/次），无增密补充；`surface_refine` 与 dense 互斥被禁 |
| 观测绑死人脸 | `live_prepare.fit_local` PnP<35 内点→整帧丢弃；`initial_appearance` 只在 face mask 内保点 |
| 容量闲置 | 8GB 显存峰值仅用 1.5GB；900+400 步、零增密事件 |

## 3. 唯一正式技术路线（已实施，非双轨）

统一主体 = FLAME 基底上的脸+颈皮肤+发（一个优化器一个时钟）+ 环境（房间+身体）
在同一渲染、同一损失下的分阶段联合优化；观测有效性三层拆分；受控增密+修剪。

1. **观测分层**：`fit_local` 仍只在 face-valid 帧拟合，但 PnP 拒帧降级为
   scene-valid 观测存 `scene_observations.npz`（最近拟合帧代理头姿态，含世界相机），
   `components_v2.load_prepared` 挂载；T3/T4 世界帧池纳入 scene 帧监督房间；
   `initial_appearance` 颜色支持扩到 `observed_body_skin`（FLAME 颈/颌皮肤获得真实点）。
   fitted 身份链（local_geometry.npz == fit checkpoint names/roles）逐字节保持。
2. **T4 统一联合阶段**：移除硬拒绝；`jointSteps` 进入 profile 契约（0..600 int）；
   T4 损失 = 房间 + 衣物 + 脸(.5) + 发(.3) + 颈皮肤(.3) + 不透明人物；
   全体一个 Adam 时钟（身体独立时钟仅限 T3）；
   环境外观/尺度/朝向可训、means 冻结（防跨物体补偿，见第 6 节）。
3. **受控增密**：T3 每 150 步对 room+body 选择性分裂（≤384 父/轮，gen<2，
   需保留≥150 步恢复预算，环境上限 140k 点）；T4 step120 脸部分裂
   （`replace_skin_parents` 事务，逐子点≥2 帧观测验证）；阶段末低透明度受控修剪
   （阈值 0.01、保底 70%，实测保守跳过）。所有行变更同步
   parts/initial_means/initial_scales/initial_quats/uid/parent/generation/
   sources/layers/neck_binding（子点继承父行）。
4. **容量**：local 900→1200、room 400→600、新增 joint 300、hair 180 不变；
   契约上限 local≤1600、room≤900、joint≤600。
5. **接口零改动**：`ENGINE_VERSION` 不变（客户端 `downloadView` 白名单兼容）、
   资产名/schema/端点/协议全不变；实现身份由闭包哈希
   （本次最终值见 `engine-profile.json`）与 Git 提交标识。

## 4. 外部兼容（鸿蒙端无需任何改动）

- `downloadView` 白名单 `'portrait-native-fullframe-20261002-research'` 保持命中。
- `portrait.gaussian.ply` 主资产、`portrait.view.json`（targetFaceFraction=.5、
  surfacePointCount≥30、assetSha256 一致）均按原 schema 产出。
- preview3d(≤12MB)/scene3d(≤12MB) LOD 上限不变（28000 点采样）。

## 5. 提交清单（master，里程碑式）

| 提交 | 内容 |
|---|---|
| f4f04fe | 统一主体路线主体：观测分层、T4、增密、接线（8 文件） |
| 818e0f8 | 身份链外置 scene_observations.npz + quats/颈绑定行同步 |
| 6a3e026 | 双优化器状态键同步（防 state_dict KeyError）+ 回归测试 |
| (amend 系列) | clear 移出组循环；子点验证器下标修复 |
| de5b0f0 | T4 冻结环境 means 防跨物体补偿；分裂恢复预算 |
| d9fc5a3 | README 事实同步 |

## 6. 调参证据（真实样本 self-quality-temporary-20260926.mp4，65MB）

- 直接验证（300/600/300/180 缩短路径）暴露并修复 4 个链式缺陷：
  einsum 维度（initial_quats 未映射）→ neck_topology_changed（绑定未同步）→
  state_dict KeyError（双优化器残留键）→ 验证器下标笔误。
- 正式 e2e 第 1 轮（1200/600/300，T4 环境 means 开放）：
  face L1 0.0328→0.0311、hair 0.0749→0.0551、skinNeck 0.1938→0.1716 改善，
  但 room hole 0.1474→0.3101、cloth L1 恶化——诊断为跨物体补偿
  （cloth 点漂移覆盖颈部误差的交叉特征）+ 第 4 轮分裂零恢复。
  修复即 de5b0f0（环境 means 冻结 + 恢复预算）。
- 正式 e2e 第 2 轮（终版，1200/600/300，T4 环境外观开放/means 冻结，
  作业 `ed8cd9d7…`，456-517s，峰值 1.5GB，**采纳为现行 profile**）：
  - face L1 0.0328→0.0301；hair L1 0.0749→0.0453（-40%）；skinNeck L1 0.1938→0.1668；
  - neckCloth hole 0.1994→0.1967；clothObserved hole 0.2004→0.1968（空洞转好）；
  - room hole 0.1474→0.2032（有界回退；开放环境 means 的第 1 轮为 0.3101，
    冻结修复一半以上）；
  - 900-local 校准轮（`614f11e5…`）可把房间 hole 收到 0.1637，但人物收益
    全部回吐（hair 回到 0.0570、skinNeck 恶化到 0.2035），未采纳；
  - 结构变化：脸部表面点 8034→11518（body-skin 支持+分裂）、环境 73763→75299
    （3 轮分裂 +1536，第 4 轮因恢复预算守卫不再触发）、总点 93969-109478。
- 契约级联调（鸿蒙客户端同款路径）：preview PNG / preview3d PLY / scene3d
  文件名与字节 / gaussian 分块 sha256 / view 白名单+schema——全部通过。
- 测试：WSL 297 用例/13 环境错（基线 295/13，+2 新增）；Windows 139/34 不变。

## 7. 测试与基线

- Windows：139 用例/34 环境错（与重构前基线一致，缺 torch/cv2/scipy 属环境）。
- WSL 全量：296 用例/13 环境错（+1 jointSteps 契约、+1 双优化器分裂回归；
  13 错为 WSL venv 缺 fastapi/httpx/PIL 的 app 层用例，与基线一致）。
- 新增守护：`test_runtime.test_joint_budget_and_raised_stage_budgets`、
  `test_surface_stage.DualClockSplitTest`、`test_live_fullframe` joint 透传断言。

## 8. 残留边界

- 完全无人脸检测的帧（无标签）仍未进入观测（需 face.py/components_v2 两层手术，
  本样本 0 PnP 拒帧、引导拍摄下检测缺失罕见）；scene 分层机制已就位，属纯扩展。
- 修剪阈值 0.01 实测不触发（保守正确）；环境分裂固定预算 384/轮未做误差自适应。
- 环境空洞的进一步压缩依赖 DA3 预算与窗口恢复（本路线不动其契约）。
