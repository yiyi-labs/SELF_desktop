# 本轮复现
W/backend，Ubuntu-22.04，/opt/self-reconstruction/venv/bin/python -B。
所有输出必须为新的目录；以下run已存在，禁止覆盖。

```text
run_ray_surface_repair.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --depth .sources/dense-motion-surface-20260930-h/depth --out .sources/observed-ray-surface-20261001-b --steps 300
audit_ray_surface_repair.py --root .sources/observed-ray-surface-20261001-b --out .sources/observed-ray-surface-20261001-b/quality
audit_ray_component_rollback.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --source .sources/observed-ray-surface-20261001-b/surface --out .sources/observed-ray-surface-20261001-b/component-rollback
audit_complete_preservation_display.py --folder baseline=.sources/continuity-physical-surfaces-20261001-b/body-transition-sh --folder control=.sources/observed-ray-surface-20261001-b/control --folder surface=.sources/observed-ray-surface-20261001-b/surface --out .sources/observed-ray-surface-20261001-b/display
```
W根目录的Windows node：
```text
node scripts/probe-dense-surface-display.mjs <W>/backend/.sources/observed-ray-surface-20261001-b/display
```
随后W/backend：
```text
audit_motion_display_comparison.py --prepared /mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e --browser-report .sources/observed-ray-surface-20261001-b/display/playcanvas-01/report.json --identity-map .sources/observed-ray-surface-20261001-b/display/identity-map.json --out .sources/observed-ray-surface-20261001-b/display-comparison
audit_complete_preservation_state.py --folder .sources/observed-ray-surface-20261001-b/control --folder .sources/observed-ray-surface-20261001-b/surface --out .sources/observed-ray-surface-20261001-b/state-restore.json
audit_dense_surface_asset.py --folder .sources/observed-ray-surface-20261001-b/surface --out .sources/observed-ray-surface-20261001-b/orbit
python -B -m unittest test_ray_surface test_asset_order test_observation_protection test_reconstruction_continuity_surface test_reconstruction_motion_surface
```
实际执行源码保存在run的algorithm-source；当前源码增加了数值零增量精确化，详见报告。缓存DA3-BASE没有重新推理或下载。本轮未复制外部方法代码、未安装新依赖。
