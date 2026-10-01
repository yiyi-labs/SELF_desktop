# 本轮实际命令与边界

W/backend，Ubuntu-22.04 Python `/opt/self-reconstruction/venv/bin/python -B`。所有out必须是未存在的独立目录。以下已经执行的目录不能覆盖。P只作为只读prepared来源。

变量含义：

- PREP：`/mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e`
- COMPLETE：`.sources/continuity-physical-surfaces-20261001-b/body-transition-sh`
- TRACKS：`.sources/continuous-geometry-repair-20261001-a/observed-tracks/tracks.json`
- ROOT：`.sources/cross-window-surface-repair-20261001-a`
- MVS0/1：ROOT的`head-window-0-score`、`head-window-1-score`
- MVS2：`.sources/continuous-geometry-repair-20261001-a/head-restored-native-mvs`

```text
prepare_measured_hair_mvs.py --prepared PREP --tracks TRACKS --out ROOT/head-window-0 --native-object-roi --include-face-anchors --complete COMPLETE --window-index 0
prepare_measured_hair_mvs.py --prepared PREP --tracks TRACKS --out ROOT/head-window-1 --native-object-roi --include-face-anchors --complete COMPLETE --window-index 1
run_cross_window_surface_repair.py --complete COMPLETE --mvs MVS0 MVS1 MVS2 --out ROOT/hair-all-window --steps 240
run_quadratic_body_motion.py --prepared PREP --tracks TRACKS --out ROOT/body-shared-motion
run_dense_face_surface_repair.py --complete COMPLETE --mvs MVS0 MVS1 MVS2 --out ROOT/face-shared-depth-b --steps 240
run_dense_face_surface_repair.py --complete COMPLETE --mvs MVS0 MVS1 MVS2 --out ROOT/face-shared-normal --geometry-mode normal --steps 240
run_context_appearance_repair.py --complete COMPLETE --out ROOT/context-appearance-b --steps 240
run_protected_face_appearance.py --complete COMPLETE --out ROOT/face-native-coverage --steps 240
run_observation_protected_hair.py --complete COMPLETE --source ROOT/hair-all-window/actual-surface-candidate --out ROOT/hair-observed-empty
```

普通共享几何候选均因geometry门槛被拒绝，`--steps 240`并没有实际启动其外观训练。face-native-coverage实际执行快照是点序修复前版本；当前入口新增原位更新，不声称原run自动变成新源码运行。

OpenMVS由Windows `scripts/Invoke-FiniteMeasuredMVS.ps1 -Folder <MVS-folder> -ToolDirectory <existing-tool-directory> -Seconds 360 -DenseConfig ROOT/sparse-neighbor-score.cfg -Verbosity 3`运行；绝对实际参数、工具hash和执行结果在每窗`execution.json`。0/1默认失败输出保留；研究score目录只复制对应已准备的原输入到独立目录，没有重写相机或像素。第三窗复用，没有重新计算。

```text
audit_fixed_order_export.py --folder ROOT/face-native-coverage --complete COMPLETE --out ROOT/face-native-fixed-order
audit_order_render.py --source ROOT/face-native-coverage --ordered ROOT/face-native-fixed-order --out ROOT/order-render-check
audit_dense_surface_asset.py --folder ROOT/face-native-fixed-order --out ROOT/face-fixed-orbit
audit_cross_window_evidence.py --root ROOT --complete COMPLETE --out ROOT/evidence-final
audit_cross_window_evidence.py --root ROOT --complete COMPLETE --out ROOT/display-recovery-input --display
audit_complete_preservation_display.py --folder hair-protected=ROOT/hair-observed-empty --out ROOT/display-hair-protection-input
```

W根的Windows node使用现有锁定脚本，不改查看器：

```text
node scripts/probe-dense-surface-display.mjs <absolute ROOT/display-recovery-input>
node scripts/probe-dense-surface-display.mjs <absolute ROOT/display-hair-protection-input>
```

W/backend各显式浏览器报告随后调用现有`audit_motion_display_comparison.py --prepared PREP --browser-report <input/playcanvas-01/report.json> --identity-map <input/identity-map.json> --out <independent comparison directory>`。当前三个比较目录为`display-recovery-comparison`、`display-hair-protection-comparison`以及最初hair输入。没有自动选择历史browser报告。

初始未通过的`face-shared-depth`、`context-appearance`、MVS0/1默认执行保留。完整状态回归对五分支显式调用`audit_complete_preservation_state.py`。实际55项单元回归命令见tests.log。数据与执行快照优先于当前源码默认值。

本轮未部署、未回传、未创建生产job、未改算法默认入口。没有新T3/T4，没有HarmonyOS测试，没有完整视频到可发布作品的2—3分钟验收。