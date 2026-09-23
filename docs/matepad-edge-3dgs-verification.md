# MatePad Edge 真机签名与 3DGS 验证

核对日期：2026-09-23。本报告补充模拟器结论，不能用真机的显示能力替代个人重建验收。

**签名、覆盖安装、原生 GS 测试模型显示和画面 PNG 保存已通过。当前这台平板的官方重建查询返回 801；GS 改色没有产生像素变化，PLY 保存没有完成。SELF 仍不能在这台设备上完成“拍摄本人 → 生成本人 3D → 贴脸圈选编辑”的完整流程。**

## 实际环境

| 项目 | 实测值 |
| --- | --- |
| 设备 | HUAWEI MatePad Edge，型号 QXS-W10，tablet |
| 系统 | QXS-W10P 7.0.0.107(SP8C00E105R6P5)，Release，API26 |
| ABI | arm64-v8a |
| 开发环境 | DevEco Studio 26.0.0.821；商业 SDK 26.0.0.105 |
| 包名 | com.self.mirror；测试模块 entry_test |

用户已完成华为账号登录及自动签名。为 default 构建产品关联现有 default 签名配置，保留用户生成的证书和私密配置。正式包及测试包均使用 **signed.hap**；两次覆盖安装输出均为 `install bundle successfully`。没有卸载或清空数据。

本地真机安装包为 `artifacts/SELF-device-debug-signed.hap`，校验值见 [signed-package.json](evidence/matepad-edge-spatial/signed-package.json)。它是设备调试包，不是上架发行包。源码 ZIP 的签名材料隔离检查见 [delivery-signing-check.json](evidence/matepad-edge-spatial/delivery-signing-check.json)，现有后端凭据扫描也通过；当前源码归档与本机可运行工程的签名配置有意不同。

物理设备序列号、账号信息和私密签名材料不进入本报告或 Git。项目本地 `build-profile.json5` 保留用户的签名配置，不提交该工作区文件。源代码打包脚本现在会在 ZIP 中去除签名配置和产品签名引用，并排除证书文件，不改写本地原文件。

## 真机结果

最新完整对照运行位于 [control-run](evidence/matepad-edge-spatial/control-run)。[freshness.json](evidence/matepad-edge-spatial/control-run/freshness.json) 确认报告落在本次设备时间区间内；测试框架 **1 项失败、0 项通过**，不能把 HDC 的退出码 0 或 `test finished` 当作功能通过。

| 项目 | 结果 | 证据和边界 |
| --- | --- | --- |
| 正式 / 测试签名包构建 | 通过 | [测试包构建](evidence/matepad-edge-spatial/signed-build/hypium-build.log)、[正式包构建](evidence/hap-build.log)；保留 SDK 警告，编译不代表功能通过 |
| 正式 / 测试包真机安装 | 通过 | control-run 的 app-install.log、test-install.log |
| 原应用启动恢复 | 通过启动请求 | restore-app.log：start ability successfully；探针进程退出后重新启动正常入口 |
| 设备重建运行库及 API26 符号 | 存在且应用可加载 | 实际位置 `/system/lib64/ndk/libspatial_recon_ndk.z.so`；应用 report 的 libraryLoaded、api26Symbols 为 true |
| 官方 GS 重建支持查询 | **未通过：801** | 多次真实调用 `HMS_SpatialRecon_IsSupport(SPATIAL_RECON_MODEL_TYPE_GS)`；available 为 false |
| 原生 GS 插件、PLY 载入、显示 | 通过最小合成样本 | pluginLoaded、nodeLoaded 为 true；512×512 PNG 可见前层绿色测试点。只是 162 点资源，不代表大模型流畅性 |
| GS 画面 PNG 保存 | 通过 | gs-before.png、gs-after.png、gs-control.png 均由真机 Component3D 组件截图生成；不是浏览器截图，也不是 PLY 保存 |
| 2D 蒙版圈选后改色 | **未通过** | selectBy2DMask / paint 调用完成，但修改前后变化像素数为 0 |
| 全部测试点索引选择后改色对照 | **未通过** | 选择 0–161 全部合成点并改红，主动请求渲染后仍为 0 变化像素；不能仅归咎于蒙版 |
| 官方 PLY 保存 | **未通过** | saveToPLY 使用官方示例所示的沙盒绝对路径，15 秒未返回；此前 file URI 形式在超过 60 秒的测试等待内也未完成。一次直接回收文件检查为不存在 |
| GS 前后遮挡、旋转绑定、保存重开后的圈选 | 未验证 | 调用成功不证明表面选区正确；没有将这些标志设为 true |
| 本人重建、保真、耗时、峰值内存、发热 | 未验证 | 本轮没有个人采集或实际训练；没有降分辨率、删点或借示例面容替代个人结果 |
| DeepSeek 图片、工具调用及账单 | 本轮未验证 | 本轮没有发起模型调用或上传个人照片 |

[pixels.json](evidence/matepad-edge-spatial/control-run/pixels.json) 记录三个 PNG 的相同 SHA256、前层绿色像素 208920、两个改色检查均为 0 变化像素。这是对编辑失败的证据，不是通过指标。

## 801 的含义和当前限制

安装的商业 SDK `spatial/spatial_recon_interface.h` 把 801 定义为 `SPATIAL_RECON_STATUS_DEVICE_NOT_SUPPORT`。IsSupport 的说明要求以当前硬件、系统和环境实际判断。**现在只能认定本设备当前环境没有通过官方 GS 重建支持检查，不能进一步断言这款硬件永远不支持。**

这台真机与此前模拟器不同：它已经有重建、GS 渲染、GS 编辑运行库。仅查 `/system/lib64/` 顶层而未找到重建库，会漏掉 `/system/lib64/ndk/` 下的真实实现。也不能将 SDK 链接桩安装进设备补能力。

IsSupport 附近的应用日志还出现 AI/GPU 驱动相关加载失败和符号缺失。它们是待厂商核查的线索，尚不能据此认定单一根因或提供可靠安装修复；未绕过系统权限、替换系统库或强行创建未获支持的会话。

此外，SELF 自身仍缺少已经通过验收的 AR 图像、内参、真实相机位姿采集接线，以及个人产物入库、保真验收和 GS 表面编辑。即使以后支持查询变为成功，也不能跳过这些实现和真机质量门槛。

## 修正及失败追踪

1. 原资源读取失败 9001005：测试资源属于 entry_test，原先通过生产模块资源管理器读取。改为显式测试模块上下文后，设备接收的 PLY 与源文件字节完全一致。
2. 原模型载入 SIGSEGV：原先先建 Scene、后装插件。按华为空间渲染示例，先等待插件加载，再创建 Scene，最新多次运行载入成功。ASCII 改为二进制本身没有消除崩溃，不能将失败误归因于 ASCII。
3. 原截图错误 100001：界面条件首先检查非观察字段，导致初次短路之后没有随状态重建 Component3D。改为专用观察状态后 PNG 正常生成。
4. 增加分步骤报告、明确异常码、自动超时、重复编辑保护、全索引对照和进程清理。保存失败会明确使专项测试失败，不延长等待后伪称成功。
5. 合成资源由本项目 `prepare-gs-fixture.py` 生成，标准二进制小端 PLY，162 个高斯点，含 SH 属性、尺度、旋转和不透明度。仅测试 HAP 持有，非个人头像、非重建输出。

早期 `gs-probe-module-context.json` 的时间戳与前一轮相同，**是崩溃后取回的旧文件**，不能作为该轮结果。早期运行记录只用于追踪失败；结论优先采用 control-run 的新鲜报告。

`runtime-library.json` 记录的是静态符号核验时的状态，其中 appRuntimeCallsValidated=false；后续实际应用查询以 control-run 报告为准。单独的 shell ELF 探针在真机执行被拒绝 Permission denied；没有绕过限制，改用已签名应用测试。emulator-probe-check 子目录仅属模拟器，不能混进真机通过项。

## 官方核对与复用范围

- [空间渲染 API](https://developer.huawei.com/consumer/cn/doc/harmonyos-references/spatial-recon-spatialrender)：本轮实际读取官方公开文档正文，核对插件与 Scene 初始化顺序、GSNode 导入 URI 和 parent 参数。
- [空间编辑 API](https://developer.huawei.com/consumer/cn/doc/harmonyos-references/spatial-recon-spatialedit)：本轮实际读取正文，核对 selectBy2DMask、selectByIndex、paint 和 saveToPLY。保存示例使用沙盒路径；示例的路径拼接和节点创建不能不加核验地照抄。
- [重建 C 接口](https://developer.huawei.com/consumer/cn/doc/harmonyos-references/capi-spatial-recon-interface-h)：具体类型、返回值及函数签名同时核对本机商业 SDK 26.0.0.105 的头文件和 Native 文档。

应用和探针代码为项目内实现，仅采用官方调用约定，未复制整套示例或引入新重建引擎。原创合成 PLY 无新增第三方资产许可。华为 SDK 和设备运行库按其安装许可使用，仅本地核对，未提交或分发库二进制、完整头文件或官方文档全文；本轮没有采用 OpenHarmony 示例版本表作为商业机型保证。

## 复测与下一步

保持 USB 调试及当前设备签名，在项目根目录运行，设备标识用 `hdc list targets` 查到的实际值：

```powershell
.\scripts\Test-SpatialDevice.ps1 -Device '<真机标识>' -Build
```

脚本只接受指定目标，使用签名包覆盖安装，自动运行合成探针，按设备时间拒绝旧报告，保存新鲜的部分失败证据，最终释放探针进程并恢复正式入口。失败时返回错误是预期行为，不能删掉断言来“变绿”。设备所有者不是默认用户 100 时，脚本的数据回收路径需要调整，当前只验证了本设备默认用户。

`Test-SpatialCapabilities.ps1` 是另一个 shell 级诊断工具；其运行上下文与应用不同，且本真机拒绝执行此 ELF，不作为真机首选复测方式。`Test-Native.ps1` 本轮只用于 BuildOnly；原模拟器安装流程使用 unsigned.hap，不能直接用于真机。

下一步应携带本报告的具体型号、系统版本、801 返回值和合成编辑最小复现，向华为确认此版本对 GS 重建及编辑的支持条件，或在官方确认支持的真机复测。不需要先租云服务器。支持条件明确后，再完成并验收 AR 采集、本人建模和稳定表面圈选；不能现在承诺完成时间或流畅程度。
