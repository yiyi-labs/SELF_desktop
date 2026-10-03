# 当前设备测试入口身份核对

2026-10-02，只读取当前任务、状态、配置、报告和安全检查点。未重训、部署、回传或操作设备页面。

## 确定结论

当前服务不是 50,095 点完整内容路线。最新完成任务 `f44e259d245820dd916ed3ad06d7ad88` 使用相同原片 hash，但重新从旧准备初始化，产出 34,083 点。原始部件为 room 22,020、body 348、表面 8,798、头发 2,917；完整基线为 room 26,054、body 12,833、face 8,286、hair 2,917、classifiedAccessory 5。分类点数量不等于实体眼镜点数。

实际运行了 local 900 步（74.65 秒）和 T3 300 步（45.45 秒）；joint 0，两个阶段 densityEvents 都为空。`surfaceRefine=false`，`resumeState=null`，没有恢复完整基线。训练与审计总计 185.62 秒，含服务收尾总计 189.86 秒，分配显存峰值 730.48 MiB、缓存峰值 898 MiB。因复用同原片准备且没有完整内容阶段，这次负载较小，不能归因为 8 GB 不足或电脑根本没训练。

审查时队列 20 个完成、5 个失败、8 个取消，无 queued/running；电脑空闲符合任务已经结束的事实。原片的临时研究副本仍存在，本次已重新核对 hash，可用于离线复测，无需重新拍摄。

最新 job 本地文件 PLY hash 已与 job.json 核对一致。HDC 连接存在，但未确认平板前台正显示哪一个 job；不能只凭用户截图宣称其恰好是上述最新任务。

## 实现差距

- `reconstruction_portrait_pipeline.initialize_scene` 调用原 `initialize`，保留旧 room 和未绑定衣物种子，重新实例化 `LocalPortraitModel`。
- `reconstruction_runtime.reconstruct_test` 默认只启用 local 900/T3 300；profile 未启用 surfaceRefine，因此未触发其有限密度分支。
- 头发位置自由度 `hair_delta` 的学习率为 0，旧头发壳并未被真实结构修复。
- 全幅绘制、参数更新与完整内容初始化是不同能力；全幅入口已经执行不代表完整表面路线已接入。
- job 报告明确 fidelityGatePassed=false、releaseApproved=false，只是用户授权的研究预览。当前代码不能把这一状态说成整体画质通过。

六个固定全幅观察的 room RGB L1 为 0.261—0.444，room 低 alpha 比例 78.18%—91.37%，衣物低 alpha 比例 9.15%—25.07%。低 alpha 是覆盖诊断而非几何真值，但与用户画面中的大面积背景缺失一致，应与原片结构及真实投影联合判断。

## 本轮服务身份最小修正

启动时保存工作器的实际代码闭包 hash，心跳和每次领任务前再次核对。代码变化时工作器必须 ready=false，新的 profile 不能给旧已加载代码重新授权；配置读取失败同样给出未就绪状态。原实现仅在启动时做一次 preflight，心跳一直复制旧 ready，存在已改源码仍显示 ready 的缺陷。

结果增加 executionReceipt：实际初始化数量、最终部件数量、各阶段真实步数/耗时/密度事件及恢复方式。保留 portrait-import.json；从 local-init.pt 安全读取 environment_parts/portrait.role 的实际分组和初始化哈希，两种分组语义分别记录。缺失时写明 unrecorded，不根据当前默认值回填过去事实。

本文件与 JSON 只保存身份、阶段和数值，不含图像或私人原片。未改算法、profile、签名、作品，也未重启工作器。本次代码变更需要由集成步骤核对新 profile 并重启工作器后才会生效；旧运行进程不因磁盘文件变化自动具备这些检查。

WSL 中执行 `python -B -m unittest test_reconstruction_runtime test_reconstruction_cancel -q`，14 项通过，1.408 秒，包括源码/profile 失效、已缓存 ready 撤销、GPU 失败不能被源码检查改成成功、真实初始化/终态语义组数、私有输入清理与真实子进程取消。上述通过只验证服务合同，不表示画质通过。
