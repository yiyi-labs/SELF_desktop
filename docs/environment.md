# 实测环境与纵向验证

## 当前生效记录：2026-09-22 原生 ES3 + DeepSeek 迁移

最新实施依据为根目录 `SELF_HarmonyOS_Native_DeepSeek_Codex_20260922.md`，已完整读取；本机未发现适用 AGENTS.md，也没有 Git 仓库可提供 diff。保留原工程及用户数据，旧渲染记录仅供追溯。

正式 `EntryAbility` 已使用 C++ EGL ES3 / XComponent SurfaceHolder，原 ArkUI 柔和界面保留。当前 API26 原生人脸 GLB、贴图、旋转、圈选和 PNG 已实际运行，**下文“API26 WebGL 不可用”是旧引擎的历史结论**，不适用于当前原生路径。

| 当前层级 | 实际结果 |
|---|---|
| DevEco / SDK / Native SDK | 26.0.0.821 / 26.0.0.105 / 26.0.0.105 API26 Release |
| 工程 | target26.0.0、compatible5.1.1(19)、现有 ArkTS 动态模式 |
| CMake / Clang | 3.28 / 15.0.4 |
| 构建 ABI | arm64-v8a、x86_64 均从源码构建链接；未复制外部 .so |
| 模拟器 | Pura 90 Pro Max，127.0.0.1:5555，emulator7.0.0.106(SP1DEVC00E999R4P11)，API26，x86_64 |
| 实际 GL | vendor ARM，Mali-G77，OpenGL ES3.2 (4.6.0 Build32.0.101.8724)，GLSL ES3.10，32 texture units |
| 宿主 | Intel Arc140T，驱动32.0.101.8724；不把模拟器 Mali 字符串当成真实手机 GPU |
| 图形/导出 | RGBA8 FBO + depth24，Native Image PNG；真实9279顶点/17684三角形扫描 |
| 后端 | Python3.12，项目 backend/.venv；固定 FastAPI/httpx/Pydantic 依赖；仅 loopback8787 |
| 模型 | 默认 deepseek-flash；官方配置已核对，密钥未提供，真实调用未验证 |
| 签名 | 原 signingConfigs=[] 保持；unsigned debug HAP 在本模拟器安装，真机和发布未验证 |

当前证据在 `evidence/native-es3/`；接口依据见 [api-compatibility.md](api-compatibility.md)。构建脚本为 CMake 子进程使用 `/D` CMD 适配器，规避本机 AutoRun 改目录；只改变本进程 ComSpec，不改注册表。曾有模拟器退出造成安装断连，恢复同一实例后继续，未清数据。

以下章节是旧 Web/Component3D 实施的历史记录，不能替代当前验收。

核对日期：2026-09-21 至 2026-09-22。初始项目目录为空，根目录及祖先目录未发现 AGENTS.md；没有整仓替换既有代码。当前根目录的 FINAL 提示词来自用户给定的 Downloads 文件，旧版提示词未叠加。

| 项目 | 本次实际值 |
|---|---|
| 系统 | Windows，本项目 D:\STUDY\College\mine\olay |
| DevEco Studio | 26.0.0.821，build 261.23567.138.36.2600821 |
| 实际安装目录 | C:\Program Files\Huawei\DevEco Studio |
| 用户提供的安装包目录 | C:\Users\30243\Downloads\devecostudio-windows-26.0.0.821；它是安装来源，不是最终 IDE 目录 |
| 安装包 | deveco-studio-26.0.0.821.exe，3,296,046,208 bytes；Authenticode Valid，Huawei Technologies |
| SDK | sdk/default，HarmonyOS 26.0.0，API 26，26.0.0.105 |
| 构建目标/兼容目标 | targetSdkVersion 26.0.0 / compatibleSdkVersion 5.1.1(19) |
| Hvigor / OHOS plugin | 6.26.4 / 6.26.4 |
| 构建 Node / Java | DevEco bundled Node 24.14.1 / bundled jbr；不使用全局 Java 17 |
| 辅助 Node / npm | 系统 Node 24.15.0 / npm 11.12.1 |
| ohpm / Hypium | 26.0.0.630 / 固定 1.0.25 |
| hdc | 3.2.0f |
| 手机模拟器实例 | Huawei_Phone，已有 API 19 镜像；未替换已有 2in1 实例 |
| 镜像目录 | C:\Users\30243\AppData\Local\Huawei\Sdk\system-image\HarmonyOS-5.1.1-B1\phone_all_x86 |
| 系统实际返回 | emulator 5.1.0.199(SP3DEVC00E199R4P11) |
| 实际 ArkWeb | ArkWeb 4.1.6.1 / Chrome 114.0.0.0 / OpenHarmony 5.1 |
| 桌面图形测试 | Chrome 153.0.8010.48，headless SwiftShader，DPR 2；这是独立测试环境 |
| 签名 | 未配置发布签名。生成 unsigned debug HAP，实际 API 19 模拟器允许安装；未验证真机 |

机器可读记录见 [environment.json](evidence/environment.json)。安装位置以该记录为准。用户已明确同意两份模拟器许可，随后执行官方 `Emulator.exe -license accept` 并启动已有实例；没有更改 BIOS、系统防护或账号设置。IDE 安装完成后继续使用实际 Program Files 目录，未擅自移动安装目录。

## 2026-09-22 新 API 26 环境补充

以上 API 19 表为历史验证环境。用户后续配置了 Pura 90 Pro Max：设备 `127.0.0.1:5555`，系统 `emulator 7.0.0.106(SP1DEVC00E999R4P11)`，实际 API 26，屏幕 1308×2880，x86_64。新镜像路径为 `%LOCALAPPDATA%\Huawei\Sdk\system-image\HarmonyOS-7.0.0\phone_all_x86`。主机显卡为 Intel Arc 140T，驱动 32.0.101.8724；不能假设支持 CUDA。

API 26 HAP 可安装并打开原生界面；ArkWeb 7.0.0.105 / Chromium 144 的 WebGL1/2 均被启动参数 `--disable-3d-apis` 禁用。应用级 enableAdvancedSecurityMode({disableWebGL:false}) 的试验无效并已撤回。原始和复测结果在 `evidence/api26/`。用户日志的宿主 PID 20944 对应 Previewer，和真实手机模拟器是独立进程。

新增原生 ArkGraphics 3D 独立入口实际出现纹理模型，但外观未通过；后续启动也出现 scene manager 创建失败。不能推广为原生 3D 已兼容所有模拟器或真机。入口只用于迁移验证，主界面仍保留原设计。

## 最小纵向验证的真实边界

先在实际 HAP 中验证 WebGL2、GLTFLoader.parseAsync(ArrayBuffer)、嵌入 JPEG、双向中文/引号/NUL、65,539 字节全值域往返、闭合圈选、1 MiB 蒙版回传及私有 PNG 写入，然后扩展业务页面。历史证据：[vertical-results.json](evidence/emulator/vertical-results.json)。新版完整流程证据：[emulator-full/results.json](evidence/emulator-full/results.json)。

最终桥使用 `createWebMessagePorts(true)`、`WebMessageExt` 的 STRING / ARRAY_BUFFER、`onMessageEventExt` 与 `postMessageEventExt`。ArkTS 与 Web 都使用开始/结束帧，正文分为 65,536 字节 ArrayBuffer。接收完成才提交，最大单资产 32 MiB。实际验证 65,539 字节往返、553,116 字节 GLB、1,048,576 字节蒙版及约 414 KB PNG；32 MiB 极限和超大导出取消未在模拟器验证。base64 辅助函数仅做 Node 测试，生产路径没有采用它。

资源方案：本地 rawfile HTML/CSS/单个 IIFE；源 GLB、PHOTO、mask、PNG 均通过原生登记 ID 和二进制消息。没有虚构宿主 URL，没有将 blob URL 当作原生路径，没有网络图片权限。CSP 仅为 GLTFLoader 内嵌纹理允许 `connect-src blob:`，不允许 HTTP 请求。MESH 使用静态扫描 bakedAppearance，不宣称实时重光照或个人重建。

背景动效使用程序生成的 CSS 变量，因此 style-src 允许 self 与 inline 样式；script-src 仍限本地 self，没有内联脚本、eval 或网络脚本。音乐走原生 AVPlayer + ResourceManager.getRawFd，不通过 Web 音频或 CDN；已在实际模拟器观察 playing 与超过 1 秒的播放时间回调。三段本项目 WAV 为 24 kHz、16 bit、双声道、每段 32 秒。

系统小艺输入法首次启用时要求独立的用户协议/隐私选择，与先前接受的两份模拟器许可不同；未代替用户自动接受。因此真实键盘输入、键盘展开后的完整交互仍未验收；本地文本映射已在生产类的 Node/Hypium 测试覆盖。

## 构建与调试注意

所有脚本支持 `-DevEcoHome`，本机默认值来自实际探测。构建只设置进程级 SDK/JAVA 环境变量。Hvigor 初次安装 pnpm 10.28.2 到用户缓存；其安装输出曾报告一项 high 漏洞，未做全局升级，见 validation 风险项。项目 npm 依赖与 ohpm 依赖均固定并保留锁文件。

本机 CMD AutoRun 会改变当前目录；因此脚本直接调用 node.exe 和 npm-cli.js / pm-cli.js，不通过 npm.cmd、ohpm.bat。构建日志包含 SDK 的异常处理静态警告以及未设置签名警告；编译成功不代表发布就绪。

Debug 使用 SDK 的 `applicationInfo.debug` 开启 Web 调试，Release 按该标记关闭；Release 包和真实设备未实测。模拟器测试从当前 bundle PID 发现 ArkWeb socket，转发到本项目 9223，结束后删除对应映射。Chrome CDP 的 Browser.setDownloadBehavior 在此 ArkWeb 不支持，故采用最小 CDP WebSocket，只观察/操作实际 HAP 的 WebView；未以桌面页替代模拟器。

未测性能：持续帧率、耗电、低内存、大照片峰值、真机图像质量。CPU 可见面圈选优先正确性，未宣称实时大范围高帧率。
