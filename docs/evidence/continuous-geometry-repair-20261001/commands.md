# 本轮执行记录

范围：现有完整研究场景，独立颈部连续形变、原片真实短窗测量、共享面部/头发纠正、真实多视图背景表面替换。不改应用/生产配置，不部署或回传。

起点 W HEAD：b7f044a5771c47a4db7c3171a4e3051c2475abee。
P HEAD：3dad0cd5651824cc06d9e88d61aabdd2642c0b30。
完整研究起点不是通过作品：50095 点，frame_0010.png，PLY a343ccf05292ce1e174c7fd63795122347a8d03bd0202a19395a9a414b691f41。

全部命令在 W/backend、Ubuntu-22.04、/opt/self-reconstruction/venv/bin/python -B 下运行。

```text
-m unittest test_reconstruction_surface_continuity test_reconstruction_continuity_surface test_reconstruction_room_surface_repair test_measured_head_surface_repair

run_continuous_surface_repair.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --out .sources/continuous-geometry-repair-20261001-a/neck --steps 200

run_continuous_observed_tracks.py --prepared /mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e --out .sources/continuous-geometry-repair-20261001-a/observed-tracks

run_observed_body_motion_repair.py --prepared /mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e --tracks .sources/continuous-geometry-repair-20261001-a/observed-tracks/tracks.json --out .sources/continuous-geometry-repair-20261001-a/body-motion

run_measured_head_surface_repair.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --tracks .sources/continuous-geometry-repair-20261001-a/observed-tracks/tracks.json --out .sources/continuous-geometry-repair-20261001-a/face-measured-recorded --component face --steps 180

run_complete_room_surface_repair.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --mvs .sources/surface-evidence-face-clothing-20260929-a/B-mvs --out .sources/continuous-geometry-repair-20261001-a/room-projected-surface --steps 240 --proposal-domain projected-surface
```

保留的失败执行：room（训练身份门禁过严，未训练）、room-role-corrected（三维旧核域不足，未训练）、face-measured（几何求解完成，记录数组序列化失败，未进入图像训练）。修复后均用新的独立目录；没有覆盖旧证据。

每条可训练分支先写 config 与源码，再保存 initial/mid/candidate-final/restored，包含 Adam/绑定/采样器/RNG。当前控制、候选预算相同；旧900步仍是没有Adam的历史基线，不称精确resume。

本轮没有安装、升级或复制外部实现。复用既有锁定 OpenMVS 2.4.0 融合缓存与 gsplat 1.5.3；新的数学适配和测量入口为本工程实现。模型许可沿用 FLAME Open；没有再选择普通 FLAME 或切主干。

## 追加的实际执行（保持先前失败目录）

```text
run_measured_head_surface_repair.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --tracks .sources/continuous-geometry-repair-20261001-a/observed-tracks/tracks.json --out .sources/continuous-geometry-repair-20261001-a/hair-measured --component hair --steps 180

audit_measured_head_local.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --run .sources/continuous-geometry-repair-20261001-a/face-measured-recorded --out .sources/continuous-geometry-repair-20261001-a/face-local-evidence
audit_measured_head_local.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --run .sources/continuous-geometry-repair-20261001-a/hair-measured --out .sources/continuous-geometry-repair-20261001-a/hair-local-evidence

prepare_measured_hair_mvs.py --prepared /mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e --tracks .sources/continuous-geometry-repair-20261001-a/observed-tracks/tracks.json --out .sources/continuous-geometry-repair-20261001-a/hair-native-mvs
prepare_measured_hair_mvs.py --prepared /mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e --tracks .sources/continuous-geometry-repair-20261001-a/observed-tracks/tracks.json --out .sources/continuous-geometry-repair-20261001-a/hair-native-mvs-roi --native-object-roi
prepare_measured_hair_mvs.py --prepared /mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e --tracks .sources/continuous-geometry-repair-20261001-a/observed-tracks/tracks.json --out .sources/continuous-geometry-repair-20261001-a/head-native-mvs-roi --native-object-roi --include-face-anchors
prepare_measured_hair_mvs.py --prepared /mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e --tracks .sources/continuous-geometry-repair-20261001-a/observed-tracks/tracks.json --out .sources/continuous-geometry-repair-20261001-a/head-restored-native-mvs --native-object-roi --include-face-anchors --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh
```

以上四个MVS输入目录分别调用W/scripts/Invoke-FiniteMeasuredMVS.ps1，ToolDirectory固定为W/backend/.sources/tools/openmvs-2.4.0-cpu/bin/vc17/x64/Release；实际二进制hash、参数、退出码、耗时在各目录execution.json。前两次exit=0但无dense.ply；第四次只重三角化已有测量，不重匹配、不优化相机。

```text
build_native_head_surface.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --mvs .sources/continuous-geometry-repair-20261001-a/head-native-mvs-roi --out .sources/continuous-geometry-repair-20261001-a/head-mvs-proposal
# 上述明确相机合同失败，未训练。

run_native_head_surface_repair.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --mvs .sources/continuous-geometry-repair-20261001-a/head-restored-native-mvs --out .sources/continuous-geometry-repair-20261001-a/hair-native-surface --steps 180

run_continuous_surface_repair.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --out .sources/continuous-geometry-repair-20261001-a/neck-material-jacobian --steps 200
```

## 实际显示和固定资产绕看

W根目录node scripts/probe-dense-surface-display.mjs读取独立display-full与hair-surface-display；输入由audit_complete_preservation_display.py按显式folder列表生成：
- display-full：完整研究起点、首次neck候选、face候选、5点hair场候选、room物理表面候选。
- hair-surface-display：相同完整起点、actual-surface-candidate。

```text
audit_motion_display_comparison.py --prepared /mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e --browser-report .sources/continuous-geometry-repair-20261001-a/display-full/playcanvas-01/report.json --identity-map .sources/continuous-geometry-repair-20261001-a/display-full/identity-map.json --out .sources/continuous-geometry-repair-20261001-a/display-comparison

audit_motion_display_comparison.py --prepared /mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e --browser-report .sources/continuous-geometry-repair-20261001-a/hair-surface-display/playcanvas-01/report.json --identity-map .sources/continuous-geometry-repair-20261001-a/hair-surface-display/identity-map.json --out .sources/continuous-geometry-repair-20261001-a/hair-surface-display-comparison

audit_continuity_asset.py --folder .sources/continuous-geometry-repair-20261001-a/neck/strain-candidate --out .sources/continuous-geometry-repair-20261001-a/neck-fixed-orbit
audit_continuity_asset.py --folder .sources/continuous-geometry-repair-20261001-a/hair-native-surface/actual-surface-candidate --out .sources/continuous-geometry-repair-20261001-a/hair-surface-fixed-orbit

audit_continuous_repair_results.py --root .sources/continuous-geometry-repair-20261001-a --out .sources/continuous-geometry-repair-20261001-a/final-evidence
```

最终29项合同回归包括材料权重完整链式Jacobian、原像素ROI保留与正确投影、实际COLMAP导入半像素、坏第三观察拒绝。历史28项与新29项日志分别保留。测试通过不等于画质通过。

所有GPU分支各自先记录预算/config后创建optimizer。首轮predeclared-budget.json未被改写；新增面部180、原片表面hair180及材料导数重放200分别有自己的独立config与源码快照。没有将研究分支都计作一次服务任务。
