# SELF 外观优化：重启前续做记录（2026-09-27）

本记录用于 Windows 重启后接续当前工作。当前工程、应用、签名、旧作品、USB/HDC 协议、PlayCanvas 查看链路、已有编辑数据均保留；本轮没有向平板回传候选模型。工作区原本已有大量未提交修改，不得用清理或重置命令覆盖。

## 用户当前目标

在既有 FLAME Open + gsplat 1.5.3 局部外观训练路线内，完成普通 FLAME 2023 与 Open 的同协议 900 步 A/B；定位和修复头发壳感、眼镜漂浮；核对训练颜色到 PLY/PlayCanvas 的显示；增加局部指标。普通版仅作为离线研究对照，不能直接切换产品默认主干。未通过候选不发布、不回传平板。

## 已完成与证据

- 原 Open 900 步训练（本轮之前完成）：14 train / 8 held-out，固定 ROI RGB L1 0.06438 → 0.04125，11715 点；这只证明局部外观优化，画面仍有头发壳感、眼镜问题、黑底截断。路径：`backend/.sources/quality-geometry-20260926-temp/flame_open_e2_20260927/private-optimized-subset-900-footprint-1.00`。
- 模型：Open `.sources/third_party/flame2023_open/flame2023_Open.pkl`，SHA-256 `e75a0990728ba038c7da2a420ae4396f7ddd7781366c13026066c5b24f127623`；普通版 `.sources/third_party/flame2023_standard/flame2023.pkl`，SHA-256 `8fb1af0db1abb51053ead8fd1f2624a63d01c9602f4a4fb4ea23bd2c82017fa0`。原视频 `backend/.sources/quality-geometry-20260926-temp/capture.mp4`，SHA-256 `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。
- 训练帧 `(5,12,25,40,50,60,70,80,90,100,110,120,136,150)`；开发留出帧 `(15,35,55,75,95,115,130,145)`。原图竖直 1080×1920，估计 K：fx=fy=1181.055，cx=540，cy=960；裁剪时相应平移主点。
- `backend/probe_flame_observations.py --variant standard` 已输出普通版观测：22 个 faceObservation、104 个 worldObservation、14 个两者皆有；没有凭空补世界头姿。`backend/probe_flame_hair_hull.py --variant standard --skip-render-comparisons` 已生成 2950 个粗壳点；普通版可见头发 IoU 0.4295、precision proxy 0.4667；Open 2946 点、0.4359、0.4721。这不是训练 A/B。
- 以相同构建方法检查候选点：Open 皮肤7939/细节859/头发2917，合计11715；普通版7818/890/2928，合计11636。
- `backend/audit_appearance_parameters.py` 对 Open 900 步参数审计：头发 offset 均值0.771 mm、p90 1.427 mm，alpha 均值0.55→0.331，scale 均值比0.928；表明优化更多依赖颜色/透明度，粗壳几何没有得到充分修正。皮肤 offset 均值0.165 mm，细节0.278 mm。
- `backend/probe_local_component_tracks.py` 从训练原片做局部跟踪/三角化：Open 头发61 个可接受种子，距离 FLAME 面中位18.6 mm、p90 42.85 mm；种子到粗壳最近距离中位4.92 mm、p90 17.73 mm；眼镜仅6 个合格种子。说明粗壳不足、目前种子也不足以直接替换真实体积。
- `backend/export_flame_appearance_research.py` 已把原 Open900 的自定义后激活颜色与方向项拟合为标准 3DGS 一阶 SH，导出静态参考帧研究 PLY（不是动态/完整场景）：`backend/.sources/quality-geometry-20260926-temp/flame_open_e2_20260927/private-optimized-subset-900-footprint-1.00/private-reference-0035-ply-contract/portrait.ply`，SHA-256 `2e56b4404b4d53965185958ec82380e84e77994282cbc5a624151afba82bfa7a`，11715 点，2,766,216 字节。14 个训练视角预测值的每点平均转换误差0.0006698，p95 0.00255，最大0.0197；不是精确恒等转换。
- `scripts/probe-personal-playcanvas.mjs` 用现有 `entry/src/main/resources/rawfile/gs-viewer.js` / PlayCanvas 2.22.4 在 Windows Chrome/SwiftShader 实际绘制上述 PLY，WebGL2 true、11715 点，静态参考帧正常载入。`backend/audit_playcanvas_head.py` 同视角比较：PlayCanvas vs gsplat 固定 ROI L1=0.0061074，整个 crop=0.0068981；PlayCanvas vs 原片=0.0389217。白色边缘晕在 gsplat/PlayCanvas 都有，属于资产/几何缺陷。仅验证一静态相机，未验证连续转动或鸿蒙绘制。
- `backend/compare_flame_appearance_ab.py` 会拒绝缺失或条件不一致的 A/B；目前普通版 900 步尚未运行。`backend/test_flame_appearance_contract.py` 加上原模型/观测测试合计9项已通过；最新 `probe_flame_hair_hull.py` 参数化修改后还需重跑语法和测试。

## 代码变动范围

本轮新增/修改（原本为未跟踪文件，注意保留）：`backend/probe_flame_hair_hull.py`、`backend/train_flame_local_appearance.py`、`backend/probe_flame_observations.py` 的标准版数据输出、`backend/export_flame_appearance_research.py`、`backend/audit_playcanvas_head.py`、`backend/audit_appearance_parameters.py`、`backend/probe_local_component_tracks.py`、`backend/compare_flame_appearance_ab.py`、`backend/test_flame_appearance_contract.py`、`scripts/probe-personal-playcanvas.mjs`。没有修改鸿蒙应用来展示失败模型。

## 当前阻塞和重启后第一步

Windows 设备管理器显示 RTX 5070 Laptop GPU `OK`，但 Windows 完整 `nvidia-smi` 报权限不足；WSL `nvidia-smi -L` 报 `GPU access blocked by operating system`，PyTorch `torch.cuda.is_available()==False`、CUDA 初始化失败。仅重启 Ubuntu-22.04 后未恢复；随后 WSL 调用还返回 `E_ACCESSDENIED`，可能正值 Windows 准备重启。用户明确要求保存记录并停止，等待其重启。

用户回来报告重启完成后，先只读核对 Windows/WSL GPU、原重建 worker 和工程状态。恢复 GPU 后以同一 trainer 当前源码、同一 run-id `ab-20260927` 分别训练 Open/standard 各至少900步，同 train/held、K、crop、seed、footprint、损失、参数开放顺序，然后用 `backend/compare_flame_appearance_ab.py` 对照。需先读各脚本 `--help` 获取完整命令，不能直接复用旧 Open900 数字作为匹配 A/B。完成后补同视角三联图、局部放大、每帧指标、显存/耗时和视觉审查；质量不过则不回传。

重启后也应继续 CPU 头发边界对照：`probe_flame_hair_hull.py` 最近加了 `--min-support`、`--max-contradictions`、`--no-fill-holes` 可隔离输出；尚未运行新实验，不得说通过。头发/眼镜尚未完成四部件真实联合训练，后续记录应明确该缺口。

## 许可与边界

FLAME 2023 普通版只作研究对照，许可问题未解决前不进入长期交付；Open 继续为默认基线，直到同条件实测与许可结论共同支持切换。当前 8 帧已被用于开发选择，只称开发留出，不称独立最终审计。任何黑底头部样件都不是完整人像场景。
