# 人像优先、完整可见环境：实际训练记录（2026-09-29）

## 本轮结论

- **人脸已经实际训练，但没有得到稳定、可放行的细节改善。** 开发集 face L1 改善，预留审计视角反而退化；鼻翼、唇缘、镜框仍明显软化，耳侧/下颈有杂纹。不能写成“整张脸修复成功”。
- **背景确实学习了完整可见影像。** 柜门、墙、顶面可以辨认，旧的大面积缺图明显改善；没有删除背景或恢复无依据的房间散点。高 alpha 和 RGB 改善仍不证明背景几何完全正确。
- **同一人像的世界变换基本保持，联合训练未稳定保持质量。** T3 冻结人像参数逐字节一致；T4 实际改变了人像，预留审计误差继续恶化。此 T4 仅保存为失败研究候选。
- **仍不可发布/回传。** 头发真实外表面、独立镜框、颈肩衣物连续性、分辨率敏感遮挡和最终设备显示尚未通过。本轮没有部署、HDC、模型回传或覆盖旧作品。

## 现场与身份

W `C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay`；P `D:/STUDY/College/mine/olay`。
P HEAD 仍为 `f68587bb34f8970d21bda9231e15b2536a33df97`，本轮没有对 P 写入。
起点 `13b1b0f58c87aa08c23b56999b4aa962fd542862`；d2 独立提交 `cef6c043ed7a4ad397de41c995b7787ec3db0ce5`。
历史 27c9810、933f664、9a6bef3 保留。原有未追踪审计目录没有顺带提交或清理。

输入仍为 capture-1790410633104.mp4 的固定准备；source SHA256:
`7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。
FLAME Open 模型 SHA256 `e75a0990728ba038c7da2a420ae4396f7ddd7781366c13026066c5b24f127623`。
正确 head-local-sh1 旧900参数 SHA256 `308da67a299dc98855fa4d3403197130811ec87d96dcb7ad967eee92950d9e46`。
旧900没有 Adam，本轮是 warm-start，不是历史训练精确 resume。新共享表面残差的零初值明确记录；旧细点、绑定、offset、SH、原始形状/表达存档和 F/K/C 未默默丢弃。

所有训练输入、198份图像/标签文件、代码快照及 hash 见 `C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/portrait-priority-training-20260929-a/contract.json` 与 `algorithm-source/`。初始化、中期、终态模型/Adam、密度状态、RNG、帧采样器及稳定点谱系保存为独立 `.pt`，不在 Git 内。实际运行使用本次快照；工作区随后仅补了许可注释和独立审计工具。

## 已实际执行

| 阶段 | 实际优化 | 结果/边界 |
|---|---:|---|
| d2 | 0训练 | 357新增、50拒绝、4已有、1704旧判断回归；d>=3/原过滤不变 |
| face-local | 900 + 48恢复步 | 32训练视角，其中9个仅有可靠局部 F；原生ROI；外观后交替小幅姿态、共享表面和嵌入 |
| face 拓扑 | 两次 | 126 + 128父点被真正替换，2个提议因子点观测不足被拒；11715→11969点；两次覆盖恢复检查通过，不等于整体画质通过 |
| room | 900 | 全有效room RGB + 有效窗口结构 + 覆盖；真实 means/scale/quat/opacity/SH 优化 |
| room 密度 | 200/400/500/600步 | 1141复制、2955分裂父点、3裁剪；22020→26113；300步实际reset，末次拓扑后300步恢复 |
| T3 | 120 | 完整共同合成，暂冻人像修环境/身体；人像参数hash完全保持 |
| T4 | 120 | 完整共同合成+原生头部监督；人像审计退化，不可放行 |

镜框仍有部分沿用旧表面细节点，未虚构为新独立三维镜框；2917个旧头发壳点继续优化但没有宣称已变成真实发型。身体有独立于头 F 的有界上身运动参数，但348个衣物种子仍不足以重建清楚衣领、肩和衣服；没有把模糊衣物算作连续性通过。

## 同协议固定 ROI RGB L1

| 集合/部位 | 可恢复基线 | 局部训练后 | 联合后 |
|---|---:|---:|---:|
| development/face | 0.033757 | 0.031474 | 0.032417 |
| development/hair | 0.044232 | 0.039452 | 0.039598 |
| development/glasses | 0.137298 | 0.134755 | 0.134667 |
| audit/face | 0.040160 | 0.041142 | 0.044052 |
| audit/hair | 0.044040 | 0.043231 | 0.043053 |
| audit/glasses | 0.157444 | 0.162336 | 0.162792 |


8 development 已参与历史方案选择；6 audit 为本轮预先留出、未用于本轮选视图/颜色训练，历史研究可能看过这些图，因此不叫完全独立最终测试。原始缺失像素继续进入固定分母。

局部原生像素指标：开发集鼻翼 0.035942→0.035122→0.036135，唇缘 0.027165→0.025937→0.027610；audit 鼻翼 0.047083→0.049208→0.052913，唇缘 0.035922→0.036439→0.043039。并非所有改动都提高真实细节；只看开发平均数会掩盖退化。

## 背景与加入环境后的归因

五个开发世界视角全幅半分辨率的 room 固定 L1：初始0.454—0.624，最终0.0341—0.0433；alpha<0.8比例由85.0%—95.7%降到0.17%—3.56%。这些是相同 mask/尺寸下的诊断，不是几何完整性判定。画面中能看到柜门/墙/顶面，但身体和颈部依然失真。

只读检查 `C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/portrait-priority-joint-audit-20260929-a/report.json`：
- T3 与 room-final 的人像参数 hash 完全相同，证明没有通过换粗模板或删点拼接。
- 同一原生ROI的 T0→T1 RGB 平均差约1.8e-7—4.6e-7；少量像素最大差最高0.00842。没有大范围坐标错误的证据，但不把非零差异当成完全逐像素一致，亦未排除共用排序近似。
- 发现明确的**分辨率敏感遮挡**：room-final 的0115脸区 q_room，全幅半分辨率约0.1550，原生ROI约0.0154；参考0111约0.2164 vs 0.00924。T3/T4后减少但未完全消失。这不能只归咎“脸像素少”或显存不足，也不能通过删背景消除。
- 最终房间相对根种子的尺度倍数 p50/p90/p99 为1.213/1.700/3.237；位置漂移为0.00796/0.03158/0.19527模型单位。没有统一放大全部点，但尾部漂移及投影足迹需继续验证；这不是独立深度真值或实测米制精度。

## 画面、单资产交接

四列对照顺序：**原片 / 可恢复旧基线 / 本次局部训练后 / 联合后**，没有锐化、刷黑、生成细节或美化滤镜。

- [0035四列对照](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/portrait-priority-handoff-20260929-b/local-comparison/frame_0035.png-four-panel.png)
- [0098审计对照](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/portrait-priority-handoff-20260929-b/local-comparison/frame_0098.png-four-panel.png)
- [完整画面对照](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/portrait-priority-training-20260929-a/world-final-images/frame_0115.png)
- [同一PLY连续绕看](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/portrait-priority-handoff-20260929-b/same-ply-continuous-orbit.mp4)

固定 PLY：`C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/portrait-priority-handoff-20260929-b/fixed-reference.gaussian.ply`，38430点，参考frame_0111。
SHA256 `f3ca3845936d1b19b2cf278fcfd7165c30f66973517f268dccf583537e11348e`。
96帧均回载这一份固定资产，不随角度换模型；每帧 K/C 和轨道参数在 `handoff.json`。±20°轨道标签不是实际观察角的认证，不能因此认为未拍区域已验证。
PLY roundtrip RGB 平均差 4.19454551e-08，最大差 0.000648021698；原生SH语义与回载保持。
第一次审计a遗漏衣物支持度；b按精确source ID从冻结348个衣物种子恢复，PLY hash完全不变，a证据保留。最终sidecar含完整长度部件、来源、支持度、三角绑定、稳定UID/父UID/代数。
此绕看由gsplat1.5.3绘制；**没有冒充PlayCanvas或鸿蒙本轮显示测试**，这两项未验证。本轮不回传坏候选。

## 资源、环境和测试

开始时Windows仍报告独显不在场、WSL CUDA不可用；随后同一训练入口实际恢复CUDA，未由助手改驱动/切模式/重启。实际设备RTX5070 Laptop、torch2.8.0+cu128、gsplat1.5.3。
- face 32.32s；room 15.64s；T3 3.50s；T4 7.19s。
- 该次加载、首次内核编译、绘制检查和训练总计 228.46s；不包含之前视频采集、分割、SfM/FLAME准备。未独立精确计时编译，也没有重跑一遍当成热启动实测。
- Torch allocated峰值 400.94MiB，reserved 462.00MiB；后半段2秒采样的整机显存最大1091MiB，59个样本。该采样不是完整运行无遗漏的整机峰值。
- 无OOM。**本次没有证据证明8GB是画质瓶颈**；稀疏附件、姿态/对应和分辨率敏感共同遮挡仍更直接。完整采集到成品2–3分钟目标尚未验证。
- 27项相关回归+1项后加的实际pre/post密度时序测试通过；真实CPU输入检查通过，完整头部/SH/来源保留。真实GPU执行和有限joint已经发生，不能再写脸冻结或joint占位。
- Checkpoint恢复合同证明拓扑改变后Adam/采样器/RNG恢复的下一次合成更新逐值一致。正式跨进程GPU训练续跑尚未额外对照；旧900依旧只能warm-start。

## 最小下一步与未完成项

本轮有限预算已用完，不继续加步数或无界调参。下一项优先修复应针对**人物保护与投影分辨率合同**：保持T3冻结人像，在同一资产/相机下核对全幅与原生ROI的足迹、共同排序和经典/AA贡献；据证据统一监督与投影口径，并使T4人物更新以可回退候选接受，不能让全场优化重新损伤已保留脸部。该诊断不能替代后续原生局部对应/共享表面的质量改进。

独立未完成：真实头发外表面与发际线、跨视图镜框、非刚性颈肩/衣领连续性、低纹理背景深度约束、跨视频泛化、最终PlayCanvas/鸿蒙画质与性能。保留E1—E5发布要求，全部未通过前不切生产默认。

## 官方参考与复用范围

[gsplat1.5.3策略合同](https://docs.gsplat.studio/versions/1.5.3/apis/strategy.html)、[锁定版simple_trainer](https://github.com/nerfstudio-project/gsplat/blob/v1.5.3/examples/simple_trainer.py)仅作为优化器/回调/密度流程参考，未整套替换工程。
使用安装包DefaultStrategy的统计、ops的参数/Adam同步；本地适配有限预算、谱系、显式reset和保守裁剪。官方示例不是已经适配的人像实现。
官方[Apache-2.0许可](https://github.com/nerfstudio-project/gsplat/blob/v1.5.3/LICENSE)已保存为同目录gsplat-1.5.3-LICENSE.txt；没有引入其他论文的非商用代码或普通版FLAME作为默认。
安装源码hash：default.py `8f9cf7d5cb02999cdb3abfb85d796e6989d5249c25ed7b08ee58538a4288a622`；ops.py `b30fa9e4d60a97ec619eb54d43d158d3e9dc8102c3d971acbb46da8385b53074`；rendering.py `6b5e4101035031afbb26bed7e496382c7502f9d8bc7cc9a432f290674a4d9133`。
