# SELF：连续测量、共享面部与覆盖保留衣物修缮

2026-09-30。研究代码和有限真实 GPU 计算已完成；完整人像目标仍未达到。本轮只在隔离 W 新增后端研究入口，没有改原 P、应用、签名、旧作品、USB/HDC、生产 PlayCanvas、AI、OLAY、上脸、故事或 UI。未部署、未回传、未切生产默认，E1—E5不变。

## 首要结论

1. 衣领—肩部—胸前首次建立了连续多视图深度假设，并实际训练240步，原片可见衣领和衣物纹理比旧348种子清楚。五个训练观察的固定衣物区域 RGB L1 全部下降，五个可靠世界开发视角没有触发预先定义的数值退化屏。但独立上身运动和深度还未成立，**只能保留局部研究进展，不能发布这份资产**。
2. 面部没有取得可保留的细节提升。实际运行同图像预算的外观控制及共享表面分支各240步，共享表面1591个顶点发生非零更新；开发平均略降，六个固定回归平均变差，部分视角越过退化容差。两个候选均拒绝，不能把“实际优化已接通”写成“面部已修好”。
3. 头发和眼镜没有被偷偷删掉或磨平。连续原片跟踪有提议，但独立原生像素复核和三维检查后，没有可靠头发表面支持。旧2917头发点、镜框和颈部保持上下文；这不代表它们质量通过。
4. 完整房间保留。没有再次整体替换为有孔洞的新room，也没有统一改scale/opacity。相同R0在gsplat与PlayCanvas仍差异巨大，衣物候选也未修复此问题；整体场景继续拒绝。前一轮新room绘制差小，不能移用为本轮保留旧room的成功证明。
5. “不影响有效效果”的工程保护已实测：零表面变化与旧标准GS绘制逐像素一致；衣物训练期间旧模型47项字段完全一致；原拓扑与decision-body恢复核对通过。**这只能证明本轮保护边界，不能保证未来所有视频都达到用户期待的质量。**

## 身份、固定输入与历史

W：C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay

P：D:/STUDY/College/mine/olay

开始及本轮提交前HEAD：59c7d5fb79db2d6dc36a5ca4cf441e46217eba77；分支codex/reconstruction-v3-audit-20260928。P HEAD：3dad0cd5651824cc06d9e88d61aabdd2642c0b30；原有dirty及未跟踪文件保留。没有reset/clean/stash/rebase/amend/强推，没有删历史run或worktree。P本轮未写；没有用“P不干净”覆盖或清理用户修改。

- 输入视频：capture-1790410633104.mp4，SHA256 7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf。
- Prepared：P/backend/.sources/integrated-components-v2-20260928-e；preparation.json SHA256 e67d4dce02f9874e0befe15486532f80458f8a62a23221324fcc5abefc2e5301。
- R0：W/backend/.sources/fullframe-surface-patch-20260929-b/R0-frozen.pt；SHA256 2468edc379f8b76eac97fccfbf9e9a4c775f980102b95283ee15b2dc4cee7cb8。
- 研究根：W/backend/.sources/motion-coverage-repair-20260930-a；已有失败目录全部保留，没有覆盖run-id。
- 原片已有两侧本人观察。可靠世界C的关键区间缺口和局部本人F是不同问题，不写成用户没拍到另一侧。八开发/六固定回归长期参与研发，不是最终独立盲测。
- 当前R0 38372点：room26054，head11970，body348。head细分类skin8286、hair2917、glasses标签5、neck标签762。标签5不代表物理眼镜只有5个高斯或镜架已正确，不使用旧22020room数量反推本次状态。

## 本轮新代码与技术边界

全部为新增文件，既有生产函数与入口没有修改。可复用入口通过prepared/split/tool/stage/out参数接收输入，不硬编码某人的像素坐标、衣服logo或历史帧号。

| 文件（W/backend） | 实际作用 |
|---|---|
| run_tapir_surface_observations.py、reconstruction_tracker_decode.py | 按真实时间戳选择短窗，连续解码原片，BootsTAPIR提议与正反向可见性；已知F/C不改 |
| reconstruction_native_measurements.py、audit_tapir_native_measurements.py | 原生25px真实patch独立搜索、唯一峰、仿射/反向精度复核；提议坐标不当几何真值；视频身份和角色守卫 |
| reconstruction_motion_geometry.py、run_motion_surface_geometry.py | 每物理track一个共享XYZ，受限6参数上身运动，同尺度参考恒等，固定C；保留第三观察/整track检查及数据Jacobian |
| reconstruction_motion_patches.py | 有真实track支持的有限表面提议；投影采样格均衡和重叠配额，不把中心格当alpha覆盖证明 |
| build_body_surface_hypothesis.py | 已锁定相机条件深度的训练短窗衣物表面，至少三独立观察兼容，未知/遮挡不作可靠空区；只是假设 |
| reconstruction_patch_transaction.py、run_guarded_body_recovery.py | 真实退役有限旧身体核、完整T2合成、原生衣物优化、逐视图退化检查、未通过几何时返回原身体 |
| reconstruction_photometric_surface.py、run_photometric_surface_recovery.py | 固定拓扑共享有界normal场；保持标准GS绘制，颜色/alpha/scale/quaternion恢复对照，非皮肤不动 |
| audit_motion_coverage_contracts.py、audit_guarded_body_asset.py | 零场/梯度/PLY、原状态与UID、同一资产121帧连续绕看 |
| audit_motion_display_comparison.py | 显式指定已冻结浏览器报告和精确sidecar，原生同K/C、原始RGBA比较；不自动选历史浏览器记录 |
| test_reconstruction_motion_surface.py | 15项新合同测试；另20项既有回归继续通过 |

上身只允许短窗共享刚体速度，不允许逐帧scale或无限自由平移。求解器内部共享XYZ和有限运动联合优化后，固定求得相机再做逐track稳健重投影细化，最后一观察不参与该点拟合。正则满秩不是深度真值；未通过观测支持的B不进入生产。

## 锁定工具、许可与依赖

BootsTAPIR固定代码commit 730cda1c730877cfedbe01bf87fb1cadb78a565d，source zip SHA256 5a7597de52b94671baed138c71e9f93dedeee13243a32494b3de4b9b63312907。官方bootstapir_checkpoint_v2.pt SHA256 8493c7a69e02c85b9382fbb3c7b8b539b36bc08ede744b9e99feb739a0129f4b。代码与官方链接权重按[官方许可说明](https://github.com/google-deepmind/tapnet#license-and-disclaimer)记录Apache-2.0，原许可保留。工具放在W/backend/.sources/tools/tapir-730cda1，独立venv只补dm-tree0.1.9、einshape1.0；未升级原锁定训练环境。

沿用既有DA3-BASE，未重新安装或换GS生成器：代码3d835ec1a5802d64a8b8b15f817a1ab54809bfe4，模型revision f4a6c9b3c95e41c82048423d3493a81ec3fa810e，权重SHA256 e01067dc1659613083d9145a9a2547ccdbe6ccbbf83c4fe7b3e8a4e2bdae78b5。Base许可与接口见[官方项目](https://github.com/ByteDance-Seed/Depth-Anything-3)、[官方API](https://github.com/ByteDance-Seed/Depth-Anything-3/blob/main/docs/API.md)。预测深度及多个预测相互兼容不等于独立测量。

训练环境torch2.8.0+cu128、gsplat1.5.3、OpenCV4.12、NumPy2.2.6、SciPy1.15.3；实际RTX5070 Laptop8151MiB。未修改CUDA、驱动或显卡模式，未重启或停止用户其他GPU进程。

## 连续测量与实际阻塞

预先限定一个head窗和一个body窗，使用训练时间段，开发/固定回归不取色、不决定新增点。最初512×384连续12Hz提议已有原片桥接；把网络FB的原生2px门槛与独立原生定位分开，避免把粗网络坐标精度当最终几何精度。最终同一头窗0107—0113采用512×512，316个真实角点提议，直接筛选17条track；原生独立定位只留下face1、hair3、glasses2共6条。新增身份守卫重放得到相同6条，不重推模型。

body独立原生定位17条仅在下方左/中，没有上方衣领/肩部稳定track；三维13条可初始化但0条通过，motionAccepted=false。头部17条直接提议有15条可三角化，最终仅face1、glasses1通过，hair0；整track第三观察P90为4.28175px。不能由这些点构造真实发际线厚度、镜腿或整个上身运动。

连续帧有h264 mmco等解码告警，实际训练锚帧与准备原图差异受控（MAE<=0.005），锚像素使用原准备图；中间帧仅供提议，没有伪造F/C或用于新颜色训练。有限窗口失败不证明整段原片没有可用结构，也不要求用户立即重拍。

## 共享面部：真实训练，但拒绝

保留正确head-local-sh1、全幅后切ROI和原标准GS路径。共享normal位移上限为原生像素尺度3倍，固定K/F/身份/表达/尺度/拓扑。同步中心与局部方向一次旋转，保留原scale轴长；**这里只做方向传输，没有宣称完整仿射应变协方差**。非皮肤头发/镜框/颈部保持原样。

两分支均240次原生全幅图像反传，同采样序列、预算和损失；控制分支240次外观更新，共享分支26次几何+214次外观，不能声称两者外观Adam步数相同。几何阶段外观冻结，后段有限恢复。没有新的density或父点分裂，也没有退回已知错误SH方向。

| 固定face区域L1、包含缺失像素 | 恢复R0 | 外观控制 | 共享表面 |
|---|---:|---:|---:|
| 8开发 | 0.031100130 | 0.030959214 | 0.031022693 |
| 6固定回归 | 0.041770071 | 0.042189215 | 0.042450927 |

共享更新1591顶点，最大normal offset 0.0000344947；0035/0055/0058/0059face及0145glasses越过逐视图容差。无可见、稳定的源片细节恢复，不因均值略降放行。固定F的光度几何仍可能补偿观察误差，这不是已测细节真值。

[0035原片/共享表面优化后](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/motion-coverage-repair-20260930-a/face-training-standard-gs/shared-surface/final-images/frame_0035.png-head.png)。相同用途的R0和外观控制图在各final-images/R0-images中，不把黑底头部样件当完整作品。

较早两个covariance实验发现研究适配器重复方向旋转和零场数值不等价，失败证据保留；最终改回原标准GS表示，而非改生产渲染器。最终零场RGB/alpha/q误差均0，非皮肤中心/协方差exact，1772顶点梯度非零且有限。最终同一PLY往返平均4.71e-8、最大0.000908732，与旧R0最大完全相同；预先0.0003绝对屏**仍失败**，只可称无新增往返退化。allPassed=false，没有偷偷放宽成完全通过。

## 衣物：可见进展，不把静态假设当成熟运动几何

复用之前已生成的camera-conditioned深度，在泛化的短窗选择规则下选择0005/0006/0010/0012/0013，1.798—5.228秒。所有都是训练观察。43142初提议，39496去重后有限12000预算；要求>=3不同图像深度兼容、free反证<=1，真实原片取色。没有生成纹理、没按logo硬编码。

父点仅在每个训练观察的实际投影半径范围完全落入可靠cloth mask时提议退役，348旧身体核中86退役、262保留。每一次T2仍同时绘制完整头部（含旧颈/发/镜框）、房间、保留身体和新表面。旧47模型字段逐项不变。240步实际Adam更新SH/alpha/scale/quaternion，offset冻结；新scale仅在原值1.25倍有界范围内，不改全局scale或opacity。无身体新density，12000不是未来终态上限。

| 训练观察、固定衣物ROI | 旧身体L1 | 新初值L1 | 240步后L1 | 旧q_cloth | 训练后q_cloth |
|---|---:|---:|---:|---:|---:|
| 0005 | .131480 | .113564 | .098899 | .540492 | .729456 |
| 0006 | .130683 | .101000 | .083063 | .558708 | .760316 |
| 0010 | .156425 | .078988 | .047266 | .649465 | .887283 |
| 0012 | .167906 | .088634 | .061080 | .692193 | .928351 |
| 0013 | .184695 | .107602 | .082278 | .712988 | .946891 |

这是原生固定ROI、包括缺失像素；不是只在高alpha像素算误差。五训练+五有可信C的开发世界视角逐区域alpha/RGB/结构/脸前cloth贡献屏通过，alpha<0.8只是代理，不宣称“无几何”。六固定回归无可靠C，不偷偷补T2。静态短窗假设geometrySupported=false，所以transactionAccepted=false，不因画面或数字较好绕过几何与发布要求。

[0010原片/本次完整冻结场景合成](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/motion-coverage-repair-20260930-a/body-training/final-images/frame_0010.png.jpg)。衣领、肩部和胸前不再只有模糊种子；头发/脸前雾片仍明显，不掩盖。

真实来源UID、点数组顺序和旧存活字段核对通过。candidate50286点（新增12000、退役86），唯一参考0111的PLY SHA256 51ea18953b365ac68808f6df38782290024dd0577e479643c1f260b382c539bb。原R0 PLY hash9fd631a133065c4e02fced9f650914abacd0a716d63f33afe3eb7df49c2cc094、38372点。

当次trainer最早的restored.pt是恢复trial初始化，**不等于原拓扑**。交付代码已区分original-context、restored-trial-initial、restored-original；后续独立audit从当次47个冻结字段和原body做原状态恢复证明，decision-body确实等于原body。本次没有为名称修正重复训练240步，训练冻结源码与交付源码有差异，见receipts。旧R0无历史Adam，只能warm-start；新的trial Adam、RNG、sampler、初始化/中期/终态与来源均保存，不假称旧训练精确resume。

## 同一PLY实际电脑绘制与连续绕看

gsplat1.5.3固定参考资产连续121帧，原生1080×1920渲染、540×960/20fps编码。旋转−60至+60是viewer相对角，不等于测得的人脸真实支持范围；不按角度换模型。
[唯一资产连续绕看](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/motion-coverage-repair-20260930-a/body-asset-audit-b/draw/frozen-ply-orbit.mp4)。

PlayCanvas2.22.4/Chrome SwiftShader真实加载同一候选及R0，各原生1080×1920、K/C一致，camera矩阵差1.84e-7，maxPixelRatio1、无LOD/fog/后处理，compact、minPixelSize2、AA=false、gamma=1、exposure1。读取GL预乘RGBA8仅翻转行序，不重复乘alpha、不调gamma/对比度。实际sidecar和asset hash匹配，0加载错误。

| 两绘制器原始RGB差 | R0 | 衣物候选 |
|---|---:|---:|
| 全幅MAE | .17597967 | .16293910 |
| face（core+boundary） | .17872484 | .17861106 |
| hair | .33060867 | .33071804 |
| cloth | .12503061 | .07815909 |
| room | .19194755 | .19190624 |

衣物在两边都能辨认，但整体绘制合同**没有对齐**。同R0全幅数值与前一轮haze审计一致；当前face mask包含boundary，不能直接与旧仅core数值相减。较低的PlayCanvas脸误差不证明模型正确，较低的gsplat房间误差也不放行脸前灰雾。保留旧room也保留其病态宽核，先前源码已发现半径限制/尾部/排序/工作缓冲差异；本轮未再隔离每个因素的责任比例，更没宣称fog是原因。

[原片/候选gsplat/候选PC/R0gsplat/R0PC](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/motion-coverage-repair-20260930-a/display-comparison/contract-checked/source-gsplat-playcanvas.png)。原生GPU重放之前float64元数据和float32绘制K/C的严格array_equal触发拒绝，已按真实float32合同校验，实际差最多4.64e-8；没有放宽位姿或改相机。

本轮没有HarmonyOS模拟器/真机测试、生产编辑测试或设备fps。SwiftShader录像/加载不冒充平板验收。

## 资源、失败证据与保留结论

| 实际阶段 | 已记录耗时 | 峰值allocated / reserved MiB |
|---|---:|---:|
| 连续512×384 TAPIR | 67.13s | 2600.3 / 3716 |
| 同头窗512×512 TAPIR | 36.25s | 3348.8 / 4242 |
| 最终面部控制240步及该分支评价 | 27.17s | 891.59 / 986.00 |
| 最终共享表面240步及评价 | 24.70s | 895.76 / 988.00 |
| 最终面部两分支完整run | 79.46s | 非GPU总占用 |
| 衣物240步完整run | 88.90s | 758.69 / 1202 |
| 衣物训练起点至评价/导出统计 | 57.11s | 该字段不是纯Adam循环时间 |
| gsplat连续绕看 | 2.36s | 非设备fps |

以上均不含完整视频准备，衣物还复用了之前深度；不能相加冒充完整2—3分钟链路。过程没有OOM，不证明8GB对未来全流程永远无瓶颈。TAPIR第一次独立分配出现一次NVML内部assert，Windows最小设备检查与随后CUDA计算正常，新独立run重试成功；没有改驱动/重启/显卡模式，不能写成必须扩显存。

失败目录measurements（缺einshape）、body-depth-proposal（参数遗漏）、早期covariance及展示适配失败全部保留；修正只发生在新的研究代码与目录，没有覆盖旧资产。除最终standard-GS/guarded记录外，不把失败分支的数字拼成新的质量基线。

- 通过：35CPU合同回归、16新文件编译；真实推理/反传/Adam；零场精确绘制；非皮肤保护；原47字段与body返回；UID/来源、实际电脑加载、固定资产连续绕看。
- 有局部进展：短窗衣物外观与覆盖优于旧身体表示，保留研究候选和代码；不是独立运动/完整作品通过。
- 失败：面部跨回归稳定改善、头发表面/镜架结构、完整房间与脸前污染、gsplat/PlayCanvas一致性、严格PLY最大像素差屏、整体E1—E5发布。
- 未验证/未实施：稳定上身B、完整肩颈接触运动、新的room表面替换/联合训练、最终独立审计、鸿蒙显示与编辑、新视频泛化画质；旧故事与上脸未改。

## 复现与下一个最小动作

本轮源码snapshot/config/contract/init/mid/final/Adam/RNG/sampler/绑定/源点在私有.sources。delivery-verification、delivery-final-b及本文verification.json记录交付源码hash和运行源码hash；最后仅清理本轮四个文件的尾部空行，无数值改动，Git不备份这些私人照片、模型与完整检查点；没有独立离线备份则不能宣称灾难可恢复。研究资产未上传。

以下在W/backend、WSL中使用同一已锁定环境，每次--out必须新目录。Linux的W/P分别为/mnt/c/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay、/mnt/d/STUDY/College/mine/olay。

```text
# 独立tapir工具venv
run_tapir_surface_observations.py --prepared P/backend/.sources/integrated-components-v2-20260928-e --split W/backend/.sources/fullframe-surface-patch-20260929-b/observations.json --tool W/backend/.sources/tools/tapir-730cda1 --parts head body --out 新目录/measurements
# 原venv，原生测量及几何
 audit_tapir_native_measurements.py --prepared 同上 --proposals 新目录/measurements --out 新目录/native
 run_motion_surface_geometry.py --prepared 同上 --measurements 新目录/native --out 新目录/geometry
# 不更改旧深度，衣物假设及240步有限恢复
 build_body_surface_hypothesis.py --prepared 同上 --depth W/backend/.sources/dense-motion-surface-20260930-h/depth --out 新目录/body-surface
 run_guarded_body_recovery.py --stage W/backend/.sources/motion-coverage-repair-20260930-a/stage.json --surface 新目录/body-surface --out 新目录/body-training
# 同预算面部对照及GPU合同
 run_photometric_surface_recovery.py --stage 同上 --out 新目录/face-training
 audit_motion_coverage_contracts.py --stage 同上 --out 新目录/contracts
# 当前实际候选的原状态证明、PLY/浏览器
 audit_guarded_body_asset.py --folder 当前body-training --out 新目录/asset-audit
# Windows项目Node（已有脚本，未修改）
 node scripts/probe-dense-surface-display.mjs 新目录/asset-audit/draw
# 显式指定sidecar映射JSON，冻结capture，不自动选择其他历史记录
 audit_motion_display_comparison.py --prepared 同上 --browser-report 指定playcanvas-XX/report.json --identity-map 精确资产标签到sidecar路径JSON --out 新目录/display-comparison
 python -B -m unittest test_reconstruction_motion_surface test_reconstruction_dense_contract test_reconstruction_dense_surfaces -v
```

下一项首要动作是**先解决可观测几何，再继续外观**：在另一组由训练时间/清晰度/视差规则选出的有限短窗中，把camera-conditioned深度作为带不确定性的初值，与独立原生测量共同约束共享表面；先检查局部F残差、第三观察与真实厚度，再开放对应表面。当前只有一条独立face track和零条可靠hair track，不够用“再训练更久”恢复头发与细节。这个动作需同时保留未知和遮挡边界，不能把不稳定测量硬变真值。

背景独立缺口保持明确：物理表面/有限覆盖替换要同时保持有效环境和消除宽核脸前污染，不能删除room、恢复巨大雾片或依赖查看器半径裁剪。衣物已有真实外观入口，应等可靠上身B后复用，不再只保348点，也不把headF借给衣服。未取得可信几何时，不把此研究候选回传替换；本轮不宣称成熟全链路已完成。

本轮代码提交：f87bc1c5f7b37ffacccee6cb64b472f26e2552bb（parent 59c7d5fb79db2d6dc36a5ca4cf441e46217eba77），只包含上述16个新文件。验证记录见verification.json和test-results.txt。证据另作独立提交，不混入原有未跟踪资料。
