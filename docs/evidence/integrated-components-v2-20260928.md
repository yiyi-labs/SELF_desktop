# SELF 五组件共享重建 v2：实际实施、画面与失败记录

日期：2026-09-28。落实本轮完整粘贴任务；沿用原 E1—E5。**代码与三轮 1800 步实际训练已完成，但画质和现有查看器编辑兼容性仍失败。没有发布、回传平板或替换旧作品。**本记录不是“新版模型已合格”的声明。

## 优先回答 A—E

- **A，为什么仍糊、仍不够立体：**皮肤在参考视角的原生像素投影半径 P50 仍为 28px、P90 为 36px；鼻唇和镜框需要的窄边缘仍由宽基函数解释。头发初始只有 267 个通过三视图检查的种子，眼镜只有 16 个；它们独立于皮肤后依然不足以形成完整表面和连续镜框。世界相机仍是暂可信研究估计，单一尺度连接的中心残差 P50/P90 为 13.1/23.1mm，不能把先验位置当测量真值。小幅固定资产绕看仍有皮肤斑驳、发侧团块和颈肩模糊。这些是本机数值及实际画面支持的原因；没有证明一种因素能解释全部失败，也没有排除两渲染器共有的中心排序近似。
- **B，真正改善了什么：**五组件、保守面部核心、静态表面支撑和双尺度共同优化后，V2B 的正面同源脸区 L1 为 0.03035，Shared 为 0.04122；原片对照能看到旧蓝白前景污染减轻。它是整个流水线候选的改善，非单变量因果实验。世界相机、训练视角与表示均不同，不能全部归因于 ROI。鼻翼/唇边/镜框尚未同时形成可见细节提升。
- **C，哪些数字好看仍失败：**V2B 正面核心空洞比例仅 0.027%，但镜框线条仍缺失、头发仍软。V2D 房间尾部 footprint 收敛了一些，却让房间覆盖下降到 0.932，并且 12 次分裂全部被覆盖检查撤回。V2E 保持覆盖的分裂实际生效，唇部 patch L1 从 D 的 0.02051 到 0.01804，但眼镜 patch 误差上升、肉眼边缘仍软，不能放行。
- **D，能否开始独立鸿蒙新资产测试：不能。**研究资产在电脑可加载、连续转动，但质量未达到要求；现有产品加载方式还破坏了面部点前缀。保持点顺序的隔离诊断通过不等于产品或真机通过。
- **E，最小阻塞：**独立镜框/发际线三维支撑仍太稀，宽面部基函数与位置残差仍在替代细节；颈肩衣物运动只有简化近似。另有明确的查看器点顺序合同问题。末段补充 CUDA 审计又受电脑独显不在当前设备中的运行环境问题阻塞。无需重新拍摄；本轮持续复用同一原片。

完整机读数值、拓扑事件、末次资源与冻结文件身份见 [JSON 记录](D:/STUDY/College/mine/olay/docs/evidence/integrated-components-v2-20260928.json)。

## 输入和冻结范围

原片为 `capture-1790410633104.mp4`，实际保存在 `backend/.sources/quality-geometry-20260926-temp/capture.mp4`，SHA-256 `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。65.393s，1963 源帧，160 张已关联的正向原生 1080×1920 图像。没有重新拍摄、向第三方发送或修改原片。

FLAME Open 仍是主先验，模型在项目私有资源目录 `backend/.sources/third_party/flame2023_open/flame2023_Open.pkl`，SHA-256 `e75a0990728ba038c7da2a420ae4396f7ddd7781366c13026066c5b24f127623`。保留 CC BY 4.0 的 Open 模型路线及既有许可记录，没有使用普通版模型、平均脸纹理或生成皮肤。输入 head-local-sh1 900 步参数 SHA-256 `308da67a299dc98855fa4d3403197130811ec87d96dcb7ad967eee92950d9e46`；不退回已知错误方向色语义。

依赖保持 gsplat 1.5.3、PyTorch 2.8.0+cu128、PyCOLMAP 4.2.0、OpenCV 4.12.0、MediaPipe 1.0.1、PlayCanvas 2.22.4。核对了安装源码和 [gsplat 1.5.3 策略接口](https://docs.gsplat.studio/versions/1.5.3/apis/strategy.html)、[同版本光栅化接口](https://docs.gsplat.studio/versions/1.5.3/apis/rasterization.html)。新增策略使用实际安装版本的参数/Adam 状态更新原语，没有盲追 main。RootSIFT、LSD 使用已安装 OpenCV 能力；没有新增未知许可权重。

根目录和 backend 内未找到 AGENTS.md。当前工程已有大量之前的未提交修改；本轮没有重置、整仓重写、提交或覆盖它们。没有改鸿蒙应用、签名、旧作品、USB/HDC、产品 PlayCanvas 入口、上脸和故事。生产 `reconstruction_train_joint.py` 默认分支保持不变，新 v2 只有手工隔离入口。JSON 中保存当前冻结文件 SHA，明确不是伪造的修改前后哈希对照。产品 bundle SHA 为 `d633fb2718ef5ed5087aabbd27356058323d2c71e9dda69c95ee32f87718f5d3`。

## 实际工程修改

| 文件 | 本轮实际作用 |
| --- | --- |
| `backend/reconstruction_face.py` | 新增 face_core、face_boundary、hair_visible、glasses_visible、neck_cloth_visible、room_visible、unknown_or_occluded 和置信产物。核心区收缩，发际/耳周保留过渡；眼区线条为候选，不当作已核验镜框真值。旧入口不调用新规则。 |
| `backend/reconstruction_observations.py`、`reconstruction_pose.py` | 按图像名关联原帧、七类 mask、置信文件、K、C/F 和用途。固定本人形状/表情，按实际径向内参重拟合有限 F；没有修改世界相机，也没有给缺失 C 补单位矩阵。 |
| `backend/reconstruction_scene.py` | 新增静态轨迹与局部三角表面补点；最长边≤80px、深度跨度<6%、表面朝向与≥3视图观测共同约束。补点在真实三角内，不用 360px 四邻外插，不补无依据房间体积。 |
| `backend/reconstruction_components_v2.py` | Open 本人局部几何、同 K 原生去畸变、独立头发/镜框三视图 DLT、真实衣物轨迹、支持与来源记录。新增邻帧独立求姿，不能把近邻先验等同真实表情或插值位姿。 |
| `backend/reconstruction_joint_visibility.py` | 同一次光栅化包含五组，输出 RGB、alpha、各组 q、各组累计/期望深度；SH 仍按正确头局部坐标旋转。 |
| `backend/reconstruction_shared_v2.py`、`run_integrated_shared_v2.py` | 隔离真实 Adam 训练、全图半分辨率与原生语义 ROI、基于深度的核心污染门控、部件 footprint/残差/支持驱动真实父点替换、覆盖回滚。没有隐藏任何另一组。 |
| `backend/audit_integrated_components_v2.py`、`audit_components_v2_detail.py`、`audit_v2_fixed_playcanvas.py` | 同源像素比较、固定资产往返、部件与来源审计、实际浏览器相机比较；CPU 来源审计和 GPU 画质审计明确分开。 |
| `scripts/probe-personal-continuous-orbit.mjs`、`probe-research-edit-contract.mjs`、`probe-research-point-order.mjs` | 同一冻结 PLY 的小幅实际绕看、编辑/还原/重放、实际加载顺序检查；诊断 loader 变体不写产品 bundle。 |

这些规则依据部件、相机、残差与支持工作，不包含针对当前片段的手工 RGB 补丁、逐帧造位姿、磨皮或特定五官增亮。泛化到其他拍摄尚未验证。

## 观察、表面和五部件

复用既有 E1 全人物排除后提特征的静态地图，没有重跑相同相机救援，也没有复用不同特征的索引。该地图仍有关键中段失败，最终可信世界姿态数为 0。用于本轮联合研究的交集为 59 个训练视角、5 个开发视角；无可靠世界连接的局部面部观测不进房间联合训练。原先 14/8 基线中有世界连接缺失的帧明确排除，没有把 5 个开发视角称为新的盲测。原片已拍到两侧，缺的是可信连接。

相机估计为 SIMPLE_RADIAL，f=1189.07588px、cx=540、cy=960、k1=0.01772216。先用原 K/畸变估 F，再将 RGB、mask、关键点一致去畸变到同 K；训练不在 mask 外涂黑。人物到世界只使用一份研究共享尺度 13.35442，无逐帧 scale。这不是独立标定，静止中心拟合只用于尺度连接，不把真实人物移动抹平。

静态初始化有 2000 个实测轨迹点、20020 个三角内多视图表面样本；各自来源类别和原始点 ID 保留。弱支撑补点插入数为 0。部件初始化为：皮肤5486、头发267、眼镜16、颈肩衣物1762、房间22020，总29551。原先2917个粗发壳点被排除，不能据此说真实发量已完整重建。

皮肤6033最终点全部具有稳定三角绑定。头发/眼镜使用头局部独立空间种子，不贴 FLAME 表面；三视图循环、≤2.2px 重投影、≥2° 射线角和可见 mask 支撑后才入选。829 条二维眼区线段候选仅被计数，**尚未建立可靠镜圈/镜腿/鼻托的三维线段网络**；这是未完成项，不用色斑代替。衣物从新的静态研究相机轨迹三角化得到348种子；旧地图对齐路径0点通过，未悄悄补回旧衣物点。最终颈肩衣物含1414绑定点与381独立衣物点，运动仍是颈部绑定加受限平移混合，完整肩部旋转/衣领遮挡未通过。

所有五组在全图与 ROI 都同时绘制。ROI 为 face/hair/nose/lips/eyes_glasses，按语义及残差并带使用衰减选取；原生 ROI 权重1.8。face_core 污染根据部件贡献和 FLAME 先验深度前方12mm门限加权，边界/unknown不做硬删除。该深度是先验而非观测真值，不能把门控分数称为准确遮挡测量。

## 独立 run-id 和真实训练结果

所有目录在忽略的 `backend/.sources/`，不是生产任务目录。

| run-id 后缀 | 实际结果 | 训练/审计进程内耗时 | Torch allocated / reserved峰值 | 采样设备 used 峰值 |
| --- | --- | ---: | ---: | ---: |
| `integrated-components-v2-20260928-a` | 初始小样；支持/法线坐标问题发现后主动停止，无资产 | 未完成，不报完整时长 | 不作验收 | 不作验收 |
| `…-b` | 1800 Adam步，29551→35387点；大子点覆盖尚能维持，但视觉失败 | 127.40s | 976.5 / 1158MiB | 1555MiB |
| `…-c` | 第241步拓扑修改触发GPU索引dtype错误，无资产；已修复并做GPU回归 | 失败，不报完整训练时长 | 不作验收 | 1483MiB |
| `…-d` | 1800步，12次提议增密均因孔洞/房间覆盖下降撤回，29551点 | 144.28s | 976.8 / 1146MiB | 1543MiB |
| `…-e` | 1800步，835父点实际被1670子点替换，30386点；视觉仍失败 | 179.65s | 977.7 / 1176MiB | 1573MiB |

计时包含训练初始化、图像/网格准备与本进程最终审计，不是完整用户任务。wrapper B/D/E 为162.72/167.55/200.61s。160帧解析分割首次另花约125.55s，B准备122.01s；E复用缓存，且训练早段存在额外审计进程，不能作为严格速度A/B。解码、E1、传输及全部冷启动未计入，**未证明完整任务2—3分钟达标**。设备 used 含桌面/其他进程，区别于 Torch 峰值。已完成训练没有 OOM，8GB不是本轮画质瓶颈的证据；不能由此证明未来最大输入也不会超显存。

E 的源参数均实际改变：means、scale、rotation、alpha、SH 的平均变化和真实曲线保存在 JSON 与私有 `research-audit.json`。不是只前向取色。

## 父点替换与覆盖诊断

D 暴露的问题是同时缩三轴并将峰值 alpha 按重合两点折半，缩小后投影覆盖明显减少；如后期提议会使参考帧核心空洞由0.14%增至1.34%、房间覆盖0.897降至0.857，覆盖检查真实撤回了参数、Adam和绑定，未导出坏拓扑。

E沿最大实际协方差轴分裂：该轴scale×0.8，中心沿该轴移至±0.6倍父scale，其余轴保持；束缚皮肤重新求附近三角和重心绑定。光学密度按两子点投影体积近似分配，并将单次配额收小。它在未投影/未合成的模型中保留轴向二阶矩，但**不是精确透明合成等价式**，因此仍以三张训练视角的实际覆盖检查决定接受。没有改为父子同时保留、全图降透明或删可见大点。

| 部件 | 初始→E最终 | 实际父点替换数 | 新后代支持视角 min/median/max | 正面原生 footprint半径 P50/P90/P99 |
| --- | --- | ---: | --- | --- |
| 房间 | 22020→22138 | 118 | 3/18/59 | 10/22/520.5px |
| 皮肤 | 5486→6033 | 547 | 3/59/59 | 28/36/50px |
| 头发 | 267→396 | 129 | 3/30.5/59 | 54/72/92px |
| 眼镜 | 16→24 | 8 | 3/10/21 | 29/38/44.2px |
| 颈肩衣物 | 1762→1795 | 33 | 4/54.5/59 | 30/156.6/498.3px |

clone/duplicate=0、prune=0。每次父点替换日志记录部件数、覆盖前后、总点数；字段长度/资产哈希、绑定、部件、置信、来源索引和Adam真实参数一致。后代mask支持≥3只是观察一致性，非独立三维置信真值。宽footprint尾部仍明显失败，没有以“点数变多”放行。

E正面核心：room q=0.00708、cloth q=0.00230、hair q=0.000209、glasses q=0.01008；核心空洞0.0759%，可见房间alpha=0.98683，房间RGB L1=0.06298。q守恒最大误差7.15e-7。hair/glasses的上述值为原始核心贡献，**不自动等于越界污染**。新增可见部件覆盖/越界深度代理的补充GPU审计尚受独显问题阻塞；没有伪造这些数值。

## 同源画面：平均数没有放行权

下表为同去畸变像素、同固定face_core+boundary、包含缺失像素的原生脸区RGB L1。Base/Shared使用各自明示旧相机/运动，新候选用明示研究C/F；这是整流水线比较。B与D同冻结准备，仍不能称只有一变量不同。原片与各候选横向对照在各run `source-comparison/`；列顺序是原片、Base、Shared、新候选。

| 文件名（不是COLMAP ID） | Base | Shared | V2B | V2D |
| --- | ---: | ---: | ---: | ---: |
| frame_0111，参考训练正面 | .06896 | .04122 | .03035 | .03188 |
| frame_0015，开发 | .14868 | .01997 | .02819 | .02789 |
| frame_0035，开发侧转 | .17336 | .02136 | .02278 | .02552 |
| frame_0115，开发近参考 | .07470 | .03233 | .03021 | .03141 |
| frame_0130，开发 | .17648 | .02364 | .03474 | .03206 |
| frame_0145，开发 | .19324 | .02336 | .02647 | .02600 |

V2B只在参考和115稳定优于Shared，其余开发视角反而更差；不能用正面一张宣布完成。E已有本次训练同步的固定核心误差及全部原生patch图，但加入Base/Shared/B/D的统一新表GPU调用未完成，不能把JPEG估值填入这张表。

E与D使用同协议核心指标：15帧 .02296→.02141、35帧 .01923→.01914、115帧 .02300→.02272、130帧 .02715→.02770、145帧 .01915→.01850。参考原生patch的鼻/唇/眼镜误差 D→E 为 .03193→.03003、.02051→.01804、.02969→.03084。改善混合，镜框没有通过。

E鼻patch输出梯度均值0.00313，原片0.00737；眼镜patch0.00234，原片0.01082。低边缘L1也可能来自输出变平，不能解释为细节恢复。所有视角已参与方案选择，均是开发验证；没有独立最终盲测。

以下实际图左为原片，右为E优化后；没有锐化、刷黑或生成细节：

![同源唇部对照，仍然柔化](D:/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e/final-audit/frame_0111.png-lips.jpg)

![头发与眼镜对照，体积和线条仍失败](D:/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e/final-audit/frame_0111.png-hair.jpg)

## 一份固定PLY、实际PlayCanvas与编辑合同

B / D / E 的 PLY SHA-256依次为：

- `3e21bb5566b3b8f476a08f966b76441c3680454dd6a7c10d57edbfc52b2db77e`
- `ae3a896995186a84d90565c500ea29ef2ef70aff923de450015fca672e9ce66a`
- `1b2fe713df73ab87ce86458bf2b689c81eba1195f1004a6fa67e556841a9ccb3`

每份资产只导出一个参考状态。参考 `frame_0111.png` 对应原片PTS45.324422s。PlayCanvas实际同一会话绕看约±11.8°控制yaw、约±8°pitch、回正；前后PLY哈希相同，没有根据视角换模型。yaw是查看器控制量，不冒充真实采集角。

[E 连续绕看视频](D:/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e/continuous-orbit-small/private-fixed-asset-continuous-orbit.webm) SHA-256 `0856fadc723ff4ac3cc80425f6ec05ec067571c80068c751d8fa5dde8a855ae3`。八个实际相机、PNG与UI截图在同目录 audit；浏览器page error=0。SwiftShader录制的24fps不是设备实际帧率，也不是鸿蒙真机证据。

![E固定资产小幅侧转实际画面：皮肤、发侧和镜框尚失败](D:/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e/continuous-orbit-small/private-small-yaw-negative-about-12-canvas.png)

B和D在同一个精确源相机下，训练→导出PLY→gsplat的AA均值误差4.38e-8/3.48e-8，说明已修正的head-local-sh1和精确SH导出没有再次丢失。B实际PlayCanvas相机与gsplat对照的可见皮肤误差约0.0074—0.0102；不能称像素完全一致或排除共同排序问题。D/E最后的补充精确跨渲染器调用因GPU不可用未完成。原有已通过的基础格式往返未重写。

**新增重要合同失败：**安装的PlayCanvas PLY解析器 `asset.data.reorder ?? true` 默认执行Morton排序，而产品仍以`editableSplats`前缀判断面部。E原6033皮肤点在加载后的前6033位置中实际为0，全部移到了范围外；真实圈选返回“立体细节较少”。诊断中仅令loader保持原顺序，30386点XYZ逐索引完全一致，6033皮肤点全部留在前缀。重复位置10处以XYZ哈希及逐索引比较核对，未误当漏点。

**旧报告口径纠正：**前次Shared编辑测试的“selectedEnvironmentCount=0”只按错误加载后的前缀计数，并未按原PLY语义证明未选房间。本次同一Shared加载顺序诊断发现13970个原人物点已移出前缀；此前编辑API可以工作，不等于人物/环境隔离合同真正通过。没有修改或删除旧报告，用本条追加纠正。

E的**隔离loader诊断变体**圈选188个皮肤点、0个非皮肤点，数字rose预览画面有变化，恢复/重放PNG哈希分别与原图/修改图完全相同，浏览器错误0。D相同变体143点也通过。产品原loader两份均失败。该测试固定注入数字preset，用于编辑数据回归，不是DeepSeek会话、品牌标定或OLAY真实效果验证。没有改产品加载器；后续最小修正需在现有入口保留索引或提供稳定源ID映射，并单列真机回归。

## 回归、运行环境与未验证项

新增3项组件合同测试在独显可用时实际通过，包含真实CUDA五组来源/深度守恒、所有组关键反向梯度、absgrad、精确SH旋转及GPU父点/绑定/Adam同步。末次13项Python回归为11通过、2因CUDA不可用明确跳过；不把skip称通过。查看器8项单元回归通过；Python编译、Node语法和diff空白检查通过。真实产品loader的集成圈选仍失败，不能用单元测试遮盖。

完成E训练后，Windows将RTX5070标为Unknown、IsPresent=false；当前视频控制器只报告Intel，WSL `torch.cuda.is_available()`为false，后续GPU调用报“Found no NVIDIA driver”。这是本轮末次实际运行条件，**没有确定为何独显离线，也没有归因为8GB不足**。已询问用户恢复独显；没有安装/卸载驱动或自行重启电脑。确认无活动任务后，用同一入口和原环境刷新闲置worker，清除缓存ready=true的误导状态，当前心跳ready=false、理由“RTX 5070 CUDA unavailable”；任务文件未修改。

| 原门禁 | 本轮结果 |
| --- | --- |
| E1 | 继续失败；未升级160注册数，64个交集只为暂可信研究C，关键中段没有新世界证据。 |
| E2 | 五部件与独立三视图种子可运行；真实发量、镜框连续、颈肩衣领运动失败。 |
| E3 | 全场景每次前向、来源/深度/梯度与真实优化通过子能力；整体场景质量与小幅绕看仍失败。 |
| E4 | 原生ROI、部件absgrad、实际父点替换、来源绑定同步通过子能力；面部细节/footprint目标失败。 |
| E5 | 同资产电脑PlayCanvas连续绕看可运行；产品点顺序/编辑合同失败，诊断变体通过；新资产鸿蒙/真机未运行。 |

## 精确复现与下一步边界

E训练当时源码已按原SHA恢复并保存在私有 `algorithm-snapshot/`，入口算法SHA `20bd5c6abea043e634ac70dde8fb9dd926d68dd1ef9386d4b502f894aae10a90`；当前主文件后来仅增加补充审计字段。冻结prepared输入仍留在B，E引用同一mask/rectified缓存。新运行应复制准备文件到新run-id；输出脚本拒绝覆盖已有PLY，不重新训练E目录。

```text
# WSL backend工作目录，锁定已有环境；使用新的独立输出目录
python run_integrated_shared_v2.py .sources/quality-geometry-20260926-temp <new-run> --fit-root .sources/quality-geometry-20260926-temp/flame_open_e2_20260927 --appearance .sources/quality-geometry-20260926-temp/flame_open_e2_20260927/private-optimized-subset-900-footprint-1.00-sh1-head-local-20260927/private-optimized-parameters.npz --static-map .sources/quality-geometry-20260926-temp/static_sfm_probe_stride1/targeted_global/sparse/0 --trust .sources/quality-geometry-20260926-temp/static_sfm_probe_stride1/trusted_views.audit.json --enrich-local-neighbours --masks-from .sources/integrated-components-v2-20260928-a --cloth-multiview --steps 1800 --antialiased

# 已有资产只读审计；E统一对照和补充GPU项仍需恢复显卡后完成
python audit_integrated_components_v2.py .sources/integrated-components-v2-20260928-e --asset Base=.sources/quality-geometry-20260926-temp/portrait.gaussian.ply --asset Shared=.sources/integrated-shared-joint-3000-20260927-a/portrait.gaussian.ply --parametric-baseline V2B=.sources/integrated-components-v2-20260928-b --parametric-baseline V2D=.sources/integrated-components-v2-20260928-d
python audit_components_v2_detail.py .sources/integrated-components-v2-20260928-e
python audit_v2_fixed_playcanvas.py .sources/integrated-components-v2-20260928-e

# 工程根目录：真实现有产品loader失败与隔离诊断成功分别输出
node scripts/probe-personal-continuous-orbit.mjs backend/.sources/integrated-components-v2-20260928-e --full-scene --small-interaction
node scripts/probe-research-point-order.mjs backend/.sources/integrated-components-v2-20260928-e
node scripts/probe-research-edit-contract.mjs backend/.sources/integrated-components-v2-20260928-e --full-scene --projected-region
node scripts/probe-research-edit-contract.mjs backend/.sources/integrated-components-v2-20260928-e --full-scene --projected-region --preserve-source-order-diagnostic
```

下一步最小工作：恢复独显后只补未完成审计，不重跑1800步；利用现有眼区线段候选建立有真实深度的跨视图镜框链，补查发际线和耳上可见外表面的局部视差；让可靠鼻唇表面上的窄足迹替换继续保持覆盖，检查真实边缘而非平均RGB；单独补颈肩衣领运动/遮挡；获准产品范围后修加载顺序并做同资产真机编辑。不要延长训练当作结构修复，也不要将本轮坏候选接入自动回传。
