# 拍摄、面容锚点与 Remy 参考核验 · 2026-09-23

本轮在既有工程上增量实现；包名 `com.self.mirror`、签名配置、作品、模型授权和主渲染器保持原有路径。调试对象是 MatePad Pro 13 / HarmonyOS 7.0.0.106 / API26 / x86_64 平板模拟器，设备 `127.0.0.1:5555`。构建使用 DevEco 26.0.0.821、商业 SDK26.0.0.105。没有以浏览器或 Previewer 代替设备验收。

## 已实现的拍摄路径

打开顶部常驻相机图标，等取景就绪后点击底部圆形快门；再次点击保存无声 MP4。返回主界面，设置 → 采集记录 → ▶ 可在应用内播放。最长每段30秒；软件录像过程中横竖屏改变尺寸时先保存当前片段，再重新准备新方向。关闭未结束的录制会取消该片段，不删除以前保存的视频。

当前模拟器只枚举 AAC 音频编码器，没有系统视频编码器。此前因此禁用的快门现有真实软件采集路径：Camera Kit 的第二个 PreviewOutput → ImageReceiver → ImageKit 方向/尺寸/像素格式处理 → N-API 异步任务 → H.264 → MP4。没有录制界面截图，也没有输出空文件代替成功。支持设备仍优先走 AVRecorder；该硬件路径尚未在真机验收。

ImageReceiver 使用 SDK 要求的 JPEG 占位枚举，实际像素格式以 Camera Profile 为准；当前设备返回 RGBA8888（3），不是 JPEG 压缩图。代码另处理 NV21（1003）和行步长，其他格式明确失败。最长边限制960，录像时间轴取实际采集时间，不写虚假30帧/秒。只允许一个帧任务在途；检测最多约10次/秒，录像独立调度，忙时舍弃旧帧，避免堆积。

**不需要让 Windows 桌面或相机应用分辨率与平板一致。** 使用设备实际提供的1280×720规格。原生 Surface 预览按 Camera Kit 方向补偿并等比裁切。帧读取路径发现模拟器 RGBA 图像与预览上下相反，已增加仅针对该模拟器路径的翻转修正；修正后的横竖屏像素与前后摄像头逐项人工对照仍未完成，不能把“窗口旋转通过”写成“所有图像方向均已验证”。

## 识别与引导

不再依赖当前模拟器缺少的 CoreVision face detector，也不再从 XComponent 截图读相机。内置固定版本 libfacedetection，在本机 CPU 上检测真实相机帧中的人脸框和5个关键点。没有身份识别、情绪推断、网络上传或调试图像落盘。

- 搜寻状态是较大的细环；连续获得稳定单一候选后，约440ms收拢为22–38vp的小环。
- 锚点取鼻尖关键点，按预览的等比裁切映射到屏幕；邻近匹配、大小约束和自适应平滑抑制跳动。
- 多个模糊候选不任意选择；短暂丢失容忍后展开搜索，不继续假装锁定。
- 眼部连线控制平面倾角，鼻尖与双眼关系控制小环的近似椭圆变化。**这是二维几何引导，不是经标定的3D姿态或世界空间锚点。**
- 开始拍摄时短暂出现原创“人物＋移动手机”的线条动画，提醒缓慢横向取景；没有虚构重建进度。

用户已明确“稍后再测真人跟踪”。本轮不把公开样本检测、合成轨迹测试或零人脸相机帧，冒充真人转头时的贴合验证。侧脸、遮挡、快速移动、多人切换、低光和不同肤色的稳定性均待验证。

## 实际观看的参考视频

用户提供的本地视频为7.933秒、1280×592、30fps、238帧。以每秒4帧检查全片，并在约1.8–4.3秒的手机取景段以每秒8帧放大检查。视频标题为“高清人像＋空间重建模式 Remy1.5正式上线”；不据此认定1.5就是目前最新版本。

可以观察到：全屏取景、小白色人物锚点、“将锚点对准人物正面”、红色快门、拍摄后控制层淡出、“从正面慢慢拍摄到一侧”的人物与手机引导。未展示完整的大圈检测收拢过程、最终重建结果或背景虚化。因此大圈收拢结合用户描述自主实现，不宣称逐像素或算法一比一复刻。原视频与截帧只供本地参考，没有进入应用资源、Git证据或交付包。

相关一手材料： [Remy官网](https://www.remy3d.cn/)、[同标题发布视频](https://www.bilibili.com/video/BV1HEFQzwEsq/)、[华为 Remy 支持说明](https://consumer.huawei.com/cn/support/content/zh-cn16076523/)。网页播放器此前受工具限制无法打开；本轮实际观看依据为用户提供的本地视频。

## 建模和背景的边界

当前 MP4 保留相机采集到的完整画面及背景，不把应用控件录进去。**个人3D重建、背景空间重建和背景分离虚化尚未实现。** 不能用圆形模糊蒙版或示例头像声称已经扫描人物。

重新核对商业 SDK `hms/native/sysroot/usr/include/spatial/spatial_recon_interface.h`：SpatialRecon 的输入包括图像、相机内参、位姿、时间戳，或 AR Engine 帧；有设备支持查询和801不支持状态。保存一段普通 MP4 并不自动满足这些输入。现有采集元数据明确写 `poseData:false`、`reconstructionStatus:not-reconstructed`，当前模拟器也未建立受支持的重建运行链。

[官方空间渲染接口](https://developer.huawei.com/consumer/en/doc/harmonyos-references/spatial-recon-spatialrender)提供 GSNode / API26 TiledGSNode 等3DGS能力；[重建写入格式](https://developer.huawei.com/consumer/cn/doc/doccenter-capabilities/api/capi-spatialrecon-hms-spatialrecon-modelwriteinfo)与普通可编辑GLB网格不是同一资产契约。3DGS结果不能直接冒充现有GLB局部编辑管线输入。未找到可据以保证当前设备背景景深效果的公开接口证据，也未采用 Remy 私有接口或 Blender 文件作为设备运行格式。

后续接入需先在支持设备验证图像/位姿同步、真实重建输出与加载，再验证人物/背景分离和显示阶段的景深。原始采集保留背景，虚化应非破坏性地作用于展示，避免把失焦信息永久写进重建输入。该路线目前是待验证方案。

## 测试证据

| 范围 | 结论与证据 |
|---|---|
| 商业SDK构建 | 生产与ohosTest构建通过；arm64-v8a和x86_64均链接。见 [最终构建](evidence/camera-tracking/final-build/hypium-build.log)及 [生产构建](evidence/hap-build.log)。未签名debug包，不代表真机发布验收 |
| 原有政策/原生UI | 14/14通过，包括圈选、保存重开、PNG、模型授权边界。见 [回归日志](evidence/camera-tracking/regression/hypium-results.log) |
| 原生检测/编码 | 2/2通过：真实CNN识别公开扫描样本、空白负例、5关键点；实际H.264编码和MP4封装；锚点获取/移动/丢失/多人逻辑。见 [结果](evidence/camera-tracking/native-final/results.log)及 [数值日志](evidence/camera-tracking/native-final/camera-events.log) |
| 公共视频解码 | 模拟器生成12帧、384×512、1.8秒MP4；宿主ffprobe读取正常、ffmpeg完整解码退出0。见 [公共样本视频](evidence/camera-tracking/native-final/public-fixture.mp4)及 [流信息](evidence/camera-tracking/native-final/ffprobe.json)。这是编码验证，不是实拍帧率 |
| 平板真实相机 | 最终4/4通过：全屏横竖屏/重开/前后台恢复、真实录制保存＋本机解码＋应用内回放、旋转保存片段、面板/强调色/语言。见 [最终相机套件](evidence/camera-tracking/tablet-cadence/results.log)。测试只删除自己新建的采集，保留原有视频 |
| 真人跟踪 | 未验证；按用户要求稍后安排 |
| 所有相机方向的像素对照 | 未完成；预览布局旋转和录像尺寸变化已测，不等同于前后镜头所有方向视觉正确 |
| 真机、长时性能/温度/耗电、最低兼容版本 | 未验证；arm64编译成功不等于真机通过 |
| DeepSeek真实调用 | 本轮未重测，没有发送任何摄像头画面；先前模型证据保留，不能计作本轮新通过 |
| 个人3D、背景重建/虚化 | 未完成 |

最终本机实际录像：960×540，50帧/4.264秒，约11.73fps；旋转前片段27帧/2.401秒，约11.25fps，详见 [数值日志](evidence/camera-tracking/tablet-cadence/camera-events.log)。比最初独立限频前约8.35fps有所提高，但没有达到30fps，也没有经过持续负载测试，不能宣称流畅采集或推广为真机性能。

私密录制测试在应用沙箱内解码，未导出其画面；只保留尺寸、帧数、时长等数值日志。早期人工方向检查的临时影像已删除。证据里的视频和脸部坐标全部来自已有公共扫描资产，另有许可署名。

## 遇到的失败与修复

1. 系统无视频编码器：保留真实失败事实；增加软件H.264/MP4采集，不伪造AVRecorder成功。
2. 从相机Surface读PixelMap失败7600104：改用真实相机生产者的ImageReceiver队列。
3. RGBA再转RGBA失败62980115：格式相同跳过转换；按真实Profile处理像素和步长。
4. minih264按C++编译失败，两个单文件库在同一C单元出现静态符号冲突：使用两个独立C翻译单元，未改上游实现。
5. 早期自动化在说明卡已打开时再次点击导致找不到状态组件：改为检查可见状态；[初次失败记录](evidence/camera-tracking/initial/results.log)保留。
6. 相机帧与预览上下相反：增加限定模拟器的修正；完整方向视觉复核仍列为未完成。

## 复现

```powershell
./scripts/Test-Native.ps1 -Device 127.0.0.1:5555
./scripts/Test-DeviceSuite.ps1 -Device 127.0.0.1:5555 -Suite SELFNativeCameraPipeline -ExpectedTests 2 -Evidence artifacts/camera-pipeline-check
./scripts/Test-DeviceSuite.ps1 -Device 127.0.0.1:5555 -Suite SELFNativeCamera -ExpectedTests 4 -Evidence artifacts/camera-check
./backend/.venv/Scripts/python.exe scripts/Check-Camera-Dependencies.py
./scripts/Install-Emulator.ps1 -Device 127.0.0.1:5555
```

相机套件会短暂使用真实宿主相机，录制后只删除测试自己产生的片段。私人视频、密钥和参考视频不进入交付；依赖版本、逐文件哈希、实际改动与许可见 [依赖清单](../shared/camera-dependencies.json)和 [引用记录](references.md)。
