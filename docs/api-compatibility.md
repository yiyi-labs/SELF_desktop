# 商业 SDK 接口核对：2026-09-22

正式路径为 ArkUI → N-API → C++ EGL/OpenGL ES3 → XComponent SURFACE。唯一生产入口仍为 `EntryAbility / SelfMirrorPage`。旧 Web 与 Component3D 试验源码保留作参照，不自动回退、不创建第二套作品。

实际 DevEco 26.0.0.821；SDK/Native package 26.0.0.105（API26、Release），target `26.0.0`、compatible `5.1.1(19)`，沿用 ArkTS 动态编译模式。CMake 3.28、Clang 15.0.4；`arm64-v8a`、`x86_64` 都从本项目源码链接。运行证据仅为 API26 x86_64 模拟器，不代表 arm64 真机或最低版本已经测试。

本地声明根目录：`C:/Program Files/Huawei/DevEco Studio/sdk/default/openharmony`。这是商业 SDK 实际安装布局，不能仅凭目录名将其与任意 OpenHarmony master 版本等同。

| 实际调用 | 本地依据与边界 |
|---|---|
| Stage UIAbility / ArkUI | `@kit.AbilityKit`、已有 V1 页面；新 NativeMirrorSurface 独立 `@ComponentV2`，没有同 struct 混用 V1/V2 |
| FrameNode 转 NativeNode | `arkui/native_node_napi.h`，`OH_ArkUI_GetNodeHandleFromNapiValue`（12 起）；先通过 `arkui/native_interface.h` 初始化 `ArkUI_NativeNodeAPI_1` |
| SurfaceHolder | `ace/xcomponent/native_interface_xcomponent.h`，Create/AddSurfaceCallback/GetNativeWindow/Dispose 等（19 起）；不同时注册旧 OH_NativeXComponent 生命周期 |
| NativeWindow | `native_window/external_window.h`；回调借用窗口显式增加自己的引用，只释放自己的引用 |
| 帧调度 | `native_vsync/native_vsync.h` Create/RequestFrame/Destroy（9 起）；未调用最低版本之外的新 SetExpectedFrameRateRange |
| GL / EGL | 本机 EGL、GLES3 headers；`EGL_NONE` 终止属性，ES3 window context，RGBA8+DEPTH24 FBO；不依赖浮点 FBO 或 sRGB window 扩展 |
| 图片 | `multimedia/image_framework/image/` 的 ImageSourceNative、PixelmapNative、ImagePackerNative（12 起）；RGBA8888、row stride、opaque baseline、PNG；EXIF1–8 显式转换一次 |
| 网络 | `http` from `@kit.NetworkKit`；异步自有后端请求、取消与超时；module 声明 INTERNET。HTTPS 保持证书验证 |
| 选图/文件 | `photoAccessHelper` from `@kit.MediaLibraryKit`；`fileIo` from `@kit.CoreFileKit`。URI 通过正式文件接口读取 |
| N-API / 日志 | `napi/native_api.h` async_work + threadsafe_function；Native hilog；UI 线程不等待网络或图像编解码 |

实际商业 SDK 两个 ABI 编译/链接通过，是接口可构建证据；API26 模拟器运行是另一个层级。最低 API19 的原生二进制运行尚未验证，不能用旧 Web API19 测试替代。

## 线程与生命周期

UI 只复制请求与字节；N-API async worker 解析 GLB/解码照片。GL 专属线程管理全部 EGL/GL。PNG 编码在读回后交回 async worker。NativeVSync 自身回调只唤醒 GL 队列。候选检查、圈选、导出才读回，动画帧不读回。

解绑先关闭事件投递，再移除 holder 回调、等待 GL 清理并释放窗口自有引用，最后释放 holder / JS 事件通道。GL 不等待 JS，所以没有 UI↔GL 循环等待。后台停止调度；保存从 Native 取实际视角；照片限定平移/缩放，3D 才旋转。

## 官方资料限制与已修复问题

[Huawei XComponent 指南](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/napi-xcomponent-guidelines)本次网页正文返回空，不能声称完整核实网页；本地头文件和实际编译为主要依据。官方 OpenHarmony 指南/实现只用于交叉核对，固定读取版本见 `evidence/native-es3/reference-commits.json`。

实际失败包括：未初始化 NativeNode 模块导致 SurfaceHolder 创建失败、默认深度状态导致空白、保护例外 shader 缺括号、N-API 可选 ArrayBuffer 传 undefined。均保留失败日志并修复后重新运行。宿主 CMD AutoRun 改变 CMake 目录的问题通过本项目 `BuildCmd.cs` 的 `/D` 子进程适配解决；不修改注册表。
