# 唯一生产入口接入核对（只读）

本记录仅核对实际代码、配置、服务与 USB 状态。没有修改 profile、启动 worker、运行 GPU、改动任务或回传资产。后续命令是恢复服务时的操作清单，不是本轮已执行记录。

## 当前现场

- Git HEAD：`749fb6e94ca2c1d763d4674b30604e84d65cf419`，工作区仍有本轮及既有未提交文件；不得按本记录清空或混提。
- 源码闭包本次读取为 44 个文件，SHA `0264731d5509e0fb038845a9925fccf0595db7b8f43febe22ffbd3101643fb68`。这是读取时值，最终修改后必须重新计算。
- `backend/.data/reconstruction/engine-profile.json` 仍声明旧实现 `f12f8677f485404aa313904e8040241066a5442f47ab0e4ad98fea1d997e5798`；实际调用 `engine_profile` 返回 `test_source_hash_changed:dependency_closure`。
- 旧 profile 的真实缺省为 local900、room300、hair0、dense=false、shared=false、observedFace=false，并保留旧 preparedCache。因此现在不能称最新能力已全量接入。
- worker_status 为 ready=false、`integration_verification_in_progress`，与当前停止状态一致。
- Windows 127.0.0.1:8787 正由 PID36384 监听。HDC 设备 `6DP0226117002287` 在线，`tcp:8787 tcp:8787 [Reverse]` 已存在。
- 任务状态只读统计：gaussian_ready20、cancelled8、failed5；没有 queued/running。任务和资产均未修改。

## 通过当前合同的配置字段

以下字段经 `training_profile_options` 纯 CPU 验证通过。只有对应画质对照可保留后才能实际写入；不启用被否决实验。

```json
{
  "engine": "portrait-first-soft-surface-test",
  "executionAdapter": "native-fullframe",
  "algorithmVersion": "portrait-native-fullframe-20261002-research",
  "userTestingAuthorized": true,
  "releaseApproved": false,
  "localSteps": 900,
  "roomSteps": 400,
  "hairCompositeSteps": 180,
  "denseSurfaces": true,
  "sharedRoomSurface": true,
  "observedFaceDomain": true,
  "surfaceRefine": false,
  "implementationSha256": "FINAL_SOURCE_IDENTITY_REQUIRED"
}
```

删除 `preparedCache`，不要改成另一个研究准备目录。代码 `verified_preparation` 在字段不存在时返回 None，随后执行当前视频的抽帧、识别、背景相机、局部本人拟合及短窗定位，再进入同一个训练入口。已实际验证此控制分支；不是把旧训练作品当新视频输出。

当前 native adapter 固定 joint_steps=0；不添加一个不会被读取的 profile jointSteps 字段制造已启用的错觉。AA 保持当前 classic。`observedEmptySpace`、严格皮肤 context 实验、额外颈部几何等尚未通过项，不因“全量”就启用。

### 最新辅助房间预算尚有接线差距

当前自动调用链是：

`reconstruct_test → reconstruction_live_fullframe → pipeline.run → augment_prepared → apply_shared_room_correction(complete_observed=True) → complete_observed_room`

最后一个函数目前仍默认 `extra_budget=8000`。手工 30000 预算对照不会因为 dense/shared 开关自动生效。若该对照通过，需要在唯一自动 stage 中统一合格的预算策略，或增加严格的 runtime/CLI 预算字段，并同步：

1. `training_profile_options` 校验与 executionProfileSha256；
2. CLI 传入、pipeline 配置与 stage 回执；
3. 主 surface stage 到 completion 的真实参数；
4. 阶段/资产来源记录及 CPU 合同回归。

不能仅把研究 manifest 设为默认输入。若不接此项，最终报告必须明确“仍为 8000 自动预算”，不能声称包含最新已接受预算。

## 源码身份更新方法

`reconstruction_code_identity.source_identity` 从 worker/runtime/live_fullframe/live_prepare 出发，静态遍历本地 import（包括函数内 import），并加入 identity 模块本身。当前闭包确实包含 dense、shared_room、room_completion、hair_motion、face_domain、hair_composite 与 surface_recovery。

应在最后一个源码修改和显式 Git 提交完成后重新调用，而不是沿用本报告中的哈希：

```powershell
wsl -d Ubuntu-22.04 --cd /mnt/d/STUDY/College/mine/olay/backend -- /opt/self-reconstruction/venv/bin/python -B -c "import json; from reconstruction_code_identity import source_identity; print(json.dumps(source_identity(), indent=2))"
```

有 `implementationSha256` 时，runtime 验证完整闭包并忽略四文件旧 `entrySourceHashes` 分支。建议移除旧四文件字段，或准确同步它，避免人为误读。若只走旧分支，精确必需集合是：

- reconstruction_live_fullframe.py
- reconstruction_portrait_pipeline.py
- reconstruction_portrait_model.py
- appearance_direction_contract.py

仅四文件不足以保证完整新链路，因此当前应使用完整 implementationSha256。`gitCommit` 是审计标识，dirty 文件的实际身份由字节哈希决定。

DA3 公共工具不在该 Python 本地 import 闭包内，但 worker dense preflight 会另行验证固定 P 目录的源码锁、代码提交、模型提交与权重哈希；不再回退到旧 worktree。

## HTTP 已运行时，必须单独恢复 worker

`Start-ReconstructionDesktop.ps1` 的 watcher 只在 8787 端口不通时启动 Server。当前 HTTP 已运行、worker 单独停止，重复点击桌面启动器会等待超时，不会因此重建 worker。

也不应直接再启动一个 `Start-ReconstructionServer.ps1`：其新 HTTP 会争抢8787，失败后 finally 可能停止它刚创建的 worker。

当源码/profile已冻结，GPU研究结束、确认无现存 worker 后，可只启动 worker；以下是与既有 Server 脚本相同环境的命令，保留新日志名而不覆盖历史日志：

```powershell
$logRoot = 'D:/STUDY/College/mine/olay/backend/.data/reconstruction'
$runStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$workerProcess = Start-Process -FilePath 'wsl.exe' -ArgumentList @(
  '-d', 'Ubuntu-22.04', '--cd', '/mnt/d/STUDY/College/mine/olay/backend', '--', 'env',
  'SELF_RECON_JOBS_DIR=/mnt/d/STUDY/College/mine/olay/backend/.data/reconstruction',
  'CUDA_HOME=/usr/local/cuda-12.8', 'TORCH_CUDA_ARCH_LIST=12.0', 'MAX_JOBS=2',
  'PATH=/opt/self-reconstruction/venv/bin:/usr/local/cuda-12.8/bin:/usr/sbin:/usr/bin:/sbin:/bin',
  '/opt/self-reconstruction/venv/bin/python', '-B',
  '/mnt/d/STUDY/College/mine/olay/backend/reconstruction_worker.py'
) -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput (Join-Path $logRoot "worker-$runStamp.stdout.log") `
  -RedirectStandardError (Join-Path $logRoot "worker-$runStamp.stderr.log")
```

该命令本轮没有执行。worker 自身的全局锁阻止第二个工作器进入预检。不要手工改 worker_status.ready=true；必须由真实 CUDA smoke、模型/工具检查与身份一致后生成新心跳。不要把 `--once` 或 `--job` 当作只读健康检查，它们可能执行排队任务。

应核对新心跳时间、ready、sourceIdentityVerified、denseToolVerified，且 loaded/current/profileImplementationSha256 三者一致；executionProfileSha256 必须对应最终实际开关和预算。代码改变后旧进程不能由改 profile 重新“认领”为新版，必须重启加载。

## 结果保留与实际验收边界

- 不更改20个已完成、8个已取消、5个失败任务的状态，不删除旧资产，不复用 job ID 或 run-id。启动工作器正常只处理 queued/cancel_requested。
- 新结果应保存实际 local/T3/hair步数、初始化/终态部件数量、shared条件表面是否真正应用、observedFaceDomain的原始/新颜色哈希与 masks 摘要。
- runtime 现已保留检查点、Adam/RNG、局部拟合、绑定、dense组件及主/辅助几何收据、hair motion、重新取色初值。原片清理后这些副本依赖 recovery-manifest 的哈希映射；没有原像素不能称可精确继续图像监督训练。
- 原片和临时帧仍按成功任务原清理合同删除；不是本次只读检查在清理。调试日志若要长期保留，须在清理前另存有明确用途的非隐私摘要。
- HDC在线与Reverse转发只证明线缆通道存在；电脑 PlayCanvas/GPU对照只证明电脑侧。真正鸿蒙验收仍需用户新提交的视频任务完成，核对 source/job/implementation/asset SHA、下载完成、应用保存、实际 PLY 绘制及用户看到的新作品。不能用旧作品、合成资产、单纯 JSON 成功或 CPU回载替代。
- 此轮仅后端算法改变通常无需重装 HAP；但是否当前设备确有兼容版本应以实际已安装版本/查看器合同记录为准，本检查没有替用户点按或安装。

当前仍未完成“新视频经HDC实际到新版worker并在鸿蒙显示”的最终闭环；不能提前声明已经全量验证。

## 后续实际激活记录（取代上文待办状态，保留历史读取口径）

运行代码提交：`749fb6e94ca2c1d763d4674b30604e84d65cf419`、`f865b82bb24ee94f10b19b1a9f10123c81e3fe6d`、`9d2b8e000a1a5971db2655c8fe7f00f08b392ceb`；证据提交 `b47f545a7bef13373159bf53e35d9dcf6a1bd447`。

实际45文件运行闭包：`35e300fd2d720862c3a597ebdaf3fb7bb2bcdc63c848131321f0154959ba92cf`。

已实际保存旧profile到独立 `backend/.sources/live-complete-repair-20261003-service-activation/previous-profile.json`，并写入唯一现行profile：local900、room400、hair180、dense/sharedRoom/observedFace=true、surfaceRefine=false。自动room补充默认预算现在为30000，实际统一入口新增28459个合法样点；不是手工manifest覆盖。已经删除preparedCache及旧四文件entrySourceHashes，改用完整依赖闭包。

skinCompositingSteps=0：180步实际研究出现局部/镜框退化并已完整回退，所以不默认启用。observedEmptySpace和face capacity同样不启用。不能把失败分支也启用叫“全量”。兼容协议的algorithmVersion字符串保留，实际实现由Git和完整字节哈希识别，不新增用户需要选择的服务版本。

用户解锁重连后，HDC实际出现设备 `6DP0226117002287 tcp:8787 tcp:8787 [Reverse]`；此前连接建立失败的记录不当作成功。新工作器于2026-10-03 11:11启动，独立日志 `worker-20261003-111117.stdout.log/stderr.log`，原HTTP保持运行。启动前33历史任务为20已完成、8取消、5失败，无queued/running；未改写这些任务和旧作品。正式ready与哈希一致结果须以下方实际心跳记录为准。

实际心跳 updatedAt=1790997251 已确认ready=true、sourceIdentityVerified=true、denseToolVerified=true；loaded/current/profileImplementationSha256三者均为上述 `35e300fd…`。执行配置哈希 `53bc524de092cde8a591c3cdb125fc3aa9de744c9852a9b3df152936b090059d`。Torch2.8.0+cu128、CUDA12.8、gsplat1.5.3，显存8123MiB；启动曾实际编译CUDA扩展，不能把这个CPU/JIT时段误报成新模型训练或GPU故障。没有手工设置ready。

最新profile、完整源码身份、工作器启动及随后通过心跳保存在上述独立service-activation目录。所有45个运行依赖均已被Git跟踪，生产失败研究开关保持关闭。本轮无需重装HAP；未向平板发送研究PLY或覆盖旧作品。新视频的实际建模/接收/显示仍未由本轮替用户操作，不能把就绪或USB成功说成该端到端质量已通过。

尝试从平板shell以curl读取健康接口时，设备报告没有curl；该请求未执行，不能记为平板HTTP实测通过。已通过的是HDC设备连接、实际Reverse映射和电脑工作器真实预检；用户端应用新任务仍待实测。
