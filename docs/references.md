# 实际引用与许可

## 当前原生与模型增量（2026-09-22）

最新规范已取代旧 Web 主引擎及 Remy/3DGS 的生产方向，以下新增项实际用于当前原生版本。其余章节保留历史来源，不代表仍运行旧引擎。

| 固定来源 | 实际文件 / 修改 / 许可 |
|---|---|
| [cgltf v1.15](https://github.com/jkuhlmann/cgltf/tree/v1.15) | `entry/src/main/cpp/vendor/cgltf.h` 原文未改，SHA256 `e378a21c084bf1f288bb799de827bb26906efb024255f1ecf1705ea13f11c6ec`，MIT 原文内嵌；只用于 GLB 解析。SELF 另写加载、图片、材质与绘制，未复制产品示例 |
| [nlohmann/json v3.11.3](https://github.com/nlohmann/json/tree/v3.11.3) | `vendor/json.hpp` 原文未改，SHA256 `9bea4c8066ef4a1c206b2be5a36302f8926f7fdc6087af5d20b417d0cf103ea6`；MIT 原文在 `licenses/nlohmann-json-MIT.txt`，只用 JSON 校验与序列化 |
| 实际商业 SDK26.0.0.105 headers | SurfaceHolder、FrameNode、EGL/GLES3、NativeVSync、Native Image、N-API、NetworkKit；只读取调用声明，未复制 SDK 进入交付包，依本机工具许可使用 |
| 官方 OpenHarmony 指南/源码 | 固定核对 commit 及路径见 `evidence/native-es3/reference-commits.json`；仅接口/初始化顺序交叉核对，不把其版本表作为商业 SDK 保证，不直接复制其整套实现 |
| [DeepSeek 模型表](https://api-docs.deepseek.com/quick_start/pricing/) / [Vision](https://api-docs.deepseek.com/guides/vision/) | 读取模型能力和 image_url 请求结构，自写 FastAPI/httpx 客户端与受限工具；没有下载模型权重，没有借模拟工具响应宣称真实接入完成 |
| 本项目自制测试图片、背景 shader、保护/选择算法 | EXIF彩色块、红圆/蓝方块测试图、环境粒子、业务协议均为本次自主实现，无第三方个人照片 |

Three.js0.186.0 及旧浏览器代码仅保留作迁移参照；示例 GLB 仍使用下文单独的 CC BY3.0 许可与署名。后端直接依赖/传递依赖精确版本见 `backend/requirements.lock.txt`，许可汇总见 `backend-dependencies.json`。

只使用新版提示词规定范围内的基础 API、参考思路和样本资产。来源文件与逐文件 SHA-256 保存在 [sources.json](../assets-src/LeePerrySmith-r186/sources.json)，不是只给一个仓库链接。

| 实际来源 / 固定版本 | 文件与用途 | 许可、修改与未采用部分 |
|---|---|---|
| [Three.js r186](https://github.com/mrdoob/three.js/tree/r186)，npm 0.186.0 | 核心 WebGLRenderer、Raycaster、GLTFLoader 及包内必需传递依赖；esbuild 打包本地 IIFE | MIT，原文置于 licenses/THREE-MIT.txt 并随 rawfile；无 CDN/整仓复制 |
| r186 `examples/webgl_decals.html` | 阅读 `loadLeePerrySmith`、外部 TextureLoader 贴图约定、Raycaster 最近表面拾取 | MIT，仅采用拾取/资产来源思路；未采用射击贴花、随机颜色、GUI、全窗坐标、灯光 |
| r186 `examples/webgl_multiple_scenes_comparison.html` | 阅读单 renderer/scissor 对照思路 | MIT；SELF 同场景、同相机、同曝光，显式事件与局部坐标，导出重置；未采用两种背景制造视觉差、隐式 event |
| r186 `examples/models/gltf/LeePerrySmith/LeePerrySmith.glb`、`Map-COL.jpg`、`LeePerrySmith_License.txt` | 真实公共扫描，17,684 三角形，9,279 顶点 | **资产为 CC BY 3.0，不是 MIT**。署名 Infinite, 3D Head Scan by Lee Perry-Smith; based on www.triplegangers.com。许可原文随 assets/LICENSE-HEAD.txt |
| 同上，SELF 制作脚本 | 嵌入原 JPEG、移除场景 camera/lamp、单 primitive unlit、保留扫描几何、生成显式 manifest/手绘 mask | 外部 TextureLoader 的 flipY=true 与 glTF 嵌入图的 flipY=false 不同，打包时做一次 V=1−V；记录 uvVersion。未宣称原扫描适合全表面编辑 |
| [Khronos glTF Validator](https://github.com/KhronosGroup/glTF-Validator)，npm 2.0.0-dev.3.10 | validateBytes，GLB/资源格式检查 | Apache-2.0 + NOTICES 复制到 licenses；另写 SELF UV/区域检查，格式通过不等于业务通过 |
| [glTF 2.0](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html) / [GLTFLoader](https://threejs.org/docs/pages/GLTFLoader.html) | 容器、嵌入资源、parseAsync 字节入口 | 规范参考；未复制整份文档。未采用 GLTFExporter 代码，采用本项目无损二进制重打包脚本 |
| DevEco 26.0.0.821 本机 New Project / New Module Stage 模板 | appTasks/hapTasks、json5 结构、EntryAbility loadContent、测试模块结构、默认 app_icon.png | 工具自带模板。未给模板另行套 MIT；按已安装工具许可使用，只复制初始化必要部分，业务界面和状态逻辑自主实现 |
| 同版本 SDK `@ohos.web.webview.d.ts`、文件/媒体接口定义 | 核对 WebMessageExt、WebMessagePort、applicationInfo.debug、PhotoViewPicker、fileIo | 以编译和 API 19 真模拟器运行确认；未直接复制官方 WebResourceResponse 的共享响应实现 |
| [OpenHarmony WebMessagePort 文档](https://github.com/openharmony/docs/blob/master/zh-cn/application-dev/reference/apis-arkweb/arkts-apis-webview-WebMessagePort.md) / [调试文档](https://github.com/openharmony/docs/blob/master/zh-cn/application-dev/web/web-debugging-with-devtools.md) | 接口背景参考 | 动态文档仅参考；实际调用签名固定到本机 SDK，未声称复制了某个未记录的 master commit |
| [OpenHarmony JsUnit 指南](https://github.com/openharmony/docs/blob/master/en/application-dev/application-test/unittest-guidelines.md)，Hypium 1.0.25 | 官方 describe/it/expect，Hvigor 自动生成 runner，aa test | Apache-2.0，包内 LICENSE 复制到 licenses；测试导入生产 SessionStore/PolicyEngine，不重新实现简化规则 |
| [OLAY Super Serum 美国官方资料](https://www.olay.com/products/super-serum)，核对 2026-09-21 | Original Size 1 oz 名称、地区、容量、使用说明的简短自主摘要 | 配方版本编号未公开。内部资料 ID 不是厂家 SKU；只允许品牌资料视图。未复制包装/实拍/临床图，未取得该素材复用许可，未宣称合作或效果标定 |

其他工具仅用于开发/验证：esbuild 0.28.2（MIT）、Playwright Core 1.63.0（Apache-2.0）、pngjs 7.0.0（MIT）；均不打进 HAP。锁文件提供实际依赖完整性。

2026-09-22 的新增设计参考：[HarmonyOS 7 官方产品页](https://consumer.huawei.com/cn/harmonyos-7/) 与 [HarmonyOS 设计理念](https://developer.huawei.com/consumer/cn/design/concept/)。仅阅读其光感、粒子、空间层次与柔和秩序的设计说明，没有下载/复制其图片、视频或系统实现。实际界面采用本机 API 19 支持的 ArkUI 材质模糊及自写 CSS；不能据此称已完成 HarmonyOS 7 全套材质适配。

新增原生音频使用本机 SDK `@ohos.multimedia.media.d.ts` 核对 AVPlayer 的 stateChange、fdSrc、prepare/play/release、loop、setVolume 和 timeUpdate，已实际编译与模拟器运行。`scripts/prepare-audio.mjs` 及三段 WAV 是本项目确定性生成的原创合成音轨，没有第三方录音或商业歌曲；来源与逐文件哈希在 `assets/audio/manifest.json`。柔和氛围、粒子、回复转场、轻转和音乐切换均为自主实现，不把官方示例当作成品直接套用。

紧急求助文本仅摘要 [WHO Suicide Q&A](https://www.who.int/news-room/questions-and-answers/item/suicide) 中联系急救、专业人员及可信任者的建议（核对 2026-09-21）。它不是风险诊断，未根据脸部或行为推断心理状态；本项目中文交互尚未经过独立心理健康专业审阅，不宣称完成该项发布验收。

未复用、未宣称接入：ArkGraphics 3D、MediaPipe 示例/模型、AnimationMixer/GLB clips、任意云模型、OLAY 标定着色器。普通静态 GLB 没有本项目的材质动画；本项目示意为独立原生色块时间轴。未验证的模块没有以“预留接口”计为完成。

公开官方示例用来理解原理。实际资源桥、坐标、蒙版、政策、保护锚点、文件持久化、导出和生命周期均为本项目实现，示例本身不作为产品适配验收证据。
# 2026-09-22 原生迁移补充

用户新指令优先原生、参考 Remy，并保留原版设计。新增 NativeMirrorProbe / NativeProbeAbility 为本项目编写的 SDK 调用与诊断代码，未复制官方样例实现。所用 Scene.load、Camera、Component3D、Node rotation 等声明来自本机 DevEco 26.0.0.821 / HarmonyOS SDK 26.0.0.105；SDK 文件未随源码包复制。

原生 SDK 文件、Remy 一手材料、格式分工和失败门槛详见 [native-reconstruction-review.md](native-reconstruction-review.md)。没有采用 Remy 私有 API 或代码，没有新增 Remy/KIRI 商业素材。Blender、COLMAP、OpenMVS 均仅作方案比较，没有引入运行依赖或声明已完成重建。


# 本轮大陆产品及原生交互补充（2026-09-22）

- 新增来源、实际 SDK 声明和使用范围见 [本轮实现说明](overhaul-implementation.md)。原生代码延续已有 C++ ES3 引擎；没有复制华为完整应用示例，没有引入 Blender、COLMAP、OpenMVS 或 Remy 私有运行包。
- 生产产品库已替换为 `shared/products/olay-cn-catalog.json` 的8条大陆渠道条目；上文美国 Super Serum 记录是历史引用，未把美国成分套用于大陆。品牌官网入口由宝洁中国官网确认；商品名称与部分规格来自京东自营旗舰店，明确标注渠道证据与未核实字段。
- `entry/src/main/resources/rawfile/products/{red-jar,white-pump,black-tube,black-jar,white-set,white-ampoule}.svg` 为本轮原创矢量类别插图。未使用网页产品图片、官方包装图形或临床图；名称用于识别，未宣称品牌合作。`serum.svg` 是既有自主示意资源，生产目录不引用美国旧条目。
- 后端模型候选与真实调用记录以 `model-contract.md` 顶部更新、`validation-overhaul.md` 为准；上文“未接入任意云模型”为更早阶段的历史状态，不适用于当前 DeepSeek 实现。

## 最新产品展示补充

产品 UI 已不使用上述 SVG。`scripts/build-product-models.py`、`ProductScene.cpp/.h`、`ProductCard.ets`、`ProductFactsDeck.ets` 为 SELF 自主实现，生成六组独立瓶身/盖子 GLB（贴图内嵌），逐文件哈希和原创声明见 `rawfile/products/3d/manifest.json`。未复制商业照片或官方包装图形；仅使用 OLAY 文字识别品牌。旋转、灯光和分体开合是真实原生渲染；几何、材质、盖子机构只是近似示意，并非实测商品参数。Arial 使用本机系统字体生成位图，没有分发字体文件。

本轮设计阅读 [华为设计官网](https://developer.huawei.com/consumer/cn/design)及 [HarmonyOS 7 官方页面](https://consumer.huawei.com/cn/harmonyos-7/)，采用柔和光感、材质层次、堆叠卡片和响应式布局的方向。未复制官方素材，未宣称获得官方设计认证或已经验证真机流畅度。实现使用本机商业 SDK26 的 ArkUI 与 GLES3，不用 OpenHarmony 示例版本表证明商业兼容。

本轮相机、对话与背景使用范围见 [对话与平板相机核验](interaction-camera-validation.md)：本机 API26 Camera Kit/Media Kit 的声明与官方说明核对，原生采集类、GLSL 氛围和圈选反馈自主实现；没有复制 SDK 文件或新第三方资产。


## 2026-09-23 全屏采集与设置

新增 `rawfile/ui/{camera,settings,atmosphere,music,music_off}.svg` 为本项目原创路径图标；未使用华为系统图标文件、Remy 视频画面、网页图片或第三方包装资产。CameraCaptureView / LocalFaceGuide / UiPreference / UiText 和方向/动画修改均为项目实现，未复制 SDK 声明或官方示例。

核对入口：[华为相机旋转术语](https://developer.huawei.com/consumer/cn/doc/doccenter-capabilities/camera-rotation-term-native)、[窗口旋转](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/window-rotation)、[Remy 机型支持说明](https://consumer.huawei.com/cn/support/content/zh-cn16076523/)。动态页面部分正文超时，实际接口以安装的商业 SDK 声明、编译及平板运行核验。搜索到 [Remy 演示](https://www.bilibili.com/video/BV1vEAaz3EvG/)，网页返回412，内嵌浏览器超时，未能完整观看；不声称逐帧复刻或复用其跟踪/重建算法。环形引导为原创交互，不能当作成功重建进度。
