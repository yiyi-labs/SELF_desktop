# 固定深度工具接入与真实训练对照（2026-09-30）

本轮完成了实际深度推理、表面生成、面部/头发/房间反向优化、状态恢复以及同资产电脑绘制。**没有得到可发布的完整模型。** 新候选头发在六个固定回归视角均退化，房间覆盖和衣物连续性也失败；不部署、不回传、不切生产。

## 先回答当前任务

- **人脸是否训练并改善？** 实际进行了240步面部阶段，SH、alpha、scale、rotation，以及26次有界normal offset/embedding更新均有非零变化。固定回归face L1由0.041770降至0.041526，但改善很小，图片仍软；不能称恢复了源片细节。共享表面残差、身份、F/K和表达保持冻结。
- **背景是否学习完整有效影像？** 是。另240步在1080×1920原生全幅上，对真实room有效像素计算RGB、有效窗口结构和覆盖损失，包含柜门等低纹理区域；不是只监督特征点。此有限表示对照固定拓扑，**没有运行新的density**，不能说已完整执行参考式3DGS或全部joint。
- **加背景后是否保住同一人像？** 房间阶段冻结相同人像且所有组件共同排序/合成；五个可用开发世界视角face区域room贡献从R0的0.113177降至0.003718。但新room误差及低alpha区域恶化，不能用污染降低放行背景缺失。六个固定回归没有可信C，本轮不伪造它们的T2。
- **还缺什么？** 多视图头发真实外表面与发际线结构、独立上身B及连续衣领/肩部表面、镜框曲线结构、跨窗口深度/姿态充分一致性、背景覆盖恢复。没有把头F当衣物相机，没有把新深度当测量真值。

## 现场、身份和保护

W：C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay

P：D:/STUDY/College/mine/olay

开始HEAD：a1ff96ef63a922622828fac15fb75689792d7d93（codex/reconstruction-v3-audit-20260928）。

P HEAD：3dad0cd5651824cc06d9e88d61aabdd2642c0b30。

R0：W/backend/.sources/fullframe-surface-patch-20260929-b/R0-frozen.pt

R0 SHA256：2468edc379f8b76eac97fccfbf9e9a4c775f980102b95283ee15b2dc4cee7cb8

Prepared：P/backend/.sources/integrated-components-v2-20260928-e

原视频SHA256：7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf

研究目录：W/backend/.sources/dense-motion-surface-20260930-h。之前a—g及全部失败证据保留。g仅为修正时间顺序前的诊断，不作质量基线。本轮没有写P，没有改应用、签名、旧作品、USB/HDC、生产查看器、AI/OLAY、上脸或故事；E1—E5不变。

## 本轮最小代码修改

1. run_dense_observations.py：发现local_geometry行顺序并非原片时间顺序。窗口改按frame manifest的timestampSeconds/sourceIndexZeroBased排序，F仍按imageName取正确行。没有把图像ID当帧序号。
2. reconstruction_dense_contract.py：修复OpenCV remap请求行数超过32767的真实失败。只分批请求，不降采样原图、不改坐标或阈值。加入source hash、字段长度、有限值及UID合同，拒绝不同视频表面误接。
3. reconstruction_dense_surfaces.py：保留原数值生成器，补显式prepared/depth/out的可复用阶段入口，避免依赖某个历史run路径。
4. run_dense_surface_training.py：接入真实有限优化阶段；旧face绑定继续使用，新hair为头局部独立前景，新room为世界组件，旧眼镜/身体只作未修上下文。完整保存初始化、120/240/360步、终态、Adam、RNG、sampler、绑定、UID、来源和策略状态。
5. 两个审计入口与隔离PlayCanvas脚本：同一PLY原生投影、贡献守恒、连续绕看、训练器→PLY→电脑查看器。没有修改生产渲染器。
6. 旧run-id保护：CLI遇已有目录时拒绝，不向旧成功run追加failure；真实回归已核对。

训练后追加的来源/UID守卫、CLI和失败目录保护只改变合同，不改变本次数值结果。真实运行源码保存在training/algorithm-source；后追加代码保存于delivery-receipts-c。新守卫已在receipts-guarded实际重放，输出与前次相同。

## 锁定依赖与真实深度

Depth Anything 3代码commit：3d835ec1a5802d64a8b8b15f817a1ab54809bfe4。

DA3-BASE revision：f4a6c9b3c95e41c82048423d3493a81ec3fa810e。

权重SHA256：e01067dc1659613083d9145a9a2547ccdbe6ccbbf83c4fe7b3e8a4e2bdae78b5。

工具目录：W/backend/.sources/tools/da3-3d835ec；官方代码及Base模型许可记录为Apache-2.0。原license/model card保留。[官方源码](https://github.com/ByteDance-Seed/Depth-Anything-3)、[官方模型](https://huggingface.co/depth-anything/DA3-BASE)。

本轮使用深度分支，**没有调用上游GS生成器，没有生成RGB、没有实施MegaSaM或Shape of Motion**。模型输入已含归一化已知F/C与对应处理后K，不能说“完全没传相机”。固定F/C不被预测输出重写；每窗口只有一个尺度。

24个训练头部观察，4个头局部窗口；17个世界观察，3个重叠世界窗口。开发8帧及固定回归6帧不进入深度初始化/颜色来源。这些评估帧已用于研发，不是最终盲测。

中心对齐相对RMS：world 0.02052—0.02930，head 0.00920—0.01391；相应对齐后预测朝向最大差异world 7.229°、head 5.502°。**低中心误差不证明深度准确**，朝向差异亦不能单独认定为全部退化的原因。输出是学习深度假设，没有被宣称为真实稠密几何。

表面原提议：head 362109，room 215145；去重/有限预算后head22000、room30000。head中skin16494只保留为提议，没有替换现有face；hair5470投入研究；glasses36未当镜架真值。每候选要求至少3个不同训练图像的深度兼容，空区反证、遮挡未知分开；约3%深度兼容仍非独立几何证明。

## 真实训练与对照

一次预定240+240步，逐视图全幅反传；没有重做900步、FLAME A/B、旧d2背景审计。面部前80步稳定外观，中段每4步有限几何更新，最后恢复；姿态/身份/共享残差不开放。房间阶段face冻结但仍渲染。没有新的T3/T4面部更新。

面部参数平均变化：normal_offset 0.00006022、embedding 0.00147860、log_scale 0.052593、SH 0.023642。新hair offset变化0.012005、SH 0.065214；新room offset 0.094600、SH 0.070933。详细曲线、源参数、每帧指标见训练result和receipts-guarded/result。

主指标固定mask，计入缺失像素；下表为相同原生全幅口径、按视角均值：

| 区域/用途 | 可恢复R0 | 新初始化 | 实际优化后 |
|---|---:|---:|---:|
| face / 8开发 | 0.031100 | 0.031939 | 0.031037 |
| face / 6固定回归 | 0.041770 | 0.044456 | 0.041526 |
| hair / 8开发 | 0.039585 | 0.074745 | 0.049858 |
| hair / 6固定回归 | 0.043766 | 0.077570 | 0.055436 |
| T2 room / 5有C开发 | 0.041490 | 0.226673 | 0.161660 |
| T2 neck/cloth / 同5视角 | 0.163257 | 0.222271 | 0.220885 |

新room低alpha（<0.8）区域均值由初始化45.139%降到30.757%，R0同口径0.561%。这是累计alpha代理，**不是“没几何”比例，也不证明R0背景正确**。柜门/把手轮廓在新样件能辨认，但侧面仍有空洞；新表示优于自己的初始化，不等于优于旧基线。

原片/R0/新初始化/终态同裁剪四联图，固定使用原先要求的0035、0075、0145：
- [0035四联](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/dense-motion-surface-20260930-h/receipts-guarded/frame_0035.png-comparison.png)
- [0075四联](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/dense-motion-surface-20260930-h/receipts-guarded/frame_0075.png-comparison.png)
- [0145四联](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/dense-motion-surface-20260930-h/receipts-guarded/frame_0145.png-comparison.png)

实际视觉审查：头发不再完全是均匀光滑帽壳，但出现颗粒、发际线刺点和耳上缺口；鼻唇/镜框仍软，颈部有杂纹。衣物是旧348身体种子及旧头部颈绑定，仍像云团，未得到新衣领/肩部表面。不存在“改分类就修好了头发衣物”。

前一轮连续观察只有55个下方cloth提议，没有上方衣领/肩部支持；不能用它们宣称独立上身运动已解。眼镜36深度提议也不足以代替稳定镜腿/镜框三维曲线。本轮没有实际重建或训练新的身体/镜架；这是明确的实现缺口。

候选筛选失败：六个hair固定回归，五个room开发视角。自动恢复至本run的新初始化；model、Adam、绑定、sampler、RNG、strategy、trainable、contract、extra逐项完全相等。**不是把R0文件或生产状态回滚了**。initial/candidate/restored和失败图全部保留。

## 同一资产、坐标与绘制

唯一PLY：training/candidate-research-only.ply，reference frame_0111.png。

SHA256：cd39aac5afe2b018daf7689c00c1fcdf07eb0cc9202a030fde657153513cf8a9。

44871点；精确point_id及(来源namespace, UID)无重复；来源守恒max约7.15e-7。body与neck共用部件标签不代表两者已正确融合；旧body仍348个上下文点。

训练器→标准PLY→gsplat回载：
RGB平均差2.65e-8、最大0.000543；alpha最大0.000812；q最大0.000811。少量边界差异保留，不称逐位恒等。SH1的真实语义、head-local→world协方差/SH转换继续使用既有正确路径。

同一PLY连续绕看121帧，原生1080×1920绘制，视频仅编码为540×960/20fps。轨道−60°至+60°是viewer相对角，**不等于已测真实人脸角度**。录像来自gsplat，未按角度换模型：
[固定资产连续绕看](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/dense-motion-surface-20260930-h/asset-audit/frozen-ply-orbit.mp4)。

PlayCanvas2.22.4实际电脑绘制：相同PLY/C/K/1080×1920，maxPixelRatio1，无LOD、无fog、无postEffects；默认compact、minPixelSize2、GAMMA_SRGB、exposure1。没有改gamma/曝光/对比度掩盖模型。相机变换最大差1.84e-7，读取raw GL预乘RGBA与gsplat黑底合成比较：全图RGB MAE0.007339、face0.006712、hair0.006429、room0.005934；alpha仍有差异，不称渲染完全一致。无加载错误，但并未隔离量化/剔除/排序各自的责任。
[双绘制器对照](C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/dense-motion-surface-20260930-h/receipts-guarded/gsplat-playcanvas-raw-comparison.png)。

此处Chrome SwiftShader只证明电脑真实绘制合同，**不是鸿蒙验收或设备fps**。真实图在两个绘制器里都不合格。生产上脸算法没改，但新候选的完整编辑/设备兼容尚未测。

## 资源、通过、失败和未验证

- 深度推理总43.21秒；PyTorch峰值分配2886.91MiB、保留4532MiB。
- 240+240步及评估导出198.63秒；峰值分配921.94MiB、保留1116MiB。
- 此有限任务均无OOM；不能据此推断所有未来8GB流程必然无瓶颈。上述不是GPU总占用，也不含原视频准备、表面CPU生成等完整耗时；不宣称完成2—3分钟全流程。
- 通过：20项CPU合同回归；真实推理/反传/Adam；来源与UID保护；初始化精确恢复；同PLY回载/电脑加载和连续绕看。
- 失败：头发优于R0、全观察room覆盖、清晰面部细节、衣物/颈肩连续、完整作品质量。
- 未运行/未验证：新镜架、独立上身B/衣物重建、新density、新T3/T4、鸿蒙/手机/平板绘制与编辑、最终独立审计。
- 新候选拒绝；旧作品和R0不被覆盖。GPU/驱动/全局环境未修改，没有上传私人数据。

## 可复现入口与后续唯一优先动作

先读取本run training/config、contract、spec、algorithm-source、初始化和源数据hash。旧R0没有历史Adam，只是warm-start；新run保存了自己的完整状态。元数据保护后来增加，冻结源码和当前源码不能混称“当次算法完全相同”。

在WSL原venv中，用新out复现（以下W/P以本文绝对目录换成/mnt/c与/mnt/d路径）：
1. 独立工具venv运行 backend/run_dense_observations.py --prepared P/backend/.sources/integrated-components-v2-20260928-e --split W/backend/.sources/fullframe-surface-patch-20260929-b/observations.json --tool W/backend/.sources/tools/da3-3d835ec --out 新目录/depth --limit 24 --batch 8。
2. 原venv运行 backend/reconstruction_dense_surfaces.py --prepared 同上 --depth 新目录/depth --out 新目录/surfaces。
3. 原venv运行 backend/run_dense_surface_training.py --stage W/backend/.sources/canonical-observation-repair-20260930-a/stage.json --surfaces 新目录/surfaces --out 新目录/training。阶段固定240+240，不增加参数搜索。
4. backend/audit_dense_surface_asset.py --folder 新目录/training --out 新目录/asset-audit；Windows项目Node运行 scripts/probe-dense-surface-display.mjs 新目录/asset-audit；再运行 backend/audit_dense_surface_training.py。
5. python -m unittest test_reconstruction_dense_contract test_reconstruction_dense_surfaces -v。

下一项唯一优先动作：**在训练角色的连续短窗口中，用真实跨视图像素轨迹约束同一个局部三维表面，将新深度作为带不确定性的初值；同时保留已有F/K规范和可靠可见性，先验证跨窗口结构与厚度，再接覆盖恢复训练。** 不能仅按相机中心RMS放行、全局加scale/opacity或再延长步数。发际线是首先检验的部位；独立上身B和衣领/肩部仍需另一项实际几何实现，不借头部替代。这些后续能力在本轮没有完成，不能说成熟完整重建路线已被充分尝试并证伪。

本报告交付真实训练的阴性结论和已实现交接能力；没有宣布用户的完整建模目标已完成。原片、失败候选、完整检查点和图像仍在本机私有.sources，Git只记录代码和本报告，不自动备份这些资产。
