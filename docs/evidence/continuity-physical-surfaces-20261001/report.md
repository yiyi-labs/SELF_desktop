# SELF：头颈衣物连续性、真实表面与多视图面部修缮

2026-10-01。完成隔离后端实现、有限真实GPU训练和实际电脑绘制。**完整目标仍未实现，新资产全部拒绝发布，未部署、未回传、未切生产默认。**原E1—E5不变。

## 实际结论

1. **颈肩衣物有可见局部进展。** 真实观察支持的颈皮肤、衣物分层初始化和训练，让参考画面中旧模型缺失的脖子、衣领、胸前纹理出现。连续运动在部分短窗观察优于静态控制；0035、0130、0145的颈部仍退化，下颌接触存在色差。不能说整段连接已修好。
2. **面部实际训练，但未取得可保留的清晰度提升。** 20条原生纹理轨迹同时约束源/目标/第三观察，共享表面和有界F真实更新，再与控制各180步外观恢复。对应误差下降，画面差别却很小，两组0055均越过预先容差。
3. **头发外表面候选实际训练240步。** 某些视角覆盖和RGB改善，另一些发际线误遮和亮边仍在。局部屏25条失败，完整T2屏2条面部覆盖失败。没有刷黑、生成发丝或磨掉头发，镜框未被删除。
4. **完整有效房间影像参与训练，room仍失败。** 白墙/柜门/天花板不因低纹理被排除；全部组件共同合成、人物冻结。0027、0028、0145触发room覆盖退化，旧宽核遮脸仍未解除。不能以点更多或alpha高放行。
5. **保护范围通过。** 六最终分支非授权字段精确一致；模型、Adam、bindings、sampler、RNG、strategy、trainable均完整恢复。工程保护通过不等于画质通过，也不能保证未来任意视频。

## 现场、输入及保护

- W：`C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay`，分支`codex/reconstruction-v3-audit-20260928`。开始与提交前HEAD：`18f25eb0781e8ba2d07a8b564e5a291f0f94ce33`。
- P：`D:/STUDY/College/mine/olay`，HEAD `3dad0cd5651824cc06d9e88d61aabdd2642c0b30`。18项tracked修改未处理。W原有未跟踪暂停/审计文件未暂存，原索引为空。
- 未找到适用AGENTS.md。没有reset/clean/stash/rebase/amend/强推、清理run/worktree。P、应用、签名、旧作品、USB/HDC、生产查看器、AI/OLAY、上脸、故事和UI均未写入。
- 视频`capture-1790410633104.mp4` SHA256：`7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。原片已包含两侧本人，世界C缺口不能称为没拍到另一侧。
- prepared：`P/backend/.sources/integrated-components-v2-20260928-e`，preparation.json SHA256：`e67d4dce02f9874e0befe15486532f80458f8a62a23221324fcc5abefc2e5301`。
- R0：`W/backend/.sources/fullframe-surface-patch-20260929-b/R0-frozen.pt` SHA256：`2468edc379f8b76eac97fccfbf9e9a4c775f980102b95283ee15b2dc4cee7cb8`，结束复核不变。38372点：head11970、room26054、body348。FLAME Open、head-local-SH1、全幅后切ROI保持。
- stage：`backend/.sources/motion-coverage-repair-20260930-a/stage.json`。原32 train/8 development/6固定回归保留；开发/回归长期参与研发，不是最终盲测。无可靠C的帧只用于local-head。
- 冻结DA3深度：`.sources/dense-motion-surface-20260930-h/depth`，manifest SHA256：`11391f4d5f55cf1d1d1fa5bd7ba314b006879affa0783be5dc5d8d59cdaeba23`。没有新下载、推理或依赖安装。

## 文件级实现

全部新增于W/backend，原生产函数和入口没有修改。

| 文件 | 实际作用 |
|---|---|
| reconstruction_continuity_surface.py | 按记录K/畸变校正原语义/置信图；颈/衣物分层；有界共享上身运动及连续颈权重；位置、协方差、SH共同运输 |
| build_continuity_candidates.py | 按真实时间/角色选短窗；至少3独立预测观察兼容；原生RGB、来源/UID、有限配额、同物理层邻接 |
| run_continuity_surface_repair.py | 单组件真实优化、完整T2共同遮挡、有限父表示退役提议、逐视图屏、完整恢复、标准PLY与精确sidecar |
| run_native_multiview_face_repair.py | 原生patch独立搜索、唯一峰、反向及仿射检查；每track共享表面锚；对称源/目标约束、第三观察留出；有限表面/F及同预算外观对照 |
| audit_continuity_asset.py | 复用既有冻结PLY审计，明确电脑/WSL路径，保存同资产连续绕看；不改查看器 |
| audit_continuity_results.py | 显式run汇总、完整状态/范围核对、原片/R0/控制/候选图；不自动择优 |
| test_reconstruction_continuity_surface.py | 语义隔离、参考恒等、连续性、运动梯度、SH旋转与物理层邻接 |
| test_native_face_measurement_contract.py | 实际ECC成功和低纹理/不可靠插值拒绝边界 |

训练规则不包含某个人、衣服logo、历史帧号或绝对像素位置。图像诊断显式帧号不参与训练筛选。其他视频和无眼镜用户泛化尚未测试。

## 查实并修复的交接问题

**身体皮肤不等于颈部。** 原selfie-multiclass类2包括手臂。首轮3000个neck样点中276个原生y>1500，这是定位混入的诊断，1500没有成为阈值。修复用脸下缘相对范围和已有连通皮肤关联颈部，保留unknown/真实缺口，不填像素、不焊衣领、不删除其他身体皮肤。修复前后独立保存，旧失败证据保留。

**方向色运输。** 首轮颈过渡线性混合两次旋转后的SH，不严格等于一个方向场的旋转。最终使用与协方差相同的每点归一化四元数，SH0不变、SH1范数保持、旋转梯度存在。`body-transition-sh`实际重新训练240步。坐标修复不能冒充几何通过。

**ECC通道。** 首次face入口错误地把RGB送到单通道ECC，实际报错停止。新入口只在测量转灰度，原始RGB继续用于训练；旧失败目录保留。合成亚像素插值patch也有被严格仿射复核拒绝的薄弱情况，已记录拒绝回归，没有放宽门槛。真实纹理差、反光和视角差仍阻塞可靠测量。

**路径。** 首次资产适配器的backend相对路径在W根启动Chrome时读取失败。旧输出保留，新输入仅改为经hash核对的绝对路径。最终适配器保存绝对路径，并重新实际绘制；没有更改相机/颜色/资产字节。

## 颈衣同条件训练

通用时间规则选出0005、0006、0010、0012、0013，1.798322—5.228456秒，参考0010。3000颈皮肤+9000衣物，独立物理层、同次光栅化。候选暂退役191旧head-neck和86旧body，其他旧参数保持；50095点。

上身只有六个共享速度参数，固定尺度和参考。颈运动权重在参考空间固定，上端跟头，下端跟身；不是颜色羽化。协方差方向运输、轴长保持，**不是完整应变模型或测量骨架**。短窗外B未知，身份矩阵只是冻结诊断，不能作为整段运动通过。

每组240次Adam更新：31次几何/运动、209次外观。有界offset、scale初始化±25%、同类邻接；没有density。固定区域包含缺失像素。

| 图像 | R0颈L1 | 静态控制 | 最终连续运动 | R0衣物 → 最终 |
|---|---:|---:|---:|---:|
| 0005 train | .206960 | .121530 | .080835 | .118207 → .095981 |
| 0006 train | .197498 | .102477 | .073482 | .118664 → .080758 |
| 0010 train | .140342 | .051417 | .049737 | .160126 → .050128 |
| 0012 train | .103424 | .044196 | .046291 | .182524 → .069868 |
| 0013 train | .093465 | .059728 | .062651 | .206897 → .093295 |
| 0015 dev | .087399 | .070095 | .067454 | .228063 → .118038 |
| 0035 dev | .063973 | .116128 | .096987 | .223111 → .164691 |
| 0130 dev | .060068 | .114190 | .138589 | .185870 → .155563 |
| 0145 dev | .054235 | .122651 | .128873 | .177926 → .145447 |

连续运动并非每视角优于控制；0035/0130/0145失败，拒绝。下颌色差、整段上身运动和手臂仍不合格。图中左至右为原片、R0、静态控制、最终连续运动：

![颈肩衣物对照](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/continuity-physical-surfaces-20261001-b/evidence-final/body-frame_0010.png.png)

## 面部真实测量与训练

四训练短窗有效轨迹9、6、5、0，共20条；第四窗大多唯一峰/仿射/反向检查失败，没有伪造匹配。46拟合观察、20第三观察。初始源误差近零来自射线交点，不是深度真值。

固定高斯数量/UID/绑定/角色，以真实纹理约束一个共享有界normal场。80步固定F，80步有限F；固定K、身份、尺度、世界C和表达。表面同步协方差，非皮肤保持；再做180步颜色/alpha/scale/quaternion恢复，控制同180步、同采样预算。没有生成细节或再次拆点。

| 原生对应误差px | 初始 | 几何后 |
|---|---:|---:|
| 拟合中位数 | .412540 | .294121 |
| 拟合P90 | 7.20 | 5.94 |
| 源P90 | .000122 | .271503 |
| 第三观察中位数 | 4.620268 | 4.435202 |
| 第三观察P90 | 7.02 | 6.96 |

几何只通过允许外观恢复的相对检查，**不是深度/形状质量通过**。第三残差仍大，raw pose增量达到.20边界，共享场raw最大变化.348119。不可继续仅延长步数或放宽姿态吸收错误。

0035控制/共享face L1 .023679/.023772，0075 .022460/.022481，0145 .025775/.025801；未见明确真实细节接管。两组0055均越过+.001容差，拒绝。原8开发/6回归不换集合，眼镜没有新线结构。

![原片R0控制和共享表面](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/continuity-physical-surfaces-20261001-b/evidence-final/face-frame_0035.png.png)

## 头发与完整环境

头发83412原始候选→74626去重→12000预算，24个不同训练观察、四预测窗。真实原片取色，相机条件预测深度是假设，不是完整发型真值。有限退役307个旧壳点，旧壳仍大量保留。局部25失败，完整T2的0134/0139面部覆盖失败。跨窗外表面还未独立证实，不能宣称发际线已修；镜腿/鼻托/反光结构未修。

room 215145原始候选→174402去重→22000预算。有限事务暂退役37个宽旧核，其他room保持。全部有效room像素和有效结构窗口监督，人物/附件/身体共同参与、面部冻结，没有新T3/T4。0027/0028/0145覆盖屏失败，开发RGB并非全面改善，脸前旧宽核污染基本未解除。预测多视图兼容只是筛选，不是独立几何证据；留旧雾核再加表面不足以替换病态表示。

## 同一PLY实际显示合同

最终SHA256 `a343ccf05292ce1e174c7fd63795122347a8d03bd0202a19395a9a414b691f41`，50095点，只导出参考0010一份。精确索引/来源namespace+UID唯一。121帧0→−60→+60→0连续绕看，全幅1080×1920计算，540×960/20fps编码；轴来自记录的参考头先验，yaw是viewer相对角，不是实拍头角。录像来自gsplat1.5.3，不是设备fps或PlayCanvas录像。

[冻结同资产连续绕看](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/continuity-physical-surfaces-20261001-b/body-sh-asset-check/frozen-ply/frozen-ply-orbit.mp4)

实际PlayCanvas2.22.4 Chrome SwiftShader、1080×1920、同K/C，compact/minPixelSize2，无LOD/fog/后处理，原始预乘RGBA读取；未改gamma或加灯。q守恒最大误差7.75e−7，相机矩阵误差5.45e−8。读取成功，画面一致性失败：全幅跨渲染器RGB MAE .090770，face .089696、hair .203489、cloth .020269、room .121577。旧.176的参考/资产不同，不能直接宣称受控改善。

![真实电脑双端绘制](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/continuity-physical-surfaces-20261001-b/body-sh-asset-check/renderer-comparison/source-gsplat-playcanvas.png)

HarmonyOS/真机本轮未测、未安装。历史设备成功不计为新资产通过。

## 资源、恢复和回归

沿用torch2.8.0+cu128、gsplat1.5.3、OpenCV4.12、FLAME Open，RTX5070 Laptop8151MiB，driver617.14。未改驱动/显卡模式/全局CUDA、未重启。保留[gsplat1.5.3策略合同](https://docs.gsplat.studio/versions/1.5.3/apis/strategy.html)，本轮density关闭，不以“240低于500”推断自动细化。复用Base工具见[DA3官方](https://github.com/ByteDance-Seed/Depth-Anything-3)，共享有限运动参考[Shape of Motion](https://shape-of-motion.github.io/)；没有完整复现这些方法或新复制第三方代码。

| 最终分支 | 实际更新 | 总秒数 | Torch allocated/reserved峰值MiB |
|---|---:|---:|---:|
| body static | 240 | 139.57 | 1090.78 / 1524 |
| body transition最终SH | 240 | 137.23 | 1093.08 / 1526 |
| hair | 240 | 295.85 | 750.48 / 1188 |
| room | 240 | 227.24 | 771.39 / 1204 |
| face control | 180 | 分支18.92 | 891.24 / 1006 |
| face geometry+appearance | 160+180 | 分支24.37 | 894.46 / 1006 |

face入口总151.32秒含载入/测量/基线；其他也含初始化/评估。均不含原视频准备/前序深度推理，不能称完整2—3分钟。Torch峰值不等于整机峰值；本轮无OOM，不能把8GB认作当前画质失败主因，也不能保证更大规模不会受限。

**46项回归通过**，包括实际ECC、运动SH梯度、参考恒等、邻接及既有dense/motion回归。六分支model/Adam/bindings/sampler/RNG/strategy/trainable恢复一致，非授权字段精确一致。合同通过不代替画质。

新run均在W/backend/.sources，保存实际源码/hash/config/输入合同、initial/mid/candidate-final/restored、Adam/RNG/采样/绑定/UID。旧900缺Adam仍是warm-start，不称精确resume。Git只保存代码/报告，不是私人资产独立备份；研究资产仍只在本机工作区磁盘，未上传/清理。

## 复现与证据

在W/backend，Ubuntu-22.04环境`/opt/self-reconstruction/venv/bin/python -B`，PYTHONDONTWRITEBYTECODE=1。prepared实际WSL路径为`/mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e`；W映射为`/mnt/c/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay`。每次out必须不存在，以下已存在的目录不能覆盖。

```text
build_continuity_candidates.py --prepared <prepared> --depth .sources/dense-motion-surface-20260930-h/depth --component body --budget 12000 --out .sources/continuity-physical-surfaces-20261001-b/body-surface
run_continuity_surface_repair.py --stage .sources/motion-coverage-repair-20260930-a/stage.json --surface .sources/continuity-physical-surfaces-20261001-b/body-surface --motion-mode static --out .sources/continuity-physical-surfaces-20261001-b/body-static-control
run_continuity_surface_repair.py --stage .sources/motion-coverage-repair-20260930-a/stage.json --surface .sources/continuity-physical-surfaces-20261001-b/body-surface --out .sources/continuity-physical-surfaces-20261001-b/body-transition-sh
run_native_multiview_face_repair.py --stage .sources/motion-coverage-repair-20260930-a/stage.json --depth-manifest .sources/dense-motion-surface-20260930-h/depth/manifest.json --out .sources/continuity-physical-surfaces-20261001-b/face-multiview-gray
run_continuity_surface_repair.py --stage .sources/motion-coverage-repair-20260930-a/stage.json --surface .sources/continuity-physical-surfaces-20260930-a/hair-surface --out .sources/continuity-physical-surfaces-20260930-a/hair-training
run_continuity_surface_repair.py --stage .sources/motion-coverage-repair-20260930-a/stage.json --surface .sources/continuity-physical-surfaces-20260930-a/room-surface --out .sources/continuity-physical-surfaces-20261001-b/room-training
audit_continuity_asset.py --folder .sources/continuity-physical-surfaces-20261001-b/body-transition-sh --out .sources/continuity-physical-surfaces-20261001-b/body-sh-asset-check
```

hair/room构建分别component hair/budget12000、component room/budget22000；均与body使用同prepared/depth。每次候选保存实际源码和配置。电脑绘制在W根调用`node scripts/probe-dense-surface-display.mjs`，传入`body-sh-asset-check/frozen-ply`的Windows绝对路径；然后显式指定该playcanvas-01/report.json和identity-map.json调用既有audit_motion_display_comparison.py，不能自动选历史报告。

- 汇总/状态/对照：`.sources/continuity-physical-surfaces-20261001-b/evidence-final/{summary,state-audit}.json`及PNG。
- 分支：result/config/contract.json、algorithm-source、完整checkpoint、float RGB/alpha/q。
- 冻结资产、实际浏览器和比较：同根`body-sh-asset-check/{provenance.json,frozen-ply,renderer-comparison}`。
- 首轮a、语义/SH修复前结果、首次ECC失败及首次浏览器路径失败都保留，不是新基线。

## 下一项最有价值的工作

可保留的是语义分层、统一运动/协方差/SH合同、可复用训练接口、真实多视图对称约束、完整恢复和绘制适配。资产全部拒绝：脸细节和真实头发未达标，颈整段运动/接触未解，room和跨渲染器仍失败；没有HarmonyOS、其他视频、无眼镜用户或完整joint验收。

下一项应在可靠C/F短窗里，用独立真实头/颈/上身纹理和轮廓共同求解颈接触表面与B，并验证多窗连接，**不能把短窗B=identity推广整段**。继续使用本轮事务/全幅/恢复接口，其他有效部分冻结。face还缺可靠多视图测量及深度可辨识性证据，20条稀疏轨迹/有界normal场不是完整本人测量。头发、镜框、病态room核仍需独立真实结构工作，不能靠加点/加步数/吞背景绕过。
