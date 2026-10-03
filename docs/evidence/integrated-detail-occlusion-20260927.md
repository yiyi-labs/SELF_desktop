# SELF 人物细节与脸前遮挡：隔离实施和真实画面复核

日期：2026-09-27。依据当前仓库、`SELF_Reconstruction_Integrated_Detail_Occlusion_Codex_20260927.md` 与用户贴入的同任务文本执行。沿用既有 E1—E5，不降低发布标准。原始视频、面部图像和研究 PLY 均留在项目忽略的私有目录；本轮没有改鸿蒙应用、签名、旧作品、USB/HDC、PlayCanvas 产品入口、既有上脸与故事代码，也没有回传新研究资产。

## 冻结基线与身份

| 身份 | 实际内容 |
| --- | --- |
| 源视频 | `backend/.sources/quality-geometry-20260926-temp/capture.mp4`，SHA-256 `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`；65.393 秒、1963 源帧，旧选帧 160。 |
| A：当前完整场景 | 同源旧 `portrait.gaussian.ply`，SHA-256 `acc35d39fc24dbbd2789d57b774fe0d256d24f5017af231918c39ec79bc9a41d`；3000 步、126210 点。 |
| B：方向色修正后的局部头部 | 旧 head-local-sh1 PLY SHA-256 `7cec883181b0fa21589970b472cef5debc29d9c3184e9294ae048d88d0f20be4`，黑底研究样件；不以它的局部指标代表 A 的完整场景。FLAME Open 文件 SHA-256 `e75a0990728ba038c7da2a420ae4396f7ddd7781366c13026066c5b24f127623`。 |
| C：平板当前作品 | 本轮未读取平板资产哈希，不能把此前截图绑定至上述研究 PLY，也未对平板安装或替换。 |

本机依赖保持已装锁定环境：PyTorch 2.8.0+cu128、gsplat 1.5.3、PyCOLMAP 4.2.0；8GB RTX 5070 Laptop。没有升级 CUDA/驱动，也没有向第三方发送此视频。[gsplat 1.5.3 光栅化接口](https://docs.gsplat.studio/versions/1.5.3/apis/rasterization.html)的 N-D 特征和 [1.5.3 增密策略](https://docs.gsplat.studio/versions/1.5.3/apis/strategy.html)及本机对应源码已核对。逐点贡献探针是项目自己按线性特征求导实现，**不是** gsplat 提供的现成语义审计 API。

## 实施与因果发现

`backend/reconstruction_joint_visibility.py` 把人物和环境放进**同一次** gsplat 透明合成。人物用记录的相对头部运动变换，房间保持世界坐标；头部与房间方向色分别在原训练约定中求值。画面同时输出 RGB、总 alpha、人物贡献、环境/衣物贡献。`q_person+q_environment≈alpha` 的实际最大残差约 `1.1e-6`。诊断探针通过一个零值可微特征返回各点在指定像素中的可见贡献；这些分数**不等于删除点后的反事实图像**。

发现旧 `backend/reconstruction_train_joint.py` 虽导出一份混合 PLY，训练时却把另一组的 opacity 置零：脸部步只见人物，房间步只见背景。旧完整场景在共同绘制的三张发展视角上脸部 RGB L1 为 `0.1771/0.1898/0.1151`，环境/衣物在脸内部贡献约 `0.249/0.265/0.171`；生成的房间单组画面中还有人的轮廓。污染不可能凭“点中心投影到脸里”或只看颜色定性：来源包括环境补点、已注册稀疏点、混入衣物、人物覆盖不足、宽投影、姿态和方向色。画面在 `backend/.sources/integrated-visibility-audit-20260927-c/`。

`backend/reconstruction_train_joint.py` 增加隔离的 `shared_research` 真实 Adam 训练，默认生产模式保持原样。该分支的每一步前向包含所有点，完整源图 RGB 与人物/房间覆盖共同监督，只变换头部点；衣物尚在旧静态组，不能解释为正确运动。`backend/run_integrated_joint_research.py` 使用独立 run-id，输入软链到同一冻结视频，不覆盖原文件。3000 步研究候选 PLY SHA-256 `304da69078f6bb2519c1e049c65fe39734eaf60bfc2f0b40144f794feac1f610`，97742 点（人物30027、环境/衣物67715），实际训练 `63.59s`，Torch allocated 峰值 `295 MiB`。它在记录的源相机下，脸从大片蓝白污染变为可辨人像；房间保留但偏软。训练损失及文件在 `backend/.sources/integrated-shared-joint-3000-20260927-a/`。这是**局部真实画质改善**，不是发布通过。

为辨别来源，`backend/reconstruction_train_joint.py` 将不可训练的源索引随 gsplat split/clone/prune 一起更新，按精确 PLY 哈希保存 `portrait.provenance.npz`；`backend/audit_reconstruction_provenance.py` 把它与共同合成逐点可见分数按哈希连接。在三个发展视角的“当前贡献”中，原始 COLMAP 轨迹占 `38.8%`，有插值深度的场景补点占 `61.2%`。两类都有在脸内强可见且在真实可见房间弱支持的点；不能以“删除所有补点”修复。原始补点由最多360px外的四个深度邻居近似，`backend/reconstruction_scene.py` 仍可能创建缺乏多视图表面支持的室内体积。衣服仍被旧二分标签放在 environmentAndClothing，逐点分数并非纯房间归因。

`backend/counterfactual_reconstruction_clean.py` 曾只在私有副本中降低 24/188 个疑点 opacity。188 点的数字筛选虽改善部分 L1，实际接触图仍有大片污染，**视觉失败**。进一步的 `--clean-research` 在共同前向内给源图头部内侧的环境贡献加小权重，同时保留 RGB/覆盖/可见房间；候选 SHA-256 `80233ff166d89dd9ab9ee686efaa3f5da0b12a73019326b91d7f866fbedf1793`，3000步、`74.78s`、Torch allocated峰值`325 MiB`。环境贡献数值被压低，但六个记录视角中五个脸部误差上升，固定 PLY 侧向仍有白色碎片、眼镜错位和连接不良。**不合并清理项，不删真实前景，不回传。**

`--detail-research` 在共同前向的原片内部增加有符号相邻 RGB 差损失，不在输出截图上锐化，源图 mask 边缘不参与。其 SHA-256 `fbd560f3a2a4cd7513fa9aabfb61f782d1cec5f7c2dc619d7c4c0d6b2fcc4af7`，3000步、`69.71s`、Torch allocated峰值`333 MiB`。三张原生像素留出裁剪中，边缘误差变化极小，肉眼鼻翼/唇线/镜框细节仍未真正恢复；只是图像损失的补充，**不能称作细节重参数化成功**。

旧 FLAME 局部 r6 的增密保留了宽父点。`backend/research_face_surface_refinement.py --replace-parent` 现在能让同一三角内的两个有界子基函数真正替换粗父基函数，保留源索引、三角绑定、语义与新 optimizer 的参数对应；旧实验默认行为不变。实际 14 训练/8 开发帧、1000 父点→2000 子点（总11715→12715）、112步几何+520步外观，候选参数 SHA-256 `a2b5704412a5a65e812326bf282c22928971257c4e3661a361baa8c33e0aa895`；`18.02s`、Torch allocated峰值`766 MiB`。八张开发帧鼻唇固定 ROI L1 均值从 `0.029984` 到 `0.029639`，相对旧 r6 只有很小的数值变化，局部画面仍软。此实验是**黑底头部局部研究**，不是完整场景 Combined，也没有新的可见细节通过。

## 同条件原片对照与真实缺陷

`backend/audit_native_face_comparison.py` 用同一原生像素、K/crop、世界相机、对应头姿、源 face mask 和完整场景，把 Base/Shared/Clean/Detail 四份 PLY 同视角渲染。`backend/.sources/integrated-native-face-compare-20260927-a/audit.json` 与三个接触图为私有审计资料。三张都属于已反复参与方案选择的**开发视角**，非盲测。

| 原片视角 | Base 脸 RGB L1 | Shared | Clean | Detail | Shared→Detail 有符号边缘 L1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| frame_0001 正面 | 0.09514 | 0.02718 | 0.02689 | 0.02707 | 0.009698→0.009691 |
| frame_0081 侧向 | 0.18581 | 0.02390 | 0.02939 | 0.02411 | 0.007470→0.007475 |
| frame_0145 另一方向 | 0.18987 | 0.03361 | 0.03916 | 0.03316 | 0.007724→0.007656 |

同一三视角的半分辨率完整画面里，Shared 对 Base 的脸内部环境/衣物贡献分别 `0.276→0.063`、`0.514→0.159`、`0.690→0.238`；对应可见房间 RGB L1 `0.0702→0.0717`、`0.0412→0.0463`、`0.0410→0.0443`，房间误差略升。Clean 又把贡献降至 `0.004/0.015/0.026`，但脸部误差与局部错位反弹。**只最小化 q_environment 会制造误导性好数字。**可见房间、人物覆盖和原片脸部都必须同时看。

Base/Shared/Clean/Detail 的同一视角裁剪说明 Shared 有真实改善，Clean 和 Detail 均未越过视觉闸门。真正不足的是可信世界相机、短发/眼镜的独立三维结构、头颈肩与衣领相对运动、房间多视图表面支持；不能靠降低点 opacity、给人像优先绘制、假光效、磨皮或输出锐化补救。

## 单一 PLY 连续绕看、资源和 E1—E5

`scripts/probe-personal-continuous-orbit.mjs --full-scene` 在 Chrome SwiftShader WebGL2/PlayCanvas 2.22.4 中对 **Shared 同一 PLY** 连续前方→约+60°→约−60°→回正，过程中再次核对 PLY SHA 未变化；浏览器 page error 为0。视频 SHA-256 `06aaeb34a336bfa9702bffce7e109035152b01fdfd3ab0223d4b630f447cf98d`，位置/相机在 `backend/.sources/integrated-shared-joint-3000-20260927-a/continuous-orbit/audit.json`；参考视图来自 `frame_0012.png`，需与视频源时刻区分。侧向画面出现大块白色碎片、眼镜与发侧错位、颈肩连接模糊；**图形可加载，质量失败**。Clean 单一 PLY 的相同浏览器轨道也失败，视频 SHA-256 `56416091884b855b7b7141c7d37c640a988e01c5ec7d8a496c07fcbebce8166f`。viewer yaw 不是头相对真实观察角；该轨道有未被可信世界相机覆盖的方向，不据此编造 PSNR。

同一 Shared PLY 的 `scripts/probe-research-edit-contract.mjs --full-scene` 实际在电脑 PlayCanvas 圈选111点，111点均位于现有 `editableSplats` 前缀，环境点0；数字试色图像有变化，“看原样”截图哈希与初始完全一致，再显示修改与改变图一致，浏览器异常0。私有截图和 `audit.json` 在 `backend/.sources/integrated-shared-joint-3000-20260927-a/edit-compatibility-full-scene-v2/`。这是现有图形/撤销合同，不证明局部贴合、品牌实物效果或鸿蒙真机编辑。

| 既有门禁 | 当前事实 |
| --- | --- |
| E1 | **失败**。旧静态复核关键中段无可信世界相机；新 `ObservationBundle` 将 COLMAP 注册的160帧标为混合人物/房间特征的估计，可信静态数0。此轮未凭数量“升级”姿态。原片有两侧面容，不是用户未拍到。 |
| E2 | 局部 FLAME Open 几何/真实外观、父点替换子能力可运行，头发、眼镜、颈肩实际几何与多视角一致性**失败**。 |
| E3 | Shared 3000步确实用完整人物+房间同次前向，源图脸改善；固定 PLY 侧向和完整遮挡/连接**失败**。 |
| E4 | 原生像素面部细节与真实局部替换已执行；细节主观与结构仍**失败**。 |
| E5 | 电脑真实 PlayCanvas 2.22.4 同一研究 PLY连续旋转可加载；圈选、数字试色、原样恢复与重放合同通过。侧向画质**失败**；本轮未做鸿蒙新资产/真机编辑验收。 |

Torch allocated 峰值分别为 Shared295、Clean325、Detail333、头部父点替换766MiB。**这不是整进程或8GB设备峰值**，也不能从热启动的63–75秒训练推定视频传输、解码、E1、FLAME、训练、导出完整任务满足120–180秒。电脑 Chrome SwiftShader 不是鸿蒙模拟器或真机性能证据。

## 通用新任务接入、回归和未完成项

`backend/reconstruction_worker.py` 为今后选帧保存源帧索引、PNG哈希和经ffprobe逐帧对应的 PTS；无法验证时写 `null`，不以名义 FPS 伪造，也不会因可选 PTS 探针失败让有效视频建模失败。`backend/reconstruction_pose.py` 单独保存受当前估计尺度约束的局部头到相机 F_t；`backend/reconstruction_observations.py` 按**文件名**关联图片、K、COLMAP C_t、局部 F_t、mask/哈希及开发用途。历史160帧实际回归得到160个世界估计、0个已核验静态世界姿态、160个补偿头视图，旧任务没有单独保存 F_t 因而其计数为0；不能把这些估计相机当发布真值。`backend/reconstruction_face.py` 还保存六类人物观察及供以后E1对照的静态特征候选遮罩，**当前生产 COLMAP 未改为使用它**。后续新视频的跨设备画质仍未验证。

新增并重跑的源码/来源、分组守恒、梯度、真实 gsplat split/clone/prune、带符号源边缘、父点替换及配饰遮罩等单元测试共16项通过；Python 编译与 `git diff --check` 通过。Windows 后端 `/health` 为ready，私有 worker 心跳在本轮末仍为ready。没有构建HAP，因为鸿蒙代码未改。研究模式只写独立目录，不改变生产默认训练或用户作品；任何坏候选都未回传平板。

Base 为旧完整场景；Clean/Detail 是同一输入、3000步和共同合成下的单因素候选，均未满足质量闸门。因此**不运行 Combined 作为可发布候选**，也不借“fidelityWarnings为空”放行。接下来的最小必要工作是：先给关键中段建立有静态多视图支撑的世界相机与环境表面，保留仅局部可信的脸观察；把头发/镜框/颈肩衣物从皮肤与静态房间中分离为有真实三维支持的运动部件；再用原片结构对应驱动父点替换和完整共同训练；最后同一PLY做连续轨道、PC与鸿蒙同资产绘制和现有圈选/试色/撤销回归。尚无第二段获准视频，不能宣称已跨用户和跨拍摄泛化。

复现命令（在 `backend/`、本机锁定 WSL 环境中，私有输入路径见上）：

```text
python run_integrated_joint_research.py <frozen-job> <new-run-id> --steps 3000
python run_integrated_joint_research.py <frozen-job> <new-clean-id> --steps 3000 --clean-research
python run_integrated_joint_research.py <frozen-job> <new-detail-id> --steps 3000 --detail-research
python audit_joint_reconstruction_visibility.py <frozen-job> <PLY> <new-audit-id> frame_0001.png frame_0081.png frame_0145.png
python audit_reconstruction_provenance.py <same-PLY-provenance.npz> <same-PLY-private-point-visible-weights.npz> <new-report.json>
python audit_native_face_comparison.py <frozen-job> <new-audit-id> frame_0001.png frame_0081.png frame_0145.png --asset Base=<PLY> --asset Shared=<PLY>
python research_face_surface_refinement.py <frozen-job> <head-local-sh1-parameters.npz> --run-id <new-id> --steps 520 --edge-weight .12 --geometry-warmup 112 --max-new-skin 1000 --replace-parent
node scripts/probe-personal-continuous-orbit.mjs backend/.sources/<new-run-id> --full-scene
node scripts/probe-research-edit-contract.mjs backend/.sources/<new-run-id> --full-scene
```
