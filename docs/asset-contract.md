# 原生资产与旧作品协议

生产资产：自包含 glTF 2.0 GLB + manifest + UV 蒙版。`.blend` 是外部创作工程，PLY/3DGS 是不同表示，均不直接加载或改名当 GLB。本版不提供扫描、个人重建或高斯渲染器。

`GltfAssetLoader.cpp` 的受支持子集：一个静态 mesh/primitive/实例、索引三角形、POSITION/NORMAL/TEXCOORD_0、PNG/JPEG 内嵌 opaque 基底、neutral baseColorFactor；可带 KHR_materials_unlit。cgltf 解析 accessor 偏移、stride、component/normalized、索引类型和节点层级变换；SELF 实现缓冲、解码、材质、上传和绘制。sparse/skin/morph/动画/Draco/其他扩展/多 primitive 在加载前拒绝。此限制应在外部制作阶段统一转换，不能宣称任意 GLB 都兼容。

固定示例为 Lee Perry-Smith 公开扫描，9,279 顶点、17,684 三角形，1024² 原 JPEG。署名及 CC BY 3.0 原文随包；不是用户个人模型，也不是球体占位。预处理 `prepare-assets.mjs` 保持原几何，将 JPEG 内嵌并按原外部贴图约定转换一次 V；来源、哈希和版本在 assets-src、manifest 中。

manifest 的 `baselineKind: bakedAppearance` 对应本规范 BAKED_APPEARANCE：照片已含光照，Native unlit 重现；纹理解码至线性空间进行有界混色，再编码 sRGB。背景光晕/粒子仅装饰环境，不能称皮肤材质仿真或任意光照下的真实产品功效。未标定产品不开放效果模拟。

示例 UV 在头部其他区域存在重叠，因此只允许已验证的 `editable.mask` 区域编辑。所有手工圈选与效果蒙版均再与 editable 相交；不是全头任意编辑。每个 region 绑定 asset/version、mesh0/primitive0/UV0、uvVersion、textureVersion、宽高。蒙版是实际单通道字节而非空 ID，保存在本地并随作品复制。

## 圈选和保护

冻结本笔视角；ArkUI vp 转归一化视口，三角形 UV 内逐纹素映射到投影位置，闭合轮廓做内部填充，再用 BVH 最近射线三角形判定遮挡。不是把 UV 边界连线。只有结束时计算，不每帧全图读回。

目标内三像素羽化，零值不向外扩张，mask NEAREST、无 mip；示例额外限制 editable。保护优先恢复原貌或明确的已提交锚点。例外授权绑定具体 operationId 与 protection ruleId，仅该项可以在自己的目标与保护交集内生效，后续层不继承，也不删除长期偏好。

每次候选离屏对比当前有效结果；保护区和非授权区分别逐 RGBA8 像素检查，阈值为0，失败不切换屏幕、不记成功账单。检查是当前视角、720宽等比图，不是所有未来视角的穷尽证明；其他视角依赖相同 mask 约束，还需更多接缝/鼻侧/遮挡样本验证。

## 照片

PHOTO 是同一 Native 渲染器的平面，不是 3D 重建。实际 EXIF1–8、33×49 奇数宽 PNG 在 API26 已验证；目前只支持 opaque PNG/JPEG。用户自己圈出唇区并确认，必须排除口腔、牙齿与皮肤；没有自动精密分割或根据模型自然语言生成蒙版。照片 pan/zoom，禁止把平面旋转假装多视角重建。

## 保存与迁移

包名 `com.self.mirror`、schemaVersion1 作品目录和偏好沿用；新增 scene/region/texture/renderPipelineVersion 字段均可选读取。操作仍保存绝对参数，从原基底重算。保存前从 Native 获取真实相机；新保存分配新 work-ID，不覆盖旧文件。

旧作品无 pipelineVersion 时会说明“按原操作重算，新旧像素一致性未逐作品验证”。不能正确匹配 asset/UV/尺寸时拒绝恢复，保留原文件。无卸载、清数据或自动删旧作品。例外授权随作品操作保存，长期保护文件只保存保护规则。

导出为同管线 RGBA8 FBO → Native Image PNG，关闭圈线、比较分屏和 UI。`files/self-export.png` 是应用私有文件，每次覆盖；尚未宣称已写入系统相册或公开分享。模型两张快照分别为干净有效图和同视角区域标注图，精确 UV/GLB 不上传。
