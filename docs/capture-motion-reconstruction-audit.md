# 拍摄引导、重建缺口与移动算力审查 · 2026-09-23

> 后续更新：[端侧 3DGS 保真审查与实测](device-3dgs-fidelity-review.md)替代本文的最新实现状态和降分辨率/固定关键帧预算建议。现已实现重建会话控制器，完整个人建模流程仍未接通；本文保留为此前阶段的实际记录，不能把其中“只有 IsSupport”作为当前代码结论。质量和本人细节优先于降低计算开销。

本轮沿用现有项目、包名、签名配置和作品，不重写工程。用户选择：**设备端重建，之后用支持的真机验证**；不增加 Windows 或云端重建后端。真人移动跟踪按用户安排暂缓。

## 根因与当前边界

上一版 `CameraCaptureView.record()` 结束后只保存视频并刷新采集列表，**没有启动重建**。`RendererSession` 只有 `RECON_SUPPORT` 动态库与设备能力查询，没有 CreateSession / PushFrame / StartSession / SaveModel 调用；相机输入也没有标定内参和同步的真实位姿。这是应用缺失，不能归咎于用户操作。

当前 API26 平板模拟器又缺少 `libspatial_recon_ndk.z.so`，实际探针为 `available:false, libraryLoaded:false`。两项障碍独立存在。换支持的真机也不会让尚未实现的应用流程自动完成。

本轮明确返回 `pipelineImplemented:false`，拍摄后显示“尚未生成3D面容”，在说明中展示真实失败原因。没有把保存 MP4 当作建模成功，没有自动关闭相机后换上公共头像。**用户要求的“拍摄→个人3D→退出相机→主界面替换”仍未实现。** 当前仅保留已有录制能力，公共示例继续标记为示例。

## 实际改动

- 把原先固定4秒消失的提示改为 `CaptureMotionGuide`：只在连续稳定的人脸观测出现横向位移或近似转向后收起；小抖动、纯缩放、点头和单帧跳变不推进。连续丢失后重新寻找。该状态机是二维关键点相对运动，**不是空间位姿或同一身份保证**。
- 人物与移动手机的原创线条动画放大到最高360vp，居中显示。动画收起时大圈约440ms收拢到鼻尖附近22–38vp小圈，随后随跟踪更新。减弱运动设置关闭时不播放缓动。
- 回正改为画面左侧圆形玻璃图标；沿原生 VSync 渲染循环约420ms回到初始视角。新触摸会接续当时的实际视角；关闭动效则立即回正。
- 全屏相机打开时暂停背后原生镜面及粒子渲染，关闭相机后恢复，避免两条图形流水线持续争用资源。
- 保留现有本地检测单任务、最新帧读取、最多约10Hz检测、软件录像最长边960及每段30秒限制。它们是现有采集约束，**不是最终重建图像质量规格**。

## Remy 参考的实际范围

再次检查用户提供的7.933秒视频及取景段连续截帧：人物正面锚点、居中的人物/移动手机提示、开始拍摄后的控制层淡出可见。视频没有展示完整重建、最终画质与后台算法，不能证明某条实现就是 Remy 私有方案。原创图形和交互只参考可见动作；未将视频、截帧或其图标打入产品。

[Remy官网](https://www.remy3d.cn/)没有提供本次所需的可复用重建内核、算力上限或完整代码。没有将其宣传画面作为 SELF 真机性能证据，也没有承诺逐像素复刻未出现在参考中的动画。

## 商业 SDK 与路线取舍

实际安装：DevEco26.0.0.821 / SDK26.0.0.105。读取 `hms/native/sysroot/usr/include/spatial/spatial_recon_interface.h`、`hms/native/sysroot/usr/include/ar/ar_engine_core.h`、`hms/ets/api/@hms.graphics.spatialRender.d.ts`、`@hms.graphics.spatialEdit.d.ts`；没有复制 SDK 实现或把 OpenHarmony 版本表当作商用设备承诺。

| 候选 | 依据 | 取舍与未完成项 |
|---|---|---|
| 华为 SpatialRecon + AR Engine | 商业头文件提供输入图像/内参/位姿/纳秒时间戳，或 PushARFrame；运行、暂停/恢复、保存与设备查询接口 | **端侧首选验证方向**。需实现并在支持设备核实相机所有权、AR追踪、时间同步、回调与产物加载；当前均未接通 |
| API26 GSNode / GSEdit | 商业声明含 selectBy2DMask、selectByIndex、paint、undo、saveToPLY、extract3DMainBody | 优先验证直接编辑重建产物，避免默认再训练/提取另一份网格。蒙版遮挡、软边、保护、检查和账单尚未适配，不能直接接管现有 GLB 编辑 |
| TiledGSNode | 官方分块加载接口按视角加载场景数据 | 可研究背景大场景显示；**减少显示资源不等于减少重建计算**，不必为小型人像强行分块 |
| PocketGS | 论文报告 iPhone15 / Apple A16 / Swift+Metal，约4分钟、峰值低于3GB的端侧实验 | 参考关键帧筛选、几何先验、内存/计算协同设计。不是 HarmonyOS 库，未移植，论文数字不作为 SELF 预算承诺 |
| Mobile-GS | 面向移动端的高斯渲染和压缩研究 | 用于显示优化参考；不能据此声称手机已完成重建 |
| Blender / 桌面 SfM / 云端服务 | 本轮未采用 | `.blend` 不是运行时格式；用户已选择端侧路线，不将拍摄数据转交 PC 或第三方 |

公开依据：[华为空间渲染](https://developer.huawei.com/consumer/en/doc/harmonyos-references/spatial-recon-spatialrender)、[分块术语](https://developer.huawei.com/consumer/cn/doc/HarmonyOS-Guides/spatial-recon-glossary)、[模型写入说明](https://developer.huawei.com/consumer/cn/doc/doccenter-capabilities/api/capi-spatialrecon-hms-spatialrecon-modelwriteinfo)、[PocketGS v5 §IV–V](https://arxiv.org/html/2601.17354v5)、[Mobile-GS](https://arxiv.org/abs/2603.11531)。部分华为开发指南网页正文无法读取，具体签名以以上本机商业 SDK 为准。未采用博客芯片白名单作为兼容保证。

### 文件与编辑必须一起验收

SpatialRecon 本机头文件输出枚举为 PLY/MP4，模型类型为 GS；GS 的 PLY 不是普通三角网格，也不等于现在的 UV GLB。即使容器同为 GLB，也不能推断内容是可供现有着色器使用的网格。保留原始 GS 资产，附版本、采集配置、坐标系及操作记录；不能只改扩展名转换。

官方 `GSEdit.paint` 的存在也不证明可以直接实现自然化妆。必须先验证可见表面选区、软过渡和颜色空间；所有新外观操作仍需大模型候选与用户授权，并通过原生检查才提交账单。保护原貌、撤销、PNG和重开应对同一产物成立。若不能满足，不把“可显示3D”计作“可编辑个人3D”。主体提取返回801等失败时，保留原资产，不用圆形模糊蒙版伪装背景分离。

## 移动端执行方案（待实现/待真机测量）

1. **进入前探测**：分别检查 AR 采集、重建、GS 渲染和编辑能力；API26只是接口版本。核对可用内存、私有存储和温度；记录真机型号与系统构建。只在通过设备上开放建模。
2. **采集阶段**：预览与检测独立分辨率；保存清晰、具有新视角的有效关键帧及其真实位姿，不把整段视频逐帧解码、全部留在内存。硬件采集/编码优先；当前软件录像仅是模拟器兼容路径。人保持自然且尽量稳定，镜头移动；头部自身转动不等于有相机轨迹。真实面部表情变化须单独评估重建失真。
3. **重建阶段**：结束采集并释放相机/编码/检测，暂停其他3D动画；单个后台任务执行 SDK 重建，UI只显示实际状态。按实际 SDK 配置前后台运行模式。高温暂停、低内存/空间不足可取消或重试，不能丢掉已有作品。不得将关键点推测的角度伪造为 AR 位姿。
4. **成功提交**：只有 SDK 成功且文件校验、真实加载和多角度检查通过，才原子替换主界面并退出相机。取消/失败保留当前作品，半成品不登记为成功资产。先完成这个闭环，再添加背景非破坏虚化。
5. **显示阶段**：小人像先测单 GSNode；大型背景才评估分块/LOD。旋转交互优先，空闲和不可见时停止高频渲染。先压低背景/装饰负载，不能用磨皮、修改“缺陷”或虚构纹理掩盖预算不足。

初始实验上限可从30秒采集、60–120张关键帧、720p/1080p两档开始，**只是测试档位，不是厂商要求或已接入参数**。120张1920×1080 RGB若全解码常驻约712MiB，还不含副本、GPU纹理与训练缓存，因此必须流式输入并明确释放。现有960像素软件录像不能直接等同于满足高精度重建的输入。

真机应分别记录采集延迟和丢帧、重建总时长/峰值RSS及GPU内存、10分钟连续操作温度与耗电、冷/热状态下的显示帧间隔、模型大小，以及鼻翼/耳缘/发丝/痣雀斑等细节是否来自本人。是否达到30fps或交互60fps由实测决定，不以模拟器、编译通过或厂商论文代替。根据首台支持设备的数据再确定最低支持设备及预算，暂不宣称“最优”已获证实。

## 本轮测试

当前调试对象为 MatePad Pro13 / HarmonyOS7.0.0.106 / API26 x86_64，`127.0.0.1:5555`。未使用浏览器代替鸿蒙测试。**最终复测被模拟器断连与启动后退出阻断，不能将下面早期通过项写作最终全套通过。**

- 原生政策与界面回归：15/15通过，含新的边缘回正按钮、回正后实际视角保存、圈选、PNG和作品重开。[结果](evidence/capture-motion/regression/hypium-results.log)
- 原生公开样本CNN/编码与运动状态机：首次5/5通过。新增独立纯色测试页用于图形视觉验证，不读取相机画面。[首次结果](evidence/capture-motion/pipeline/results.log)
- 初次相机套件：2/4通过，录制/解码与旋转保存通过；另两项因未等待录制就绪、语言刷新而失败，已改为等待明确状态。[保留失败日志](evidence/capture-motion/camera/results.log)
- 初次无相机视觉截图尝试失败：普通测试函数没有组件上下文，`createFromBuilder`无法执行；改为测试HAP内的独立UI页面，不将专用页面打入生产HAP。自定义测试页面还需显式TestRunner；保留早期构建/运行失败日志。
- 测试页面后续遇到缺失Runner、UiTest驱动初始化时序、未注册AbilityMonitor的问题；最后补上AbilityMonitor并构建通过，但设备随后断连，**最新Runner和6项完整套件尚未验证，也没有成功获取新动画视觉证据**。[失败运行](evidence/capture-motion/pipeline-final-pass/results.log)、[最新测试构建](evidence/capture-motion/verified-build/hypium-build.log)
- 最终生产HAP构建通过（arm64-v8a、x86_64），见[生产构建](evidence/hap-build.log)。最新源代码比15/15回归时增加了相机失焦计时器复位和错误说明修正；最后构建的覆盖安装未完成。没有清空数据、重建镜像或卸载应用。
- **未完成/未验证**：个人3D全链路、真实面容小圈贴合、所有镜头方向像素对照、真机、热/耗电/内存预算、长时流畅度、3DGS圈选编辑与背景分离。本轮没有新 DeepSeek 调用，也没有上传摄像头画面。

断连后尝试调试桥重连，以及同一平板的保留数据冷启动（含官方无窗口模式），仍未恢复；启动进程退出0但未留下可连接设备，因此不据此臆测是应用或宿主哪一项故障。已请用户从DevEco重新打开并提供错误文字。重启调试桥后，设备恢复还需重新建立后端映射：`hdc -t 127.0.0.1:5555 rport tcp:8787 tcp:8787`。没有改动后端密钥。

## 复现

```powershell
./scripts/Test-Native.ps1 -Device 127.0.0.1:5555 -Evidence artifacts/motion-regression
./scripts/Test-DeviceSuite.ps1 -Device 127.0.0.1:5555 -Suite SELFNativeCameraPipeline -ExpectedTests 6 -Evidence artifacts/motion-pipeline
./scripts/Test-DeviceSuite.ps1 -Device 127.0.0.1:5555 -Suite SELFNativeCamera -ExpectedTests 4 -Evidence artifacts/motion-camera
./scripts/Install-Emulator.ps1 -Device 127.0.0.1:5555
```

相机测试短暂使用宿主摄像头，只在应用沙箱内录制和解码；只删除测试自己创建的片段。视觉测试页为纯色背景和生产组件，不代表真人跟踪或建模。
