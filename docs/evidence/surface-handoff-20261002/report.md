# SELF：运动监督交接与实际遮挡贡献驱动的表面替换

2026-10-02。保留E1—E5。隔离后端修改与真实GPU训练，不改应用、签名、历史作品、USB、AI/OLAY、上脸、故事或生产查看器。**三组候选均未通过，不能以人脸白雾减轻换取背景/衣物退化。整体目标尚未实现，新能力保留为研究分支，模型不采用。**

## 身份和保护

- W：C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay；开始HEAD `cf774520a14745433166933b50ffc7a1e29697d4`；分支codex/reconstruction-v3-audit-20260928。
- P：D:/STUDY/College/mine/olay；HEAD `3dad0cd5651824cc06d9e88d61aabdd2642c0b30`；既有18个tracked修改及未跟踪文件未处理。
- 完整研究起点：backend/.sources/continuity-physical-surfaces-20261001-b/body-transition-sh，50095点；它已有完整内容，但质量未通过，不称已发布作品。
- 原PLY SHA256 `a343ccf05292ce1e174c7fd63795122347a8d03bd0202a19395a9a414b691f41`；完整检查点SHA256 `c3425ba01892940353909dbf3f95d5058ef507e023357ef864d4cb1460cac344`。
- 原视频capture-1790410633104.mp4关联sourceHash `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`。深度缓存manifest SHA256 `11391f4d5f55cf1d1d1fa5bd7ba314b006879affa0783be5dc5d8d59cdaeba23`。
- 继续FLAME Open、torch2.8.0+cu128、gsplat1.5.3、head-local-SH1、原生全幅投影/排序/合成、标准PLY与namespace+UID。RTX5070 Laptop8151MiB，driver617.14；实际CUDA计算可用。
- 无reset/clean/stash/rebase/amend/强推/清理run，无新依赖安装或驱动调整。没有重新拍摄、相机匹配或FLAME A/B。

## 可保留的实现修正

1. 衣物深度跨时刻交接使用 `B_target inverse(B_source)`，在与世界C相同的尺度中运输。未知B不能偷偷用单位矩阵。room仍静态运输；衣物和颈皮肤不是同一个运动层。
2. 明确验证状态。最终代码要求body_motion_verified；仅有光度拟合B不能启用cloth深度监督。未知运动仍保留原片RGB监督，不删除衣物或其显示。
3. 连续有限平面以真实射线与3D面交点采样，切向范围根据相邻射线间距、法向厚度受限；不是屏幕贴片。仅训练观察取真实RGB，至少三个不同观察深度支持。网络深度是相机条件假设，不是独立真值。
4. 待替换点以完整共同合成的实际alpha*T贡献选择。投影支持选择与旧错误中心的三维距离分开。几何错误的宽核可能离正确表面很远，不能用旧位置限制替代面一定落在原椭球里。
5. 替换是副本事务：其余全部人物/环境参数精确保留，父核暂退役，新核绑定原片来源/UID；完整模型始终共同绘制。没有人像最后绘制、调全局曝光、全体压opacity或刷黑头发。
6. 新入口可复用冻结准备和完整观察表面缓存；核对sourceHash、检查点、当前训练角色、实际projection evidence；不依赖这个人的绝对坐标、衣服图案或固定帧编号。

文件：reconstruction_ray_surface.py、reconstruction_surface_handoff.py、run_surface_handoff_repair.py、test_surface_handoff.py，以及本轮audit_surface_handoff_*.py。它们都是隔离stage/核验，不切生产默认。

## 实际训练协议

23个可靠world C训练观察，5个可用开发观察。原8开发/6固定回归不更换；没有world C的观察不伪造完整场景评价。它们长期参与研发，不称最终盲测。

每对控制/候选同320次真实Adam更新、同采样seed100202、同图像和反传预算。人物/相机/身份/运动冻结；room SH、alpha、scale实际更新；位置/rotation在这组表示对照固定。scale保持初值80%—125%，无全局缩点/reset/density。全部有效room RGB及有效结构窗口监督，face/hair/neck/cloth有逐像素退化约束。

旧源检查点完整加载，但本轮Adam从新状态开始，是warm-start，不声称旧Adam精确resume。保存init/mid/final/restored、Adam、RNG、sampler、strategy、bindings、源点/UID、实际源码和资产hash。

## 有限平面两组结果

B：12个按旧3D邻近选择的核→3979新点，总54062点。C：6个实际人物污染核→33820新点，总83909点。C复用B的同一冻结平面池，没有重新准备。B和C既改变了对象也改变了表示规模，**不是二者之间的单因素A/B**；各自内部控制才同预算。

| 5个有world C的开发视角，固定mask RGB L1 | 原起点 | B控制 | B替换 | C控制 | C替换 |
|---|---:|---:|---:|---:|---:|
| face | .058422 | .058423 | .058411 | .058489 | .027895 |
| hair | .138903 | .138922 | .137753 | .138601 | .057026 |
| neck | .098850 | .098846 | .098827 | .098811 | .114280 |
| cloth | .129719 | .129738 | .129879 | .129654 | .136517 |
| room | .041586 | .041244 | .049822 | .041423 | .075387 |

C中的头部参数一点没变；脸/头发改变来自room遮挡/混色改变，**不代表头发结构或面部细节重新训练成功**。完整10视角（含训练）face上的room贡献.187694→.004906，正亮度偏差.071798→.014538；可见白雾确实减轻。与此同时低纹理room L1 .035216→.097205、alpha<.8比例.004108→.255785，柜门/墙面呈块状缺口，衣物覆盖和颈色差也退化。alpha低不是几何不存在的定义，但结合真实图像确认内容未被完整承接。C拒绝，不用更低face L1放行。

B的room/结构也退化，拒绝。两个控制数值屏通过，但几乎没有可见提升，不宣称解决白雾。

| 真实训练 | Adam步 | 训练秒 | Torch allocated/reserved峰值MiB |
|---|---:|---:|---:|
| B控制 | 320 | 60.01 | 769 / 1044 |
| B替换 | 320 | 52.16 | 775 / 1018 |
| C控制 | 320 | 36.25 | 769 / 1044 |
| C替换 | 320 | 38.46 | 809 / 1100 |

B整轮413.38秒、C整轮277.38秒，包含准备/加载/检查点/评价I/O，不含原视频准备或全部后续绘制。无OOM；Torch峰值不等于整机显存峰值，不宣称完整2—3分钟。

## 更完整非平面缓存的最后一次有限对照

D不是再跑同一平面。复用已保存174402点的完整观察表面池，SHA256 `9dd8bded976377a26dd0ce54c9bcb26084d3a7a8948ccdffc4e55f0a402674e1`；重新核对当前训练role、sourceHash及17个源图，原始位置/协方差/颜色保持。没有重新枚举、匹配、相机求解、MVS或补造平面。

按同一实际贡献规则，选择三个主要污染核，退役3点→170688个有多视图支持的缓存点，总220780。175000局部预算在执行前固定。D与C的对象、点数和表面类型不同，二者仅是不同完整方案的有限尝试，不能把二者差异全部归因于一个因素。D内部仍是同320步、同源图/seed/反传预算的旧表示控制对照。

| 5个有world C的开发视角，固定mask RGB L1 | 原起点 | D控制 | D替换 |
|---|---:|---:|---:|
| face | .058422 | .058535 | .027894 |
| hair | .138903 | .138699 | .056986 |
| neck | .098850 | .098810 | .114115 |
| cloth | .129719 | .129719 | .130620 |
| room | .041586 | .041475 | .064167 |

背景比C少一些缺失，但仍不合格。完整10视角中低纹理room RGB L1 .035216→.086084、alpha<.8比例.004108→.095567；face room贡献.187694→.005324、正亮度偏差.071798→.014550。训练图和开发图仍有背景黑洞、边缘块状不连续；颈色差也变大。不是因为点数预算已达到就能放行，也不能将低alpha比例直接当几何缺失定义。

D控制37.123秒，Torch allocated/reserved 769/1044MiB；D候选41.665秒，960/1246MiB；整轮289.528秒，不包含原视频准备。三组共1920次真实Adam更新，全部仅更新room外观/尺度；脸、头发、衣物的新增训练步数均为0。人像原参数最大变化仍为0。没有OOM，不能由此保证任何输入都不超过8GB。

D实际执行快照中normalThickness说明误沿用有限平面的`.12`文字；这只是元数据说明错误，实际始终加载缓存原scales，没有对D施加该平面厚度公式。最终源码已改成“cached actual normal/tangent axes”，没有覆盖旧config或将历史参数改写。

D拒绝；保留初/中/终/完整恢复和失败原因。普通点数增加不是这次缺口的充分解法。缓存深度虽然通过原多视图支持筛选，仍是相机条件预测；尚未证明不同窗口表面具有正确共享深度、边界和遮挡关系。下一次结构修复必须以真实静态对应及边界核查这些关系，不能拿当前有孔洞的预测池当几何真值。

## 逐项事务和衣物交接证据

对C六个父核分别只替换一个，在原8个训练观察做零更新共同重放：三个主要核37589/36949/36667均改善脸/头发，但损伤room；33651也损伤room；36719损伤cloth。36825初始训练屏通过，但人物变化几乎为零，没有最终验证或自动采用。它们只是本次来源索引，**代码没有硬编码这些点**。

因此不能在整组失败后偷偷挑开发图最漂亮的一项。候选解释和发布状态仍分开。

衣物真实像素核验：按图像归一化网格分布取角点、前后向<.75px、NCC>=.85、至少4图。得到19条源轨迹记录/66次非源比较；不同源轨迹可能重复同一物理特征，不能称19个独立三维锚。静态投影/当前B补偿误差中位16.366/15.904px，P90 37.941/37.207px。源深度也是预测，所以它是有真实RGB核查的条件诊断，不是独立深度测量；没有验证现有B可靠。未重新拟合B，衣物训练步数为0，不能声称颈肩运动修好了。

最终保护性修正禁用未验证cloth深度。B/C实际执行快照发生在这项保护之前，计算了B运输的诊断缓存；其训练本来只使用room RGB/结构，没有使用cloth depth，不把后续源码改写成历史当次行为。

## 显示与恢复

PlayCanvas2.22.4桌面Chrome SwiftShader，1080×1920，同K/C、compact/minPixelSize2、原gamma/exposure，无fog/LOD/后处理。原、控制、C候选实际加载，错误列表为空。**不是HarmonyOS，也不是设备fps。**

固定C候选PLY SHA256 `3d3ebeb7966440a7912bc4cdb9ac82f782b49fdba9e24f47a17710f7c23815b1`，121帧连续绕看；全幅计算、540×960编码。renderer=gsplat1.5.3，yaw是viewer相对角，不是实拍人脸角度。q守恒最大7.75e-7。绕看没有按角度换模型。

六训练分支源baseline字段最大变化0；model/Adam/samplers/RNG/strategy/trainable/bindings恢复完全一致。三个控制初始RGB/alpha/q与原完整绘制最大差均不超过5.37e-7。点数、来源和资产hash核对通过。数学/恢复通过不等于画质通过。

最终23项回归在4.918秒内实际通过，包含CUDA前向/反传一致、运动运输/单位/未知状态、3D面投影、非平面拒绝、投影支持选择、预算和部件保护、既有连续颈与SH合同。没有以旧测试次数代替本轮执行。

[原片／旧模型／控制／C候选](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/surface-handoff-20261002-c/quality/frame_0010.png.jpg)

[同相机真实PlayCanvas对照](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/surface-handoff-20261002-c/quality/source-baseline-control-candidate-PlayCanvas.jpg)

[固定同一PLY连续绕看（失败研究候选）](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/surface-handoff-20261002-c/orbit/frozen-ply/frozen-ply-orbit.mp4)

补充实际双端结果：同参考相机的全幅gsplat/PlayCanvas原始预乘RGB MAE，旧模型.090770、C候选.040865、D候选.038524，明显缩小但仍未一致。D参考视角PlayCanvas对源图face L1 .024852→.024406、hair .044775→.040211、cloth .054254→.054107、room .130032→.106273。它们只是一张参考图的指标；脸部在桌面查看器的改善远小于gsplat那组变化，不能用训练器数字承诺设备观感。实际截图仍显示发壳、颈接缝和环境缺失。

D同一PLY SHA256 `5d22f9370a0b94661a5e04441e9304c37842e51c44c38915e561866323b1b3ae`也完成121帧0→−60→+60→0连续绕看；q守恒最大8.35e-7。renderer仍为gsplat1.5.3，不是PlayCanvas视频或HarmonyOS。桌面实际加载C/D的原、控制、候选均无脚本错误；没有以PLY解析代替绘制。

[原片／旧模型／控制／D候选，全幅实际渲染](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/surface-handoff-20261002-d/quality/frame_0010.png.jpg)

[同相机D实际PlayCanvas对照](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/surface-handoff-20261002-d/quality/source-baseline-control-candidate-PlayCanvas.jpg)

[固定D资产连续绕看：失败研究候选](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/surface-handoff-20261002-d/orbit/frozen-ply/frozen-ply-orbit.mp4)

## 当前状态

通过：运动/投影/身份交接保护、真实Adam更新、完整状态恢复、标准PLY实际读取及同资产绕看。局部证据：主要白雾由少量错误room宽核参与造成，已有真实图像改善。

失败：有限平面及当前更完整非平面缓存均未能安全承接完整环境；主要核安全替换、衣物/颈部共同画质、完整发布未通过。头发、镜框没有新几何，不能冒充它们修复。

未验证：新视频/无眼镜/不同发型泛化、最新HarmonyOS显示与设备性能、完整服务时延。研究缓存与私人模型只保存在本机.sources，Git不是独立资产备份。

下一步不能再用旧错误中心距离限制正确背景；应确保旧核承担的真实环境域得到连续表面和足够影像支持，再退役。尤其不能把低纹理或不平面的内容从表示中排除。衣物则需更可靠独立上身/颈运动观测，当前B不能承担高精度几何监督。
本轮只提交隔离后端实现、必要核验及本报告。原P和生产入口未写入，未部署、未回传，三组失败模型未切换默认或覆盖旧作品。未处理W已有的其他dirty文件。下一项最有价值的动作是：建立一个由真实静态轨迹、边界和邻近观察共同核验的共享局部背景表面，先证明它能独立承接受影响环境并双端连续呈现，再与冻结人物做替换事务；现有预测深度只作初始化。上身/颈运动是另一项独立几何缺口，不能被背景修复冒充已解决。
