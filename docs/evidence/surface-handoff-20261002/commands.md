# 实际执行命令与冻结输入

在W/backend、Ubuntu-22.04下用/opt/self-reconstruction/venv/bin/python -B执行。以下是已执行命令，不是自动运行脚本；旧run不可覆盖。

## 回归

`python -B -m unittest -v test_surface_handoff test_ray_surface test_reconstruction_continuity_surface`

23项全部通过，含实际GPU前向/梯度测试。最终4.918秒。ARCH_LIST和requires_grad转标量警告为既有诊断输出，不是CUDA失败。

## 同起点训练

```
python -B run_surface_handoff_repair.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --depth .sources/dense-motion-surface-20260930-h/depth --out .sources/surface-handoff-20261002-b --steps 320 --budget 14000
python -B audit_surface_handoff_contribution.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --out .sources/surface-handoff-contribution-20261002-b
python -B run_surface_handoff_repair.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --depth .sources/dense-motion-surface-20260930-h/depth --out .sources/surface-handoff-20261002-c --steps 320 --budget 35000 --reuse .sources/surface-handoff-20261002-b --attribution .sources/surface-handoff-contribution-20261002-b
python -B run_surface_handoff_repair.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --depth .sources/dense-motion-surface-20260930-h/depth --out .sources/surface-handoff-20261002-d --steps 320 --budget 175000 --max-parents 3 --reuse .sources/surface-handoff-20261002-b --attribution .sources/surface-handoff-contribution-20261002-b --surface-pool .sources/observed-coverage-haze-20261001-b/selection/uniform/supported-pool.npz
```

各自algorithm-source是当次真实代码快照，不能用提交后的默认值反推旧运行。D复用已存完整表面池，按当前训练role重新核对，不重新枚举或全局准备。

## 真实交接和逐项事务

```
python -B audit_surface_handoff_motion.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --depth .sources/dense-motion-surface-20260930-h/depth --out .sources/surface-handoff-motion-20261002-a
python -B audit_surface_handoff_transactions.py --complete .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --source .sources/surface-handoff-20261002-c --attribution .sources/surface-handoff-contribution-20261002-b --out .sources/surface-handoff-transactions-20261002-a
python -B audit_surface_handoff_results.py --folder .sources/surface-handoff-20261002-b --folder .sources/surface-handoff-20261002-c --body .sources/surface-handoff-motion-20261002-a --out .sources/surface-handoff-summary-20261002-b
python -B audit_surface_handoff_quality.py --root .sources/surface-handoff-20261002-c --out .sources/surface-handoff-20261002-c/quality
python -B audit_continuity_asset.py --folder .sources/surface-handoff-20261002-c/surface-replacement --out .sources/surface-handoff-20261002-c/orbit
```

桌面Windows/W根：`node scripts/probe-dense-surface-display.mjs backend/.sources/surface-handoff-20261002-c/display`。这是实际PlayCanvas2.22.4 Chrome SwiftShader，不是设备验收。

## 未覆盖的证据

.source身份探针a、首次贡献探针a、恢复汇总a与b均保留；没有覆盖它们来修饰报告。私人图像、PLY、checkpoint未进入Git，且没有独立云/外盘资产备份。不要自动清理任何这些文件。
## 最后一组的实际检查

```
python -B audit_surface_handoff_results.py --folder .sources/surface-handoff-20261002-d --body .sources/surface-handoff-motion-20261002-a --out .sources/surface-handoff-summary-20261002-d
python -B audit_continuity_asset.py --folder .sources/surface-handoff-20261002-d/surface-replacement --out .sources/surface-handoff-20261002-d/orbit
python -B audit_surface_handoff_quality.py --root .sources/surface-handoff-20261002-d --out .sources/surface-handoff-20261002-d/quality
```

Windows/W根已执行：`node scripts/probe-dense-surface-display.mjs backend/.sources/surface-handoff-20261002-d/display`。

quality脚本只是读取原片、实际全幅输出和桌面RGBA，不调用optimizer、不改checkpoint。所有新候选仍published=false。六分支全部恢复模型、Adam、策略、采样、RNG和bindings。

提交的tests.log仅去除行尾空白；原始输出保存在.sources/surface-handoff-summary-20261002-d/tests-raw.log，SHA记录于implementation-lock.json。条目、警告、耗时和结果全部保留。
