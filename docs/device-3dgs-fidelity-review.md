# 端侧 3DGS、面部圈选与保真审查 · 2026-09-23

本报告按用户最新要求采用设备端 3DGS；它替代旧提示词中“首版不新增高斯能力”的限制，以及上一份审查中可直接使用低分辨率、固定关键帧数作为性能预算的建议。保留现有原生 GLB 编辑器、作品和包名。**正确性、本人特征和细节优先，不能用自动降质换取速度。**

## 结论与实际完成边界

SDK 存在可调用的设备端重建接口，但“SDK 提供接口”不能推出“SELF 已有完整个人建模”。本轮增加了真实接口适配与可测试任务控制器，不再只写 IsSupport 探针：CreateSession → PushFrame/PushARFrame → RegisterNGCallbackFunc → StartSession → 完成回调 → 再注册回调 → SaveResultToFile → 保存回调 → 待验收产物。

**尚未完成 AR 相机接管/采集接线、真实个人 GS 载入主界面、保真验收以及 GS 的精细表面圈选。** 新控制器输出 `saved-unverified`；`acceptedForPortrait` 始终 false，没有注册为个人资产，不会替换已有面容。`pipelineImplemented` 仍是 false。没有把合成测试点、框架测试或成功编译称为真人建模成功。

## 商业 SDK 实际核对

使用本机 DevEco 26.0.0.821，商业 SDK 26.0.0.105，目标 API26；原有 compatible 5.1.1(19) 保留。编译 arm64-v8a 与 x86_64。新接口通过 SDK 原始声明的 `decltype` 取得函数类型并动态解析，低版本/模拟器缺库时可正常报告，绝不打包 SDK 链接桩冒充设备实现。

核对文件：

- `sdk/default/hms/native/sysroot/usr/include/spatial/spatial_recon_interface.h`
- `sdk/default/hms/native/sysroot/usr/include/ar/ar_engine_core.h`
- 同版本 `hms/native/docs/html/group___spatial_recon.html`
- `hms/ets/api/@hms.graphics.spatialRender.d.ts`
- `hms/ets/api/@hms.graphics.spatialEdit.d.ts`
- `openharmony/ets/api/graphics3d/Scene.d.ts`（本机配套声明；不以 OH 版本表保证商业机型兼容）

| 已核对事项 | 对实现的约束 |
|---|---|
| 输入 RGB、真实内参、8 个畸变系数、位置、xyzw 四元数、纳秒时间戳；或 PushARFrame | 普通 MP4、二维鼻尖坐标、关键点推测的转头角度不能直接替代。纳秒值跨 ArkTS 用十进制字符串，避免 JS 双精度截断 |
| 顺序输入；Start 后禁止继续 Push，包括暂停期间 | 采集和重建分阶段。不能做“边训练边不断补帧”的虚构流程 |
| API26 NG 回调携带 userdata，且每次任务仅生效一次 | 重建、保存前分别注册。单调递增回调代号隔离迟到结果，不用可释放对象地址作为回调上下文 |
| GetProgress 的 100% / FINISHED 不等于文件保存回调成功 | SDK 完成、保存完成、文件存在、格式正确、可显示、质量合格各自检查 |
| SetRunningMode 只在 Start 后、完成前生效 | 前后台调度是调度手段，不是降低输入或模型质量的参数 |
| 已读取接口没有公开迭代数、目标高斯数、面部精度档位 | 不编造“1000 次迭代”“自动砍一半点数”之类配置，不承诺 SDK 内部始终保留所有细节 |
| GSPlugin 注释写 Scene.loadPlugin；实际声明是 RenderContext.loadPlugin | 初次编译揭示矛盾，改为 Scene.getDefaultRenderContext().loadPlugin；保留失败日志，不能照抄注释/博客 |

官方资料入口：[API26 官方月刊中的端侧 3DGS 课程](https://developer.huawei.com/consumer/cn/monthly/202608)、[C 接口](https://developer.huawei.com/consumer/cn/doc/harmonyos-references/capi-spatial-recon-interface-h)、[空间渲染](https://developer.huawei.com/consumer/en/doc/harmonyos-references/spatial-recon-spatialrender)、[空间编辑](https://developer.huawei.com/consumer/cn/doc/harmonyos-references/spatial-recon-spatialedit)。本次网页正文提取遇到超时/体积限制；没有声称已读完无法获取的网页或课程视频。具体接口签名以本机商业声明及附带 Native 文档核对。

Remy 的公开合作案例明确描述 AR 图像/位姿采集、轨迹覆盖引导、云端重建和本地预览：[HarmonyOS SDK 团队案例，2025-12-30](https://www.cnblogs.com/HarmonyOSSDK/p/19419681)。该旧案例不证明 Remy 最新全部模式为端侧，也不能成为 SELF 的耗时证据。这里借鉴采集和覆盖引导，重建继续按用户选择在设备端执行。

## 不牺牲细节的优化边界

**可以先做、且不改变输入/模型含义的优化：**

1. 优先直接在 Native AR 所属线程调用 PushARFrame，避免图像经过 ArkTS、Base64、解码和多次拷贝。`pushARFrame` 接口已经实现，但 AR 采集所有者尚未接线，所以没有声称已降低实机耗时。
2. RGB 备用接口把复制后缓冲区移动给任务，不再次复制。源分辨率、内参、姿态和字节保持不变。鉴于 SDK 未声明 PushFrame 的缓冲区所有权，当前保守保留到 DestroySession 成功后释放；不能为了省内存过早释放。
3. 一次只处理一个 N-API 重建命令，拒绝积压帧；不把无上限任务排队耗尽内存。采集应受背压控制，暂停/提示补采，不能悄悄丢失必要视角。
4. 采集结束后释放相机、检测和编码；重建期间暂停无关 3D 动效，避免争用。已有“相机打开时暂停后方镜面渲染”保留；新的重建状态仍需接入同一资源调度。
5. 仅对同一 AR 时间戳的重复通知直接去重；画面相似、相机角度接近不等于细节相同。不能只用位姿阈值丢帧。实际重复输入当前会明确拒绝。
6. 重复显示使用同一不可变 GS 资产与已缓存选区；旋转/圈选不应重新重建。

**不允许默认采用：**降低人脸输入分辨率、给原始纹理加有损压缩、固定 60–120 张截断、为了准时完成提前结束迭代、删小高斯点/低对比斑点、磨皮补洞、用单图生成脸替代未拍到的部分。后台调度、高温暂停或更长等待优先于降质。SDK 帧上限/内存不足返回失败，不能把部分输入当作完整成功。

原始 MP4 可作记录，但当前最长边 960 的软件录像只是模拟器兼容采集，**不是最终保真重建输入**。不改变此既有录像功能的名义质量，并且不将其直接送去生成“高精度面容”。

性能优化必须使用同一套原始采集做 A/B 对照，先通过下面的质量门槛，再比较总时长、峰值 RSS/GPU 内存、能耗与温度。SDK 由系统自行降频时允许更慢；不写固定秒数承诺。降低显示负载与降低重建负载分开记录；TiledGSNode 的分块显示不是重建加速证明。

## 面部圈选：正确目标与 SDK 尚缺的证据

需要保证的是：在左脸颊圈画之后，左右转动、缩放、保存重开，都仍然指向同一片皮肤；不会穿透到后脑、耳后、头发或背景。**选区是模型上的区域，屏幕轨迹只是创建选区时的输入。** 圈选不改变肤色，也不等于授权执行效果。

预定数据模型是不可变模型摘要/版本 + regionId + 同一模型内稳定的表面成员及权重 + 三维锚点。UI 笔画期间冻结视角、模型变换、视口尺寸及镜像状态；取消、第二根手指或视口旋转使这一笔失效。结束后一次性解析可见表面，之后随模型投影显示轮廓和对话锚点，不每帧读回整张画面或再次选取。

必须先通过这些检查：

1. **可见性。** 蒙版内只包含当前可见的、被确认为目标皮肤表面的成员。鼻翼遮挡后面的脸颊时不能隔着鼻子选择；混合透明的发丝、边缘、背景应视为不确定区域，不能仅取投影范围内全部点。
2. **绑定。** 保存的是模型内成员，不是当前屏幕坐标。模型内容/点顺序发生变化时旧选区失效；文件保存或 SDK 导入可能重排点，必须验证对应关系，不能直接假定 PLY 行号就是 GSEdit 索引。
3. **边缘。** 过渡只在已授权表面的内部向零收敛，保护区始终为零。某个高斯点的投影可能跨越边界，仅修改其颜色未必能限制最终像素变化，所以权重选择还必须验证渲染贡献是否越界。
4. **几何。** 不改变原始 GS 的位置、尺度、旋转、不透明度和球谐细节以适配圈选。若采用额外表面辅助结构，它仅用于定位，并须与真实多视图一致，不替代/简化显示模型，也不能将通用脸模板当作本人表面。
5. **修改。** 继续执行大模型候选→授权→候选渲染检查→提交。原始 GS 保持不可变，未知或超出范围的修改不写入账单。DeepSeek 不能提供精密唇边蒙版，也不能作为几何正确性的裁判。

本机 `GSEdit` 声明有 selectBy2DMask、selectByIndex、clearSelection、paint、undo、saveToPLY；但**没有返回选中索引/每点权重的接口，也没有对蒙版阈值、遮挡、软边或导入/保存索引稳定性给出明确契约**。Scene 的通用 RaycastResult 也没有提供足以证明 GS 精确表面命中的成员信息。因此，不能仅调用 selectBy2DMask + paint 就宣称解决了贴脸圈选。

落地顺序：先在合成前后层与真实输出上验证官方选择行为；若可见性/绑定不满足，需补充可核对的表面定位与稳定成员映射，或者获取厂商对应底层能力。没有这些证据时不开放 GS 精细编辑。**不能把它退化成穿透选择或屏幕红色贴片来交付。** 当前 GLB 的可见三角形→UV 选择继续保留，不伪称已适配 GS。

## 真正“建模成功”的验收

- 使用真实 AR 轨迹和相机内参；第一阶段要求人保持稳定、镜头移动。转头自拍涉及独立头部运动，不能混入静态背景轨迹硬算。
- 检查输入原分辨率、曝光、模糊、运动和各部位覆盖；不足时补拍，不用生成式细节填补。
- SDK 构建与保存均成功；验证完整 GS 文件字段、有限值、非空几何、坐标系、相机外参和可重新加载。
- 以未参加重建的原始视角核对鼻翼、唇缘、耳廓、痣/雀斑、纹理和发际线；重投影和局部误差不能被全图背景平均值掩盖。视觉接近不等于已证明毫米级几何准确度。
- 从不同角度检查孔洞、漂浮点、重影；只展示有拍摄证据的视角，不把未知背面补成标准脸。
- 验证圈选旋转跟随、遮挡、软边、保护、撤销、重开和 PNG 导出。原始模型与任何编辑版本分开存储。
- 只有以上都通过才原子登记个人资产并退出相机。当前代码不会执行该提交。

## 本轮实现、测试与许可

- `SpatialReconstruction.cpp/.h`：实际 SDK 会话控制、RGB/AR 输入接口、暂停恢复、前后台模式、保存、取消、纳秒时间戳、资源所有权、单任务和迟到回调隔离。
- `ReconstructionClient.ets`：类型化 ArkTS 任务接口；尚未接入个人拍摄 UI。
- `SpatialReconstructionTest.cpp`：注入 SDK 响应的逻辑测试，作为独立 Native 可执行文件在平板模拟器运行；**不是重建算法测试**。
- `GsProbe.ets`、`prepare-gs-fixture.py`：仅测试 HAP 的原创 162 点前后遮挡资源及官方 GS/蒙版/导出接口探针；不是真人、示例头像或产品能力。完成调用也不能自动标为遮挡/持久化通过。
- 未复用 Remy 私有实现、未引入其他重建引擎或新第三方依赖。商业 SDK 仅使用安装文件进行编译和接口核对，未将其实现、头文件全文或桩库复制进产品。

## 本轮实际验收结果

设备为 `127.0.0.1:5555` 的 API26 平板模拟器，x86_64；调试 HAP 已覆盖安装并恢复打开主界面。未卸载或清空应用数据。本轮未拍摄真人，未调用 DeepSeek，未向外部发送照片。

| 环境 / 项目 | 结果 | 证据与边界 |
|---|---|---|
| 构建：正式 HAP arm64-v8a / x86_64、测试 HAP | 通过 | `evidence/hap-build.log`、`evidence/reconstruction-gs/hypium-build.log`；编译不证明真机能力 |
| 平板：Native 任务控制、精确输入、回调与释放 | 23/23 通过 | `evidence/reconstruction-contract/results.json`；注入 SDK 回应，不是真实重建算法测试 |
| 平板：现有策略规则 | 12/12 通过 | `evidence/reconstruction-regression-policy/results.log` |
| 平板：既有 ES3 渲染、旋转、圈选、保护区、重复操作及 PNG 导出 | 像素回归通过 | `evidence/reconstruction-es-regression/pixel-checks.json`、设备日志及 PNG；公共示例/合成测试图，不是 GS 或本人重建 |
| 平板：重建、GS 渲染及编辑运行库 | 不可用 | `evidence/reconstruction-gs/capabilities.json`、`evidence/reconstruction-contract/results.json`；重建库加载失败，GS 能力查询为 false，不能进行实际 GS 加载/选择/导出验收 |
| 平板：GS 能力诊断流程 | 1/1 通过 | `evidence/reconstruction-gs/results.log`；仅“准确报告不可用”通过，不能读作 GS 功能通过 |
| 平板：3 项现有触摸 UI 自动化 | 失败：3 Error | `evidence/reconstruction-regression-ui/results.log`；`Driver.create()` 为 null，`delayMs` 调用失败；未掩盖或跳过 |
| 支持真机：本人建模、几何/细节、GS 精细圈选、内存/能耗/温度/耗时 | 未验证 | 待 AR 输入与主界面产物接线和支持设备；不能用模拟器逻辑测试替代 |
| 模型调用 | 本轮未验证 | 本轮未发生新的真实 DeepSeek 请求；Native 探针的后端健康检查为 `SELF_NETWORKKIT_UNVERIFIED`，不计为网络或模型通过 |

复现本轮专项检查：

```powershell
.\scripts\Test-ReconstructionNative.ps1 -Device 127.0.0.1:5555
.\scripts\Test-Native.ps1 -Device 127.0.0.1:5555 -BuildOnly
.\scripts\Test-DeviceSuite.ps1 -Device 127.0.0.1:5555 -Suite SELFNativeSpatialProbe -ExpectedTests 1 -Evidence docs/evidence/reconstruction-gs
.\scripts\Start-NativeProbe.ps1 -Device 127.0.0.1:5555
.\scripts\Collect-NativeProbe.ps1 -Device 127.0.0.1:5555 -Evidence docs/evidence/reconstruction-es-regression
```

最终结果以以上原始记录为准。没有真实输入、有效 GS 产物与细节验收，就不能宣称完整联调成功或保证流畅。
