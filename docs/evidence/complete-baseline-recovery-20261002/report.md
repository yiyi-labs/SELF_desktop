# 完整内容基线恢复后再修缮

2026-10-02。在P恢复完整内容研究起点，没有从旧prepared重新初始化参数。本任务未修改应用、签名、旧作品、传输、AI、OLAY、故事或查看器。

## 最新白雾

最新完整研究路线仍有明显薄雾、柔化与颈部接缝。柜体、天花板和衣物内容比本轮错误的稀疏初值对照完整。空洞退化与白雾不能混为一谈。已有同资产双渲染器证据中，PlayCanvas部分人像比gsplat更清晰，但衣物仍淡化，两端仍不一致。本次未新测HarmonyOS；不能把gsplat白雾程度直接当成平板当前作品的程度。

最新共享几何研究候选fd21c779...未通过/未采用。修缮起点继续为完整内容a343ccf0...，保留最新数值能力和对照，不按文件修改时间把失败候选升级为默认。

## 基线已真实恢复

统一入口：backend/reconstruction_baseline.json。恢复实现：reconstruction_complete_model.load_complete。缺字段、hash或来源变化会拒绝，不默默退回initialize_scene或补零。

- PLY SHA：a343ccf05292ce1e174c7fd63795122347a8d03bd0202a19395a9a414b691f41。
- 检查点SHA：c3425ba01892940353909dbf3f95d5058ef507e023357ef864d4cb1460cac344。
- source SHA：7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf。
- preparation SHA：e67d4dce02f9874e0befe15486532f80458f8a62a23221324fcc5abefc2e5301。
- 50095点：room26054、face8286、hair2917、稳定分类accessory5、body12833。分类5点不代表整副眼镜只有5点。
- 67个模型状态字段与原检查点逐项torch.equal。
- **重新计算、导出的PLY hash与原资产完全相同**，不是复制旧PLY冒充恢复。
- 参考时刻frame_0010.png的原生float RGB/alpha/q与历史结果最大、均值差都为0。
- 参考时刻加5个已有world开发观察完成全幅绘制；输出在P/backend/.sources/complete-baseline-recovery-20261002-b。

私人检查点、PLY、源点表、相机和观测记录按hash复制到P/backend/.sources/baselines/7ac189eb49e0/a343ccf05292。原W、历史run、prepared未改，没有再次拍摄。Git保存代码与hash清单，仍不等于独立外部资产备份。

## 恢复与绘制边界

合并已有LocalPortraitModel、SharedSurfaceModel、ContinuityStage、FreeComponent和受限姿态的恢复数学到可调用模块，不移植旧runner或修改依赖。按冻结观察顺序恢复pose索引；完整加载几何、SH、协方差参数、身体/过渡、keep表和来源。

通过weights_only=True、静态global检查和固定标准NumPy类型白名单读取，不执行任意pickle。恢复后参数冻结；没有创建Adam/backward/density/重新取色。原优化器/RNG记录保留，本次不是训练resume。

保留原短窗口身体运动及窗外“冻结且未知”诊断，不升级为整分钟可靠运动。发壳、镜架、颈部、衣物缺陷未被分类或刷色掩盖。

原生全幅投影/排序/共同合成后切ROI保持。原quaternion/scale路径与历史完全一致。显式covariance路径完整RGB平均差约4.4e-8至5.9e-8、最大差约0.00077至0.00287；少数局部q差异触发预设0.003门槛，该迁移合同仍失败。这种极小平均变化不能解释整幅白雾。未放宽判据、修改gamma/曝光/颜色/剔除；完整恢复默认保留原合同，仍使用gsplat1.5.3。

首次检查失败证据在complete-baseline-recovery-20261002；第二次分开记录“原始基线恢复”和“新绘制分支可替换”，不把失败变通过。

## 验证与资源

17项新/已有检查点、真实CUDA全幅、人像来源/绑定/事务回归通过，3.313秒。测试通过不是画质通过。

完整恢复与6视角重放34.157秒，Torch allocated峰值865.37MiB。这不是训练耗时或2—3分钟完整建模成绩。图、参数和相机在私人report.json关联；原开发/回归用途不改，不称最终盲测。

复现，在P/backend与现有/opt/self-reconstruction/venv：

```text
python -B audit_complete_baseline.py --manifest reconstruction_baseline.json --out .sources/<fresh-replay-output>
python -B -m unittest test_reconstruction_checkpoint test_reconstruction_live_fullframe test_reconstruction_portrait_model -v
```

## 后续入口

基线恢复门槛通过，后续从完整状态修缮。优先用有多视图依据的有限物理表面接替异常宽room核，保住完整环境并冻结已取得的人像状态；不把全局降opacity、删背景或全局压scale当去雾。候选同时检查人脸、头发、颈肩衣物、真实环境和误遮挡；失败保留原状态。

平板实际服务的完整阶段接入仍未完成。本次未修改engine-profile或回传，不能称新视频服务已经全量切换，不能将旧个人PLY返回给新视频冒充新建模。
