当前生效说明：[原生运行入口](../README-native.md)、[当前验收](validation-native.md)、[接口核对](api-compatibility.md)。以下为旧 Web/Component3D 路线历史记录；不作为当前实现或验收结论。

---

# 原生渲染与 Remy 建模路线核对

核对日期：2026-09-22。用户最新决定：优先鸿蒙原生实现，真机验证可稍后安排；保留此前认可的界面。此决定更新 FINAL 文件中仅使用 ArkWeb 的技术约束，但不取消真实能力、用户自主选择和证据要求。未修改原始需求文件。

## 当前事实

- 原版玻璃对话、氛围、音乐、会话、授权及作品保存代码仍在，默认 EntryAbility 未换页。NativeProbeAbility 只是单独研发入口，没有迁移后的产品设计含义。
- 现有 3D 是 Lee Perry-Smith 扫描示例，经本项目脚本嵌入原 JPEG、固定 UV 方向，不是 Blender 生成，也不是用户的脸。没有已完成的拍摄重建流水线。
- 用户 API 26 模拟器的 ArkWeb 禁止 3D；原生 Component3D 曾加载同一 GLB，但眼口有异常亮斑，显式新建无光照材质产生过曝，故撤回该材质替换。另一次 Scene.load 返回 Creating scene manager failed。这些是失败证据，不是质量验收。
- 原生入口包含实际 Scene.load、Camera、Component3D、单指旋转、双指缩放、回正、异步失效保护和资源清理代码。此时只有构建/安装及部分加载观察有证据，旋转质量、圈选/编辑/PNG 没有原生通过记录。

## Remy 能证明什么

[Remy 官方网站](https://www.remy3d.cn/)展示空间记忆产品定位；[Remy 官方发布视频](https://www.bilibili.com/video/BV1JFstzWE1P/)明确以 3D 高斯泼溅介绍产品。[Khronos 发布的 SIGGRAPH Asia 2025 演讲第 28 页](https://www.khronos.org/assets/uploads/developers/presentations/glTF_Gaussian_Splats_-_glTF_BOF_SIGGRAPH_Asia_Dec25.pdf)将 Remy 作为 HarmonyOS 6 的 3DGS 应用，并把当时端侧重建列在后续事项中。不能据此断言 Remy 所有版本均端侧处理，或推断它的私有实现。

本次未取得 Remy 实际导出的原始文件或官方完整格式规范，不能声称已解析它的私有 MP4/GLB 封装，也不能将 KIRI Engine 的另外一套云 API 当作 Remy 的开放接口。未上传人像、未接入其云服务、未复制 Remy 代码或素材。

## 当前最优先验证的候选：华为公开原生 3DGS 链路

以 Remy 的使用体验为参考，优先验证“原生采集与跟踪 → Spatial Recon Kit 端侧重建 → 原生高斯渲染/编辑”。它可以避免先要求用户使用桌面 Blender，也避免把格式转换误当建模。

实际本机 SDK 为 26.0.0.105。已阅读下列真实声明，未把网络示例代码直接当实现：

| 环节 | 已核对的公开接口/内容 | 尚需实测 |
|---|---|---|
| 支持检测 | C API HMS_SpatialRecon_IsSupport，可能返回 801；支持与设备硬件、系统有关 | 目标真机上的返回值；不能只看 API 26 版本号 |
| 采集 | HMS_SpatialRecon_PushARFrame，或 PushFrame 输入 RGB 图像、内参、位姿、时间戳 | Camera/AR 同步、追踪丢失、方向、镜头切换、帧生命周期 |
| 重建 | CreateSession / StartSession / GetProgress / StopSession / DestroySession 等生命周期 | 真实面部数据、失败恢复、后台、发热与内存 |
| 保存 | HMS_SpatialReconOutputFormat 在本 SDK 只有 PLY、MP4 | 文件实际结构及读回；MP4 输出不能直接当普通视频或可编辑源模型 |
| 渲染 | spatialRender.GSPlugin.loadGSNode；通过 ArkGraphics 3D 场景承载 | PLY 重建结果和 Remy 导出样本实际加载、颜色/朝向一致性 |
| 编辑 | API 26 GSEdit：selectBy2DMask / selectByIndex / paint / undo / saveToPLY | 选择是否含背面、边界串色、保护区域、取消和失败后回滚 |

源文件：DevEco Studio/sdk/default/hms/native/sysroot/usr/include/spatial/spatial_recon_interface.h；hms/ets/api/@hms.graphics.spatialRender.d.ts、@hms.graphics.spatialEdit.d.ts；openharmony/ets/api/graphics3d/Scene*.d.ts。原生头文件目前仅声明 GS 模型类型，没有“输出带 UV 的三角网格”选项。[华为重建输出结构](https://developer.huawei.com/consumer/cn/doc/doccenter-capabilities/api/capi-spatialrecon-hms-spatialrecon-modelwriteinfo)、[原生高斯渲染 API](https://developer.huawei.com/consumer/en/doc/harmonyos-references/spatial-recon-spatialrender)。

这条链路是下一阶段优先做真机门槛的候选，尚不是全链路已验证的选型结论。尤其 GSEdit 只有“可以选择和上色”还不够证明满足 SELF 的严格保护语义：本 SDK 声明没有提供选中索引读取接口，不能擅自假定可以直接拿到稳定选区 ID、排除背面或实现所有视角不变。

## 保存格式分工

| 数据 | 拟采用格式 | 约束 |
|---|---|---|
| 高斯重建原件 | SDK 生成的 PLY + 元数据 JSON | 原件不可覆盖；需验证其高斯字段、颜色编码、点顺序和读回一致性 |
| 编辑作品 | 新 PLY + 原件 hash/资产版本/操作与保护记录 | 保存成功且读回校验后提交作品；普通点云 PLY、网格 PLY、高斯 PLY不能混用 |
| 图库分享 | SDK 合法生成的空间 MP4（如目标设备支持） | 单独验证图库交互；不得把录屏冒充可编辑 3D 数据 |
| 平面导出 | 原生渲染输出的 PNG | 固定相机/色彩/背景；不以带 UI 的屏幕截图代替 |
| 既有扫描示例/网格备选 | 标准 glTF 2.0 GLB，三角网格、UV、内嵌纹理 | 走网格加载器，不送入高斯加载器 |
| Blender 工程 | .blend 仅用于可选离线制作 | 不交给鸿蒙运行时读取；目前没有采用或安装 Blender 流水线 |

GLB 是容器，不能仅按后缀判断内部是普通网格还是高斯扩展；PLY 同样需要检查属性。[Khronos glTF 2.0 规范](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html)。本次新增 inspect-model.mjs 只检查 SELF 静态纹理网格配置，不检查/拒绝高斯格式不意味着高斯模型本身损坏。它不能充当将来的 PLY 高斯校验器。

## 拍摄到修改必须遵守的边界

横向移动需要产生真实视差，不能只站在原地转手机。拍摄时保持表情和头部相对稳定、使用相同镜头和尽量均匀的光线；录制帧与内外参必须同步。重叠视角与稳定照明是多视图重建的基本条件。[COLMAP 官方教程](https://colmap.github.io/tutorial)。这些是采集设计要求，尚未验证在人脸上的成功率。

短距离横移只覆盖局部角度，不能凭空生成未拍到的后脑、耳后或遮挡区域。只在实际覆盖的视角范围观察，缺失部分明确标注；不能用通用头模填补后称为用户真实面容。头部运动、眨眼、头发、镜片及皮肤反光都必须以真实数据评估。

不自动磨皮、对称化或删除斑痕。质量检查评估模糊、覆盖、跟踪及重建可信度，不评价美丑。默认光效、粒子只在背景；原貌与修改用相同相机、材质和曝光。

保护区域在网格路线按资产版本+UV/三角形约束；在高斯路线必须重做选区与保护定义，不能直接套用示例 lip.mask。模型重建、点重排、UV 重铺或拓扑变化必须产生新资产版本，旧选区不可静默沿用。

## Blender 与网格备选

Blender 可作为离线检查、坐标规范化、UV 整理、贴图打包及 GLB 导出工具，不是手机横移视频自动重建的替代品。COLMAP 4.2.0 官方文档列出了 SfM/MVS、网格与纹理图集流程；这是候选工具，未安装、未执行个人重建。[固定版本教程](https://raw.githubusercontent.com/colmap/colmap/4.2.0/doc/tutorial.rst)。本机只检测到 Intel Arc 140T，不能默认 CUDA 可用；4.2.0 增加 AMD HIP 也不等于支持此 Intel GPU。[版本说明](https://github.com/colmap/colmap/releases/tag/4.2.0)。

OpenMVS 提供纹理网格重建，项目标注 AGPL-3.0；未引入代码或运行包，不能把其许可和设备适配当已完成。[官方仓库](https://github.com/cdcseacave/openMVS)。网格路线仅在原生高斯严格编辑门槛无法满足时重新比较，不同时扩建两套产品管线。

## 下一道完成门槛

保留原版 UI，在目标真机验证一份真实拍摄数据：能力查询 → 采集 → 重建 → 原件保存/读回 → 旋转 → 前表面圈选 → 限定上色 → 保护不变 → 撤销 → 保存重开 → 无 UI PNG。记录机型、OS/API、文件样本和像素证据。任何一项失败就不得称完整原生 SELF 可运行。当前原生 3D 显示异常与 scene manager 失败仍未解决；个人拍摄、重建和编辑尚未实现。

