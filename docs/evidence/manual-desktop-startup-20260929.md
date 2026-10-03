# 电脑端手动启动验收（2026-09-29）

本轮只新增点击启动入口、手动任务配置和启动检查，更新运行说明。已有算法、模型参数、API、GPU 工作器和 USB 守护脚本均未修改。工作区此前已经存在的修改保留。

## 使用

在项目根目录双击 `Start-SELF.cmd`。出现“SELF 已就绪：电脑服务和 GPU 工作器均正常”后即可使用。重复点击只检查既有服务，不创建重复工作器。终端窗口关闭后服务继续运行；电脑重启后需要再次点击。

`SELF Reconstruction Link` 已改为仅手动触发：触发器数量为 0，`StartWhenAvailable=false`，任务失败自动重启次数为 0，`AllowDemandStart=true`。保留既有 USB 重连和已开启会话中的服务恢复逻辑。修改前的任务定义备份在 `artifacts/reconstruction-task-before-manual.xml`。

迁移或重新配置使用 `scripts/Set-ReconstructionManualStartup.ps1`，该脚本不会启动服务。旧 `Enable-ReconstructionAutostart.ps1` 是历史自启动工具，运行它会恢复登录自启动。

## 实测结果

| 检查 | 结果 |
|---|---|
| Windows PowerShell 5.1 脚本兼容性 | 两个新增 PowerShell 脚本语法检查通过，实际入口执行通过 |
| 完全停止后的点击启动 | 旧 HTTP、守护进程和 GPU 工作器完全停止后，通过根目录 CMD 入口启动；约 14.2 秒，返回码 0 |
| 不依赖当前工作目录 | 从 `C:\Windows` 和带空格的 `C:\Program Files` 实际调用入口，通过 |
| HTTP 与 GPU 就绪 | `/health` 与重建健康接口均就绪；检查新工作器心跳，避免使用旧就绪记录 |
| GPU 实际计算 | RTX 5070 Laptop GPU、CUDA 可用；32×32 全 1 矩阵相乘并同步，结果为 32.0 |
| 重复点击 | 连续再次执行两次，返回码均为 0；仍为同一个守护进程、一个 WSL 工作器 |
| 关闭提示终端 | 入口退出后服务和 GPU 工作器继续运行，后续健康检查通过 |
| 未接 USB | 明确显示当前未连接目标平板，电脑服务仍成功启动 |
| 开机策略 | 实际任务定义没有任何触发器，也没有补启动或任务失败自动重启配置 |
| 算法文件未修改 | 与本轮开始前的 SHA-256 比较，275 个算法及相关源码文件全部一致 |

初次冷启动测试发现 Windows 显卡正常，但 WSL 报 `GPU access blocked by the operating system`，工作器报 `RTX 5070 CUDA unavailable`。入口没有误报成功，而是在超时后返回 1。确认其他发行版已停止、没有其他活动 WSL 会话、容器或建模任务后，重启空闲 WSL 环境，GPU 恢复，随后完整启动和重复启动测试通过。没有修改驱动、算法或依赖，也没有将 WSL 重启写进点击启动流程。

原始结果位于 `artifacts/startup-cold-result.json`、`artifacts/startup-cold-retest-result.json`、`artifacts/startup-repeat-result.json`；源码哈希基线在 `artifacts/startup-algorithm-baseline.json`。

本轮未实际重启 Windows 或退出登录；开机策略通过已保存的任务定义核对。平板未连接，因此未复测真实 USB 重连、平板界面或新的个人重建质量。
