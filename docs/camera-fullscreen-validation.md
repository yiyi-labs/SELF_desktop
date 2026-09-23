# 全屏相机与交互验收 · 2026-09-23

本次增量保留包名 com.self.mirror、签名配置、作品、用户数据和原生渲染器。调试仅在当前 MatePad Pro 13 / HarmonyOS 7.0.0.106 / API26 / x86_64 平板模拟器进行，设备 127.0.0.1:5555；端口本身不代表设备类型。没有使用浏览器测试冒充设备测试。

## 相机方向与使用

**不需要把 Windows 桌面或 Windows 相机应用的分辨率调成和平板一样。** 当前 Camera Kit 实际返回 1280×720 / 30–60 fps 配置；应用使用支持列表中的匹配配置。Windows 摄像头权限和官方镜像 camera.feature / camera.front.back.enable 已开启，这轮没有修改全局驱动或相机配置。

旧版固定 280vp 预览没有调用方向补偿接口。新版在原生 PreviewOutput 上调用 getPreviewRotation(display.rotation×90)、setPreviewRotation(rotation,false)，监听 display change 并注销；ArkUI 只按旋转后的长宽比等比居中裁切，避免额外 UI 旋转和拉伸。录像开始前更新容器方向元数据，但编码成功路径尚无本机证据。

打开 SELF → 顶部相机图标（始终保留）→ 直接全屏取景。顶部返回关闭，底部是快门与切换镜头；“ⓘ”收纳采集说明及设备限制。回到前台会重建有效预览，退出释放资源。采集记录在设置中管理。没有新个人模型时保留原作品，不会把视频替换成示例 GLB。

中央细环与慢速环绕点是拍摄引导，不是扫描完成度。Camera Kit 的 MetadataOutput 只在设备报告支持时启用；另有 CoreVisionKit 的本地限频单帧检测补充路径。两者都不支持时保持对齐引导，不能显示已锁定。摄像头图像不会发送给 DeepSeek，不留存用于调试的私密影像。

## 界面增量

- 氛围、设置和操作卡记录点击坐标，受窗口边界约束，从触发位置缩放展开/收起；圈选对话继续在所选区域附近出现。
- 加入半透明模糊、细高光边缘和柔和阴影，按钮按下反馈，氛围颜色在现有 NativeVSync 线程中渐变。没有引入第二套渲染循环。
- 三种背景氛围以图形预览，强调色提供雾紫、玫瑰、青绿、琥珀，控制按钮/选中状态/开关。强调色不改变面容像素，不经过模型修改作品。
- 设置集中语言、隐私、采集记录、作品和应用说明。界面主操作、产品卡操作及后续模型回复支持中英文；产品官方名称、用户原话、既有作品和部分运行诊断保留原文。偏好单独存储，不保存云端授权或自动打开音乐。
- 新相机/氛围/音乐/设置 SVG 为原创图形。未复制 Remy 画面、SDK 代码或华为图标资产。

## 本轮真实结果

| 项目 | 结果与证据 |
|---|---|
| 商业 SDK26 构建 | arm64-v8a + x86_64 构建通过；存在最低兼容版本提示、未签名提示，不能据此保证 API19 或真机 |
| 原有政策与 UI 回归 | 14/14，包含真实圈选、保存/重开、PNG、只删除测试作品；[日志](evidence/camera-fullscreen/tablet-release/hypium-results.log) |
| 全屏相机/方向/恢复/重开 | 通过：横竖屏布局、预览等比铺满、前后台恢复、两次重开、常驻入口；[最终套件](evidence/camera-fullscreen/tablet-final/results.log) |
| 新设置与面板定位 | 通过：触发位置约束、强调色持久化、英文/中文即时切换与保存；同上套件第二项 |
| 后端约束 | 31/31，包括新增英文显示与权限边界；[日志](evidence/camera-fullscreen/backend-tests.log) |
| 真实英文 DeepSeek | 通过：公共示例图 + 合成“保留痣、只聊天”输入，英文回复，无编辑/无产品推荐；[结果](evidence/camera-fullscreen/live-english.json) |
| 平板真实模型闭环 | 复测通过：静态示例图 → DeepSeek → 确认 → 原生提交 → 账单一项 → 后续发送不重复弹框 → 撤销；[日志](evidence/camera-fullscreen/tablet-model-retest/results.log) |
| MP4 录像 | **当前模拟器不可用**。getAvailableEncoder 仅 AAC 音频，无视频编码器。快门禁用，未伪造成功文件 |
| 实际人脸检测/跟随 | **当前模拟器不可用**。supportedMetadataObjectTypes=[]，CoreVision face detector syscap=false；真实跟随分支已编译，未在支持设备验证 |
| 个人 3D 重建 | **未完成**。环形动画不能代表多视角重建成功，仍使用已标记的公共示例模型 |
| 真机录像/人脸跟随、不同机型方向、持续帧率与低功耗 | **未验证**。没有“完整联调/保证流畅”的结论 |

已人工检查一次实际横屏摄像头取景：画面正向，撑满可用窗口。该私密截图只临时用于本机检查，已删除，不进入 Git、源码包或模型调用；提交的图片只有公共示例场景。竖屏已验证窗口旋转和预览继续运行，但未留存竖屏像素视觉核验。元数据和界面测试不等同于对所有设备相机画质/方向的视觉验收。

## 本轮失败与修正

1. 首次编译失败：组件 width/height 状态名与 ArkUI 属性冲突、快照尚未声明语言字段；更名与补全协议后构建通过。
2. 首次相机测试未找到预览 inspector ID，后续检查连带失败；补充稳定 ID 与失败清理。
3. 第二次测试将裁切后的 UiTest 可见边界误当完整 Surface 长宽比；改为分别验证可见铺满和 ArkUI 原始 Surface 比例。原失败日志保留在 tablet-initial、tablet-second。
4. 模型套件首次在自动输入后立即发送丢失输入事件，未完成调用；增加输入回读及事件同步后，真实闭环通过。失败截图/日志保留，不能计为成功。
5. 直接网络沙箱中的英文调用报告 network_or_response；获准网络执行后同一公开示例测试通过，未打印密钥。

## 核对资料与限制

[华为相机旋转术语](https://developer.huawei.com/consumer/cn/doc/doccenter-capabilities/camera-rotation-term-native)与本地 camera.d.ts、media.d.ts、display.d.ts 对照；[窗口旋转说明](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/window-rotation)区分显示方向与窗口布局。CoreVisionKit 接口以本地商业 SDK `@hms.ai.face.faceDetector.d.ts` 为准，未用 OpenHarmony 示例版本表作商业保证。

搜索到 [Remy 演示](https://www.bilibili.com/video/BV1vEAaz3EvG/)，但页面412、内嵌浏览器超时，未能完整观看；[华为说明](https://consumer.huawei.com/cn/support/content/zh-cn16076523/)亦指出 Remy 仅支持部分机型。本轮是自有全屏采集和引导实现，没有宣称复刻其私有算法。华为部分动态文档正文抓取超时，以实际安装 SDK 和设备运行结果补充核对。

## 复现

DevEco 打开项目根目录，Device Manager 选择当前平板并运行 entry / EntryAbility。不要使用 Previewer 验收相机。

```powershell
./scripts/Build-Hap.ps1
./scripts/Install-Emulator.ps1 -Device 127.0.0.1:5555
./scripts/Check-TabletCamera.ps1 -Device 127.0.0.1:5555
./scripts/Test-Native.ps1 -BuildOnly
./scripts/Test-DeviceSuite.ps1 -Device 127.0.0.1:5555 -Suite SELFNativeCamera -ExpectedTests 2 -Evidence docs/evidence/camera-recheck
```

真实模型测试另需启动 backend/.env 配置的本机后端，并建立该平板的 8787 反向端口。密钥、私密视频、相机截图和签名文件不打包。
