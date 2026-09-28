# SELF v3 隔离实施记录

2026-09-28。先完成总审查、开源差距与计划，并在79272a8提交；再编写v3。原现场提交c46286a保留。下面是实际做了什么，不把规划中的完整人体重建当成已完成。

## 实际代码范围

| 文件 | 本轮实现 | 仍然没有实现 |
|---|---|---|
| reconstruction_components_v3.py | 显式五部件、整数来源索引、独立坐标系、受限独立offset、强哈希sidecar、交接阻断、无cwd依赖输入适配 | 不会自动识别出正确镜框/躯干运动；输入mask仍是估计 |
| reconstruction_portrait_local_v3.py | 同次头部前向，冻结现有脸，独立训练真实多视图hair/accessory的SH、alpha、scale、rotation，40步后允许offset；360实际Adam步 | 没有声称已恢复高质量发型、镜腿或新面部细节；本轮B只是附件结构/容量实验，完整Portrait-first尚未通过 |
| reconstruction_world_static_v3.py | 只优化room，RGB监督只来自可见静态区域，人物、衣物不进入room优化器；360步 | 无可靠E1清单时必须显式research模式；不能把99局部观察全当世界相机 |
| reconstruction_compose_v3.py | 一次完整场景合成；根据实际足迹贡献、深度、静态支持和unknown缓冲区作候选审计；联合训练交接阻断 | 未接受相机/几何时不自动删背景，尚无合格轻量联合训练 |
| audit_reconstruction_v3.py | 按名称对原PTS/PNG/mask/F/K/C，直接核对实际COLMAP imageId/cameraId；逐视角原生ROI、局部图、完整场景alpha/来源贡献 | 不将开发帧当盲测、不用viewer yaw冒称拍摄角 |
| run_reconstruction_v3.py | 独立run-id、拒绝覆盖、真实GPU训练/遥测、固定参考PLY、全长来源/绑定sidecar | 无worker/store/HDC发布依赖；不能直接成为生产默认 |
| replay_reconstruction_v3.py | 从优化器保存的真实状态补绘制审计，明确新训练步数0 | 回放不计算作第二次训练成功 |
| viewer-gs/main.js | 仅Asset加载增加reorder:false，保存已有PLY点序 | 绘制时深度排序、编辑算法、主题均不改；未构建entry/HAP |
| scripts/build-v3-viewer.mjs、probe-v3-*.mjs | 私有bundle；所有59字段逐数组哈希；沿用原圈选/试色/恢复/重放，单PLY连续轨道 | 不是鸿蒙端实测，不是产品效果验证 |

## 输入、部件和阶段

同源Open SH1基线，没有再做Open/普通FLAME A/B；面部8798点保持基线，旧2917粗发壳只留在对照列。本轮结构实验用267真实多视图发种子和16配件种子替代壳，另外348准静态衣物点与22020静态表面点。这样拆分能揭示表示不足，**不是**默认切换成缺头发的新模型。原用户作品没有任何替换。

99局部观察=91训练+8开发；其中64有现有世界估计（59训练+5开发）。按实际地图核对C与存储C最大差为0。还有35帧没有世界C，不合成、不补单位矩阵。64世界估计没有自动升级为E1可靠相机。局部F与C都按同一记录K/去畸变图使用，裁剪只减主点，半尺寸图同步缩放K。新实验没有改变采集协议。

阶段B只训练附件，脸参数完全冻结；阶段C只训练room，脸/发/镜框参数哈希均保持不变；衣物始终是独立部件，不再并入room，但目前运动是假设而非解答。D只生成明确标为失败研究的诊断画面，所有部件一次共同合成，**没有运行未获准的联合训练**。E对这份失败几何只检查格式/点序/绘制可用性。

每一步仍归属原E1—E5，不另起质量放行制度。没有新密度替换动作；保留并运行既有父点替换、Adam、绑定、来源回归。这样不能宣称解决了容量不足，只表示没有用未经验证的split去破坏基线。

## 可复现命令

Windows隔离根目录：`C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay`。
WSL对应目录：`/mnt/c/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay`。
所有结果写入该根的backend/.sources；输入原目录只读。模型文件复制到隔离项目private目录，SHA保持e75a0990…127623，没有从下载目录临时加载。

```bash
cd /mnt/c/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend
export CUDA_HOME=/usr/local/cuda-12.8
export TORCH_CUDA_ARCH_LIST=12.0
export MAX_JOBS=2
export PATH=/opt/self-reconstruction/venv/bin:/usr/local/cuda-12.8/bin:/usr/sbin:/usr/bin:/sbin:/bin
/opt/self-reconstruction/venv/bin/python run_reconstruction_v3.py \
 /mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e \
 .sources/reconstruction-v3-NEW-ID --attachment-steps 360 --static-steps 360 --research-cameras
/opt/self-reconstruction/venv/bin/python replay_reconstruction_v3.py \
 .sources/reconstruction-v3-20260928-a .sources/reconstruction-v3-NEW-AUDIT
/opt/self-reconstruction/venv/bin/python replay_reconstruction_v3.py \
 .sources/reconstruction-v3-20260928-a .sources/reconstruction-v3-NEW-FOOTPRINT --front-only
```

实际-a运行的算法源代码另存run/algorithm-source，代码哈希在config.json。之后修复的是审计图同名覆盖、输入路径适配和投影足迹诊断，未暗改-a保存的训练状态或重新声称训练。旧-a最初D只查中心；最终足迹审计在独立-a-footprint目录，不能混成同一算法步骤。

```powershell
node scripts/build-v3-viewer.mjs backend/.sources/reconstruction-v3-20260928-a
node scripts/probe-v3-point-order.mjs backend/.sources/reconstruction-v3-20260928-a
node scripts/probe-v3-edit-contract.mjs backend/.sources/reconstruction-v3-20260928-a --full-scene --projected-region
node scripts/probe-v3-continuous-orbit.mjs backend/.sources/reconstruction-v3-20260928-a --full-scene
```

采用原PlayCanvas2.22.4 MIT、esbuild0.28.2、playwright-core1.63.0、pngjs7.0.0。离线npm缓存缺three包，完整ci未完成；之后只把所需的五个已安装包逐目录复制到隔离node_modules，锁文件未改，以上实际构建/绘制通过。构建第一次漏了既有node:worker_threads external选项，失败已定位，研究build脚本复用正确配置；没有因此修改引擎。

## Git与生产回归

20项现有/新回归通过后，新增“中心在面外但足迹遮脸”实算测试，v3五项重跑通过，共21个不同测试。未重复开发已通过的PLY解析、格式往返、来源守恒基础探针。原项目1639文件哈希逐项一致，status哈希26338b0026321936b864a2f5aa875c9b6ea5e9f4a6c22b2625eeff0540d8a883与开始相同；原master和HEAD未变。entry、签名、作品、协议、上脸、故事、worker/runtime配置均未改动。

私人人像PNG、PLY、权重不纳入Git；私有文件完整哈希清单与小体积结果入库。保留旧run，不清理数据，不自动回传。隔离分支回退可查看c46286a（现场）或79272a8（仅审查）；不要对原工作区执行reset/clean。
