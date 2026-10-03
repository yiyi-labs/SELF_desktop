# 新版重建接入实际测试（2026-09-28）

## 范围与启用方式

用户本轮明确要求接入新算法进行实际测试。启用的是 `portrait-first-soft-surface-0.1-research`，以 FLAME Open、头局部 SH1、共享软表面、真实图像优化及完整场景共同前向为基础。允许用户预览研究候选，不代表 E1—E5 的最终发布质量已通过。

保留应用包、签名、历史作品、PlayCanvas、上脸数据、DeepSeek 与故事代码。此轮没有改动这些文件；仓库中已有的其他修改没有回退。没有将历史作品计入最新算法成功。

`backend/.data/reconstruction/engine-profile.json` 已启用 `portrait-first-soft-surface-test`，要求明确的 `userTestingAuthorized`。现有启动脚本和 USB 自动重连任务读取同一固定任务目录。任务目录继续是 `backend/.data/reconstruction/<jobId>`，新提交产生新 job，不覆盖历史模型。

不需要重装平板。保持 USB 调试连接，在现有 SELF 的采集记录中选择视频并提交即可调用新版；已完成的旧作品不会自动变成新算法结果。

## 本轮文件级修改

- `backend/reconstruction_runtime.py`：显式算法路由、严格同原片哈希缓存、新视频准备、实际训练、结果哈希和算法记录。
- `backend/reconstruction_live_prepare.py`：通用新提交入口；全人物静态特征排除、有限静态相机求解、局部本人几何拟合、原片直接取色及多视图部件支持。缺失世界相机不默认补齐。眼区边缘不能冒充眼镜三维几何。
- `backend/reconstruction_worker.py`：在既有校验、取消、清理和返回协议中接入新版。任务附带 `releaseApproved=false`、实际算法版本和步数。
- `backend/recon_transfer.py`：仅新增可选算法标识，协议仍为 1。
- `backend/reconstruction_portrait_pipeline.py`：更新研究结果限制说明，不改变优化算法。
- `backend/test_reconstruction_runtime.py`：路由、授权、同原片缓存及清理测试；已有取消测试补齐真实观测准备依赖的隔离。

研究缓存只在原视频 SHA-256 完全相同、目录属于私有工作区时复用。不同视频走自动准备，不借用别人的形状、相机或颜色。缓存输入、模型和颜色检查点继续由原有加载器校验。

## 本次真实运行

原片 SHA-256：`7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。

### 实际 HTTP 服务任务

Job：`a31e9abe152502e97c2d39474c54b91d`。通过现有分块上传、seal、轮询与下载端点执行，没有直接把旧 PLY 当成新结果。

- 同原片已核验观测复用；重新运行 local 900、T3 300、T4 300 步。
- 实际训练与审计 160.54 秒；worker 总计 163.56 秒；客户端含排队/轮询/下载 185.63 秒。
- 34,083 点，PLY 8,045,064 字节。
- PLY SHA-256：`8f64c47bbf77c941b45cab4a5ae07999458b396cd0b6952bf13be27507bbab50`。
- PLY 和 view 的 HTTP 下载均与 manifest 字节数和哈希一致。
- 服务任务原视频和训练临时目录已清理；保留结果、预览和来源映射。

### 自动重新准备，不依赖旧拟合观测

独立 run：`backend/.sources/portrait-live-fresh-20260928-a`。同一原视频重新抽帧、识别、求解相机、拟合本人和初始化；不是不同人的跨视频验证。

- 32 个局部观测，21 个实际注册世界观测；世界训练 17、开发验证 4。另 11 个局部观测不伪造世界相机。
- 从抽帧到自动准备约 220.65 秒；再实际执行 local 900、T3 300、T4 300，约 133.00 秒。此路径不能宣称全流程 2—3 分钟。
- 11,341 点；PLY SHA-256：`4ed3c378bc9ca68bb3656197ab89a5ed7d5b8b7c0c2c6435076ede6b3fe65a37`。
- torch 分配峰值 218.08 MiB，保留峰值 444 MiB。这不是整卡峰值；本轮不据此宣布 8GB 已通过所有负载。
- 独立头发支持很少（初始化 17 点），眼镜独立部件为 0；头发覆盖和完整颈肩连续性尚不合格。运行成功不等于质量通过。
- 本独立候选没有作为旧作品替换或自动导入平板作品。

该 run 的 `training/report.json`、`config.json`、原片/初始化/最终对照和 `prepared/automatic-prepare-audit.json` 保留在私有研究目录。测试所复制的视频已删除；复现时可从本轮已授权保留的原片基线恢复，不需要重新拍摄。

## 鸿蒙端证据

真机 HDC：`6DP0226117002287`。`tcp:8787 tcp:8787 [Reverse]` 存在。

从平板 shell 经 USB 向 `127.0.0.1:8787/v1/reconstruction/health` 发出真实 HTTP 请求，返回 200，`engine=ready`、`algorithm=portrait-first-soft-surface-test`。

平板经该通道下载上述服务任务的新 PLY，实际 SHA-256 与电脑完全一致。下载放在独立 `/data/local/tmp/self-algorithm-20260928/test.ply`，核验后已删除，未写入用户历史作品。

这证明新版服务与真实设备传输通道可用；没有通过该 shell 测试证明应用内导入、连续绕看或编辑视觉通过。点按和实际视觉测试由用户进行。

## 回归、复现与结论

在安装的 WSL 环境执行：

```text
cd /mnt/d/STUDY/College/mine/olay/backend
/opt/self-reconstruction/venv/bin/python -m unittest test_reconstruction_runtime test_reconstruction_cancel test_reconstruction_portrait_model test_reconstruction_accessories -v
```

25 项通过，日志：`backend/.sources/portrait-live-regression-final.log`。

HTTP 复现脚本：`backend/.sources/probe_portrait_live_http.py`，仅本机读取密钥配置，不打印密钥；运行会创建新的真实任务。自动准备脚本：`backend/.sources/probe_portrait_fresh_prepare.py`；独立 run 目录必须换新名称。

通过：显式新版路由、取消/输入清理回归、真实优化、导出、HTTP 下载哈希、真机 USB 下载哈希、已有自动重连任务重新启动。

未通过：最终头发/眼镜/颈肩完整质量与 E1—E5 发布验收。

未验证：用户本次在应用内实际提交后的导入和画质、其他人的新视频、无眼镜实拍、真机连续绕看及编辑视觉兼容。旧作品、既有上脸和故事功能均保留，不以此次链路运行替代它们的视觉验收。
