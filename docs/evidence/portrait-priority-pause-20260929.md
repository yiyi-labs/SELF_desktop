# 2026-09-29 用户主动暂停，准备重启恢复独显

用户最新要求：停止，重启后再继续 GPU 训练。停止后不得自动训练或自行改驱动/显卡模式。

## 已完成与现场
- W: C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay
- P: D:/STUDY/College/mine/olay（本轮未修改）
- 原 HEAD: 13b1b0f58c87aa08c23b56999b4aa962fd542862。
- d=2 小修已单独提交 cef6c043ed7a4ad397de41c995b7787ec3db0ce5。
- 提交仅包括 backend/reconstruction_scene.py 与 backend/test_surface_centroid_integration.py。
- test_surface_centroid_integration + test_surface_candidate_budget 共 10 测试通过，3.611 秒。
- 固定回归复用 357 新增、50 拒绝、4 已有与 1704 旧判断，未重跑全局准备。
- 新增但尚未测试/提交：backend/reconstruction_research_state.py。包含完整状态保存/恢复、采样器/RNG、有界局部头姿和研究输入合同；不代表训练接线完成。
- 此文件刚写入，尚无 import/单元测试，必须验证后才可供真实训练使用。
- 未开始本轮 GPU 训练，未调用 Adam 优化、density、部署、HDC 或发布；旧作品和历史资产未动。
- W 原有未追踪内容：docs/evidence/reconstruction-stage2a-20260928/replay-report.md 与 reconstruction-v3-targeted-audit-20260928/。不得顺带提交。

## 恢复后优先次序
1. 用户通知重启完成后，只读核对 Windows RTX 5070 Present 与 WSL torch.cuda，不切模式/改驱动/重启。
2. 先核对 HEAD 和 dirty，读取新用户规范 SELF_Portrait_Priority_Full_Observed_Scene_Codex_20260929.md。
3. 完成并测试尚未完成的 face-local、静态 density、完整 checkpoint 接线；不能把现有冻结脸的旧 v3 runner 直接当新算法训练。
4. 预先固定有限步数/时间/显存预算与观察用途，再在新 run-id 实际训练。旧900没有 Adam，仅能明确 warm-start。
5. 真实 head-local 训练独立于世界 C 不全；完整 joint 需真实输入/变换合同，发布仍 E1—E5。不得 require_joint({}) 占位，也不得总为 true。
6. 不部署、不回传、不替换旧作品。报告明确区分实际优化、CPU 合同通过和未运行。

## 可复用代码及关键注意
- reconstruction_portrait_model.LocalPortraitModel: 完整 11715 点旧 Open head-local-sh1、8798 表面+2917 旧头发；shared residual/embedding/offset/SH；CandidateTransaction 真父点替换与恢复。旧发壳保留仅用于可恢复比较，不代表头发修好。
- reconstruction_portrait_pipeline.initialize_scene/make_frame/draw: native ROI 与 K 同步；完整5部件同一次 rasterization，准确 SH/协方差变换；旧 train_stage 缺 pose/density/完整环境 optimizer/RNG checkpoint。
- reconstruction_components_v3.load_v3_prepared: 固定准备读取，旧 source/appearance hash 校验。世界相机缺失不伪造。
- run_reconstruction_v3.py 当前仍 face freeze、360附件/360room、无 density、joint 占位；尚未修改。
- 原 room loss 已使用完整可见 room RGB，不得声称以前仅特征点附近监督。
- 已安装 gsplat 1.5.3 DefaultStrategy/ops 同步参数、Adam、每个 state tensor；新增 metadata 必须随拓扑变化。
- 安装源码 step_post_backward reset 条件实际是 `step % self.reset_every == 0 & step > 0`，需核对 Python 优先级与行为后决定研究适配，不能盲照默认。
- 学习策略需预留最后拓扑/reset后的恢复步骤；不是360改501。
- 无新 face/room/joint 画质证据，不能写改善或完整发布通过。

## 固定输入与执行环境
- prepared: D:/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e
- local_geometry.npz: 99个本地观测，91 train/8 development；64 world，其中59 train/5 development。
- appearance: quality-geometry-20260926-temp/flame_open_e2_20260927/private-optimized-subset-900-footprint-1.00-sh1-head-local-20260927/private-optimized-parameters.npz
- source SHA256: 7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf
- appearance SHA256: 308da67a299dc98855fa4d3403197130811ec87d96dcb7ad967eee92950d9e46
- WSL Ubuntu-22.04; /opt/self-reconstruction/venv/bin/python; torch 2.8.0+cu128; gsplat 1.5.3; pycolmap4.2.0。
- CUDA_HOME=/usr/local/cuda-12.8; TORCH_CUDA_ARCH_LIST=12.0; MAX_JOBS=2; PYTHONDONTWRITEBYTECODE=1。
- Windows 独显末次状态 Present=false，WSL CUDA不可用。用户已决定自行重启。
- W不在当前默认可写根内，修改/测试通过获准的 require_escalated；不要改P绕过。

本记录仅保存续接状态；用户暂停后未继续开发或测试。
