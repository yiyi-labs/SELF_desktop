当前生效说明：[原生运行入口](../README-native.md)、[当前验收](validation-native.md)、[接口核对](api-compatibility.md)。以下为旧 Web/Component3D 路线历史记录；不作为当前实现或验收结论。

---

# 在 DevEco Studio 启动 SELF

核对日期：2026-09-22。请使用完整手机模拟器运行应用；本工程的 ArkWeb、文件、二进制桥和音频不以 Previewer 预览结果作为运行验收。

## 用 DevEco 启动

1. 打开 DevEco Studio，选择 Open，打开 `D:\STUDY\College\mine\olay` 根目录，不要只打开 entry 或单个 .ets 文件。等待工程同步完成。
2. 进入 Tools → Device Manager → Local Emulator，选择 `Pura 90 Pro Max` 并启动。本次已连接 `127.0.0.1:5555`，实际系统为 HarmonyOS 7.0.0 / API 26。编译 SDK 与模拟器系统镜像分别安装。
3. 在顶部设备选择框选中已经启动的手机。运行配置选择应用的 `entry`，然后点击主工具栏的 Run（绿色三角），不要点击 Previewer 面板的预览启动或 Hot Reload 作为首次运行。
4. 若检查运行配置：Run → Edit Configurations，使用 HarmonyOS/OpenHarmony App 类型，Module 为 entry，启动默认 Ability（本工程为 EntryAbility）。当前项目已有这类 entry 配置，无需改写 .idea 文件。
5. 在模拟器手机屏幕中使用 SELF。音乐默认关闭。当前 API 26 镜像的 ArkWeb 禁用了 WebGL，主界面会明确显示镜面不可用，不能据此称 3D 编辑可用。Previewer 中显示的页面或日志不是此模拟器中的应用。

如修改了 renderer-web 源码或需确保网页与音轨已同步，在 DevEco 的 PowerShell Terminal 执行一次完整构建：

```powershell
Set-Location 'D:\STUDY\College\mine\olay'
& .\scripts\Build-Hap.ps1
```

模拟器已经启动后，也可以在同一终端安装并运行：

```powershell
& .\scripts\Install-Emulator.ps1
```

多个设备连接时，脚本要求明确传入 `-Device '实际设备标识'`，避免误装到其他设备。未连接设备时脚本不能替代启动模拟器。

本工程尚未配置发布签名。此前 unsigned debug HAP 在已有 API 19 模拟器安装成功。如果 IDE 的 Run 流程要求签名，可先在这个已验证的模拟器上使用上面的安装脚本。真机或其他系统镜像的签名要求须另行按 DevEco 提示配置；不承诺所有目标都可安装 unsigned 包。

## 本次 Previewer 报错的含义

日志中的 `in the previewer is a mocked implementation` 明确说明 accessSync、mkdirSync、setWebDebuggingAccess 等接口处于预览器模拟实现。这些 W 级日志本身不表示应用文件权限出错。

真正终止页面的是 `TypeError: undefined is not callable`。提供的堆栈映射到 `SelfMirrorPage.ets:279` 的 Web `.onLoadIntercept(...)` 注册链，发生在 initialRender 阶段；它与预览器未提供完整 Web 接口的情况一致。仅凭该日志不能把问题归因于 API 26，也不能认定真实设备存在同一错误。

此回调用于限制带原生桥的页面导航，不应为让预览器显示而直接删掉。实际 ArkWeb、文件与音频请在完整模拟器验证。之前已通过的模拟器检查记录保留在 `docs/evidence/`，不代表 Previewer 已适配。

## API 26 已构建并安装，图形能力仍有失败项

当前 `build-profile.json5`：

```json
"targetSdkVersion": "26.0.0",
"compatibleSdkVersion": "5.1.1(19)"
```

- 本机实际构建 SDK 为 HarmonyOS 26.0.0 / API 26，版本 26.0.0.105。
- targetSdkVersion 为 26.0.0；compatibleSdkVersion 是最低兼容版本，不是把构建 SDK 降成 API 19。
- 最新实测系统为 `emulator 7.0.0.106(SP1DEVC00E999R4P11)`，`const.ohos.apiversion=26`；本机已经有 API 26 镜像，不需要再因旧说明重复安装。
- 实际 ArkWeb 为 `7.0.0.105` / Chromium 144。启动参数带 `--disable-3d-apis`；WebGL1/2 均返回 `disabled by enterprise policy or commandline switch`。显式应用级 `disableWebGL:false` 未解决，已撤回该无效设置。没有修改全局系统策略。
- 保持最低兼容 API 19 也可以在 API 26 设备上测试；若使用仅 API 26 提供的功能，需要兼容分支，或明确放弃旧设备后将最低兼容版本提高到 26.0.0。仅修改这个数值不会安装新镜像，也不会修复 Previewer 的模拟接口。

API 26 的安装和原生界面启动已验证，ArkWeb 的 3D 渲染失败；历史 API 19 的通过记录不等于当前镜像通过。新的失败处理保持原生消息桥可连接，但不会向无渲染器的页面发送模型或开放编辑。

## 原生迁移验证入口（不是产品新设计）

2026-09-22 用户明确要求优先原生实现，并保留原来的完整设计。`EntryAbility` 仍打开原版界面，`NativeProbeAbility` 是单独的研发验证页，不能用它替代产品界面或宣称迁移已完成。

已构建并安装最新 HAP 后，可显式运行 `scripts/Start-NativeProbe.ps1 -Device 127.0.0.1:5555`。DevEco 也可在单独的应用运行配置中选择指定 Ability `NativeProbeAbility`。恢复原界面选择默认 `EntryAbility`，或再次运行 `Install-Emulator.ps1`。

原生试验曾显示带纹理的 GLB，但眼口外观异常；重新运行还出现 `Creating scene manager failed`。因此没有替换原版主入口。详见 [原生与建模路线核对](native-reconstruction-review.md)。

参考：[华为预览器问题说明](https://developer.huawei.com/consumer/cn/doc/doccenter-tools-faq/faqs-previewer-operating-7)、[创建本地模拟器](https://developer.huawei.com/consumer/cn/doc/doccenter-deveco-studio/ide-emulator-create)、[升级到 26.0.0 的官方指南](https://developer.huawei.com/consumer/en/doc/harmonyos-releases/upgrade-adaptation)。

