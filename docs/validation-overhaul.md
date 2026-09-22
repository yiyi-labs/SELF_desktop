# SELF 本轮真实验收记录

日期：2026-09-22。结论：已交付一轮可运行的原生增量优化，**未完成个人视频重建、全量 OLAY 精确参数和真机验收**。没有浏览器或 Previewer 测试被列为鸿蒙模拟器通过项。

## 环境与版本

- DevEco Studio 26.0.0.821，商业 SDK 26.0.0.105；target API 26，工程兼容版本 19。兼容版本是声明，不代表已在 API 19 设备实测。
- Pura 90 Pro Max 模拟器 `127.0.0.1:5555`，1308×2880；MatePad Pro 13 模拟器 `127.0.0.1:5557`，2880×1920 横屏。均 HarmonyOS 7.0.0.106 / API 26。
- 原生渲染：XComponent / NativeWindow / EGL / OpenGL ES 3；GLB 经原生字节加载。主页面未使用 ArkWeb / Three.js。
- 后端 Python 3.12，实际模型返回 `deepseek-flash`。密钥保留本机 `backend/.env`，没有加入 Git、HAP 或源码交付。
- 包名 `com.self.mirror`，保留既有作品和设置，使用覆盖安装；没有卸载清数据。发布签名未配置，当前为模拟器调试 unsigned HAP。
- 本地 Git 首次基线 `1587601`。交付文件 SHA-256 见 `artifacts/delivery-manifest.json`。

## 已通过

| 层面 | 实际结果 | 证据 |
|---|---|---|
| 构建 | 商业 SDK 编译 ArkTS、x86_64 和 arm64-v8a 原生库成功；存在 API/异常处理及未配置签名的警告，不能描述为零警告 | `evidence/overhaul/phone-delivery-final.log` |
| 手机模拟器策略与界面 | 14/14；阻止本地新效果绕过模型、授权/保护/失败不记账、触摸圈画、拒绝上传、保存/重开/导出及仅删除测试作品 | `evidence/overhaul/phone-delivery-final/hypium-results.log` |
| 平板模拟器策略与界面 | 12/12 策略 + 2/2 界面；实际生产 HAP 先安装，再安装测试模块 | `evidence/overhaul/tablet-release-policy/results.log`、`tablet-release-ui/results.log` |
| 平板圈画与布局 | 注入手写笔事件直接圈选，对话卡在窗口内；窗口方向改变后镜面宽度变化，恢复横屏成功 | `evidence/overhaul/tablet-final-experience/results.log`、`experience-pen-popup.png`、`experience-rotated.png` |
| 中文输入与同意发送 | 中文读回正确，提交后出现本次云端许可；拒绝后没有上传或执行新外观效果 | 同上第三项；这不是软键盘遮挡或实体笔验收 |
| 手机/平板原生图形 | 9279 顶点、17684 三角形 GLB；纹理、旋转、圈选、PNG、错误 GLB 回滚、8 种 EXIF 方向、奇数宽 PNG | `evidence/overhaul/phone-release-native`、`tablet-release-native` |
| 羽化与权限 | 圈外新增 texel 为 0，软边存在、窄区域保留；受保护和非授权区域的原生屏幕采样最大误差均 0；v2 重复应用逐像素一致 | 两端 `probe.log`、`pixel-checks.json`；没有由有限采样推断所有场景完全正确 |
| 动画 | 实际原生提交渐变帧已记录；手机 18 帧、平板 20 帧是探针计数，不是帧率保证 | 原生探针 `SELF_ES_STATS` |
| 旧作品多层兼容 | 无版本字段仍走旧混色和旧羽化；16 个中心像素与独立 CPU 旧公式一致，最大通道误差 0 | `tablet-native-final/pixel-checks.json`、`legacy-photo-*.png` |
| 真实模型 UI 链路 | 公开样本截图→本机后端→DeepSeek→候选→用户授权→原生检查→有效提交→1 项账单；随后撤销并仅删除测试新作品 | `evidence/overhaul/tablet-delivery-model-verified/results.log`、`app-events.log` |
| 真实产品问答 | 原创非个人图像 + tool；仅引用大陆资料中的水光小白瓶条目，明确未知配方、不提出编辑 | `evidence/overhaul/live-product.json` |
| 后端回归 | 25/25，包含鉴权、上传拒绝、幂等、无效工具调用、引用约束、未知标定、产品连续指代和换话题后不强推 | `evidence/overhaul/backend-release-tests.log` |
| 产品参数请求与连续指代 | 两次真实 DeepSeek 图片+tool；“按真实产品参数修改”和“试一下这款”均保留水光小白瓶身份，返回解释、零操作；这是正确拒绝未标定效果，**不是已实现产品试妆** | `live-product-effect.json`、`live-product-followup.json`（均位于 `evidence/overhaul`） |
| 手机/平板产品界面 | 两端各1项真实模型产品 UI 测试；启动无产品卡，正确请求水光小白瓶后显示该条目，旋转/开盖/堆叠卡/多次收起再开/取消清理通过，实际屏幕白色瓶身像素校验通过 | `phone-delivery-products`、`tablet-release-products` 下 `results.log`、`product-ui-pixels.json`、截图 |
| 原生产品资源 | 6组、12个GLB，24张开合/中间帧/旋转导出；颜色存在，姿态帧不同，关闭产品后面容逐像素不变；并非视频截图或图片切换 | 两端 `*-release-native/pixel-checks.json`、`product-*.png` |
| 十分钟手机持续交互 | 603485 ms、67轮授权历史重放，测试通过；16580帧，CPU提交P95 20.94ms，渲染起点间隔P95 51.52ms，883个间隔超过50ms，**不能称稳定30fps** | `phone-stress-final/stress-results.log`、`app-events.log` |

`*-delivery-*` 为最终构建；`*-release-*` 的原生探针、平板布局和产品卡视觉检查使用相同渲染代码与资产，之后只补上候选圈选一致性校验和手机浮层纵向位置。模型提交在最终构建重新验证。平板体验/笔注入、十分钟持续测试在产品展示新增前完成，不能称为最终双画布版本的长时性能验收。全部截图由模拟器获取，无浏览器结果充当设备证据。两端圈选卡片范围断言见 `phone-delivery-final`、`tablet-release-anchor`；后者为横屏截图。

## 当前失败或尚未实现

- **相机录制失败：** 平板调用商业 SDK `cameraPicker.pick` 返回空结果，没有得到相机录制界面、有效 MP4 或成功采集证据。体验套件是 **2 通过、1 错误**，不是全通过。现在提示清楚的失败原因并清理空文件，原作品不变。见 `tablet-final-experience/experience-camera.png`。
- **个人 3D 未实现：** 两端无法加载空间重建运行库。普通相机视频缺同步位姿/内参；SDK 的 GS PLY 输出也不是当前可编辑的 UV 网格 GLB。没有使用示例头模、改文件后缀或 Blender 占位冒充重建。设备支持检查不等于已接通重建。
- **产品范围不完整：** 当前只有 8 条大陆渠道名称/规格/系列事实记录，其中有系列和多变体，不是完整 SKU 库；是否仍在售未逐项确认。INCI、配方版本、浓度、物理参数、功效标定均为空，不用于模拟真实护肤效果。没有依据可以承诺“所有参数完全正确”。
- 新增外观仍限已实现的通用数字颜色和强度，由模型选候选、原生引擎执行；不是任意生成式修改、精确化妆品试妆或真实生理功效。
- **用户要求的产品参数驱动修改未完成。** 当前 `calibratedProductEffects=[]`，明确产品请求、上轮产品连续指代、带产品引用的 edit 均被前后端阻止；不能把“拦截无依据的修改通过”描述为产品效果实现。

## 未验证

- 真机安装签名、相机录制/私有视频回读、横移重建精度/成功率、个人脸多角度编辑全流程。
- 实体手写笔的压感、悬停、掌触抑制；当前只验证模拟器注入的 Pen 事件。
- 系统软键盘遮挡、折叠屏、2in1、全部分屏尺寸和低版本设备；窗口宽度布局代码不能代替这些实测。
- 真机长时帧率、GPU/功耗/内存趋势、所有旧作品的像素迁移一致性。短探针或十分钟 UI 测试不能保证流畅度。
- 官方全量大陆 SKU、备案/批次一致的 INCI、产品实验标定。产品 UI 已改为原创近似 3D 包装；尺寸、机构、材质并未实测，不是精确包装复刻。
- 网络中断、模型变化下的所有实况组合；协议拒绝/失败单元测试不能代替全部真实网络异常测试。

## 本轮已修复的失败与证据解释

旧记录保留，不删除失败来制造全通过：平板最初响应式分支未刷新、尺寸变化导致 EGL 12301 黑屏、照片圈选数量错误硬编码、产品模型回复过长被拒绝、测试中文输入后误按返回、持续测试过早打开面板。根因和改动见 `overhaul-implementation.md`。现行通过结果以本页明确指向的证据为准，根目录下早期截图和旧 `validation-native.md` 不替代此页。

产品 UI 曾出现按钮测试通过但瓶身发黑。GPU 上传值与源数据一致，独立场景导出通过却不足以证明新画布采样状态正确。最终显式创建产品 sampler、绑定独立纹理单元、单 mip 不可变存储，并补上真实屏幕瓶身像素校验。`tablet-product-linked`、`*-product-final`、`tablet-product-texture` 等早期交互通过记录**不代表视觉通过**；`*-release-products` 为修复后结果。临时灰度/纯纹理排查代码和运行时调试 PNG 导出已移除。

`tablet-delivery-model` 首次最终重测已记录 `SELF_LIVE_MODEL_COMMIT`，但测试收尾在面板恢复前直接寻找撤销按钮而失败。第二次 `tablet-delivery-model-final` 又在打开作品面板后过早查找保存按钮而失败。两处均改为等待目标组件，最终 `tablet-delivery-model-verified` 1/1 通过；未放宽业务断言，也未删除两次失败证据。

## 复现

1. 用 `scripts/Build-Hap.ps1` 构建，`Install-Emulator.ps1 -Device <地址>` 覆盖安装主程序。
2. `Test-Native.ps1 -Device <地址> -Evidence <新目录>` 构建两包、先装主程序再装测试模块，运行 14 项无付费测试。
3. `Start-NativeProbe.ps1 -Device <地址>` 后等待探针结束，再用 `Collect-NativeProbe.ps1 -Device <地址> -Evidence <新目录>` 收集真实设备文件并校验像素。
4. `Test-DeviceSuite.ps1` 可单独运行体验套件。`SELFNativeModelLive`、`SELFNativeProductUI` 和 `Test-Stress.ps1` 会发送公开样本图片并产生真实 API 用量，只在明确运行时触发。产品 UI 套件还自动收集截图并运行屏幕像素校验。
5. `Package-Delivery.ps1` 打包代码、资源及证据，检查 HAP 资源哈希和两种原生 ABI，排除 `.env`、本机依赖、签名私钥与缓存。
