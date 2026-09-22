# 当前原生版本验收记录

日期：2026-09-22；正式规范为 `SELF_HarmonyOS_Native_DeepSeek_Codex_20260922.md`。仅将真实执行项列为通过。证据目录 `evidence/native-es3/`，旧 `emulator/`、`emulator-full/`、`api26/` 是旧 Web/Component3D 记录，不能移作当前原生证据。

## API26 模拟器

目标为 Pura 90 Pro Max，HarmonyOS7.0.0.106，API26、x86_64、1308×2880。运行官方 hdc/Hypium/uitest 的实际 HAP，未使用浏览器测试替代。

| 项目 | 状态与证据范围 |
|---|---|
| C++ 两个 ABI 构建、安装主界面 | 通过；arm64-v8a/x86_64 构建，x86_64 实际安装。`build-current.log`；unsigned debug、原包名与签名配置保留 |
| Native Surface/EGL/GL shader/贴图/FBO | 通过；`probe-runtime.log`、native-probe.png。ES3.2、32纹理单元，RGBA8+depth24，PNG往返字节像素一致 |
| 真实带纹理 GLB、多角度 | 通过；9279顶点/17684三角形，native-face/native-side.png。公共静态扫描，不是个人重建 |
| 照片方向、行跨度、导出颜色 | 通过定向夹具；EXIF1–8 与独立解码器四角一致，33×49 PNG全像素一致，`pixel-checks.json` |
| 原生2D照片平移/圈选 | 通过探针；45个非零蒙版像素，yaw/pitch保持0，panX=.4；native-photo.png、photo-selection.mask |
| 3D圈选内部/遮挡算法 | 固定探针和真实触摸通过；探针37596个非零UV像素，真实UI存1048576字节mask。采用UV纹素投影+BVH最近射线；鼻两侧、广泛接缝和不同资产覆盖仍未穷尽 |
| 真实UI圈选→候选→确认→编辑→撤销 | 通过；Hypium当前12项（10规则/存储与2真实界面流程），`hypium-results.log` |
| 授权/过期计划/有效提交 | 通过规则测试；旋转不废弃候选，业务规则变化废弃，错误回执/渲染失败不记账，目标层删除等待渲染成功 |
| 局部保护与非授权区 | 通过固定视角像素检查；720×1277检查997保护像素、916408非授权像素，RGBA8最大误差0。不是全脸平均差或所有视角证明 |
| 单项保护例外 | 通过像素+业务规则；无grant输出等于基准，grant生效，后续无grant层不能覆盖；长期保护仍在。真实模型冲突对话尚未验证 |
| 绝对强度不累积 | 通过；native-edit/native-repeat RGB完全一致；数字唇色变动边界[329,444,419,471]。仅闭嘴样本，不证明所有牙齿/皮肤边界分割 |
| 干净快照+同视角标注图 | 通过；snapshot-clean与有效导出一致，snapshot-marked独立非空标注；模型未收到真实人像 |
| 损坏GLB | 通过；拒绝4字节坏GLB，保留上一画面，after-invalid-glb.png |
| 前后台/持续操作 | 两轮均通过：605638ms、608091ms，各89轮旋转/试色/对照/撤销/详情，每轮9次前后台，无崩溃；`stress-before-scheduling.log`、`stress-results.log`、`performance-summary.json` |
| Surface反复销毁/重建 | 通过；同一进程28796实际10次销毁/重建，11次完整探针完成，无原生错误；`surface-runtime.log`、`surface-memory.json`。RSS首/尾201080/223032KiB，高水位280832KiB；有限次数通过不等于证明无任何泄漏 |
| 手机→本机后端失败链路 | 通过真实 NetworkKit；health200、缺key返回502被拒绝，operationsAfterFailure=0；`SELF_NETWORKKIT` 日志 |
| 系统选图成功/真实键盘 | 未验证本次完整成功路径；已有选择器与取消处理代码，原生照片夹具不冒充真实选图。小艺输入法另有首次许可，未替用户接受 |
| 作品保存/重开/删除 | 通过生产Store与实际UI；保存yaw=.2902857，重开后实际导出471575字节PNG，删除仅本测试新建记录，原有记录仍存在；`ui-workflow-runtime.log`。旧作品逐份像素一致性未验证，原文件保留并提示 |
| 音乐、柔和界面 | 原生AVPlayer/原ArkUI保留，背景为自写原生shader；本轮未重做全部音频验收，历史音频证据单列，不宣称表情/眨眼已完成 |

## 后端与模型

17项实际 Python 单元/HTTP测试通过：`backend-unit.log`。覆盖工具结构、未知ID/枚举/产品/证据/额外字段、无授权上传、截断/空/多个工具、鉴权、长度、重复请求、失败清理。它们使用明确的测试响应，不能算真实模型调用。

2026-09-22 17:54：`evidence/deepseek/live-results.json` 红圆/蓝方块两项真实 Vision+tool **通过**，返回 deepseek-flash 和实际指纹/用量/耗时。`live-http-results.json` 实际电脑→SELF后端→DeepSeek 请求及重复请求缓存 **通过**。合计最终三项6110 tokens，1453/2079/1953ms；不包含前面失败和诊断的API用量。模拟器真实NetworkKit health200、modelConfigured=true，证据 `evidence/deepseek/emulator-connectivity.log`。手机云端授权→候选→原生检查→有效提交→账单完整闭环仍 **未验证**；未上传人像，未验证真实人像识别质量。

首次工具字段混用、编辑夹带澄清被拒绝，另一次结构合法但擅自替换用户指定颜色，语义验收失败。已收紧字段说明/约束并添加回归，最终复测通过，全部已记录失败证据，见模型协议文档。有限测试通过不保证模型每次遵循意图。

真实服务超时/取消竞态、模型难例、精密视觉识别和长期保护冲突对话仍需真实调用。未开公网端口，未部署公网模型代理。

## 真机、性能与失败记录

真机：全部未验证。arm64可编译不等于真实HarmonyOS设备运行、签名、图形、相册、温度、功耗或流畅已通过。最低API19原生运行也未验证。

初始预算30fps、1K–2K纹理、720p级检查。修正“每帧从实际开始时间重新等33ms”在离散VSync上的累积等待，采用绝对节拍推进。两轮同类工作负载实测如下（模拟器，非受控硬件基准）：

| 指标 | 调整前 | 调整后 |
|---|---:|---:|
| 连续测试 | 605.638秒 / 89轮 | 608.091秒 / 89轮 |
| CPU提交/Swap p50 / p95 | 2.61 / 38.47ms | 2.18 / 35.22ms |
| CPU渲染开始间隔p50 / p95 | 45.27 / 61.86ms | 31.42 / 63.04ms |
| CPU提交超过50ms | 184 / 15718帧 | 145 / 16839帧 |
| 进程内存高水位 | 259180KiB | 318024KiB（约310.6MiB） |
| 采样RSS首/尾 | 222552 / 248480KiB | 259744 / 235112KiB |

仍未达到“稳定30fps”的验收，p95长帧需进一步性能工作。间隔取CPU渲染开始，**不是GPU完成/屏幕实际呈现时间**；旧日志的presentInterval名称在新版改为renderStartInterval以避免误解。内存有波动，末尾下降，不能凭十分钟证明不存在任何泄漏。采样不是从进程诞生时开始，高水位来自系统VmHWM。完整原始数据见 `performance-summary.json`、`stress-memory*.json`；大照片、低内存、耗电未验证。

已修复且保留证据的失败：CMD AutoRun导致Native链接目录错误；未初始化Node API导致SurfaceHolder失败；深度状态导致空白；可选ArrayBuffer传undefined；保护shader缺括号；UI测试异步等待/签名参数；Stress runner自定义参数未被采用。模拟器曾退出导致安装断连，重新启动同一实例恢复，未清数据。旧API26 ArkWeb仍被镜像禁用，当前原生不依赖它。

未实现或不宣称：个人3D扫描/重建、任意个人GLB文件选择导入的产品流程（当前是受限加载器和固定示例）、Remy/PLY转换、高斯渲染、自动精密唇部/痣雀斑分割、全脸美化、皮肤光学/品牌功效标定、颜值评分、心理诊断、系统相册/公开分享、正式签名发布。数字颜色不是SKU实测，示例资产不是用户本人。

## 复现

`Build-Hap.ps1`→`Install-Emulator.ps1`→`Test-Native.ps1`→`Start-NativeProbe.ps1`。probe文件通过hdc从本应用私有目录取回，`check-native-pixels.py`用独立Pillow校验。`Test-Surface-Rebuild.ps1`实际点击销毁/重建表面。`Test-Stress.ps1`选择明确的Hypium class，单次不少于600秒；`Measure-NativeMemory.ps1`仅采SELF进程。模型见`Test-Backend.ps1 -Live`，没有key返回未验证而非通过。
