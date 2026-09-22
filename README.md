# 当前版本请先读 README-native.md

正式主界面现已使用原生 ES3；当前状态、运行方式与 DeepSeek 接入见 [README-native.md](README-native.md) 和 [最新验收](docs/validation-native.md)。以下内容为迁移前历史说明，其中 WebGL/Remy 主路线及云模型未实现的描述不再代表当前代码。

---

# SELF · HarmonyOS 离线镜面原型

这是已编译的 Stage 工程。核心编辑闭环曾在 **API 19 手机模拟器**通过定向测试；当前 API 26 镜像的 ArkWeb 禁用了 WebGL，**不能完整运行 3D 编辑**。这也不是 FINAL 文档全部条目的验收完成版。真实个人照片的系统选择成功路径、自动定位、专项保护例外、相册保存、真机和人群公平测试仍未完成或未验证；请先读 [完整验收清单](docs/validation.md)。

2026-09-22 最新方向：保留原版设计，优先原生实现，并以 Remy 的 3DGS 使用体验核对采集、重建和保存。新增原生 Component3D 研发入口可以构建，但存在真实外观/启动失败，没有替换默认主界面；个人重建尚未接入。详见 [原生与 Remy 路线核对](docs/native-reconstruction-review.md)。

初始目录为空；使用用户提供的 `SELF_HarmonyOS_Codex_Prompt_FINAL.md` 建立工程，未叠加旧提示词。未发现 AGENTS.md。DevEco 实际安装在 `C:\Program Files\Huawei\DevEco Studio`，Downloads 路径是安装包来源。

## 已交付能力

| 能力 | 状态 |
|---|---|
| 原生 ArkUI + 本地 ArkWeb/WebGL2 + 内嵌纹理 GLB | 实际 API 19 模拟器通过 |
| 原生二进制桥、闭合圈选、确认后编辑、撤销/重做、保存/重开/删除作品 | 实际模拟器通过 |
| 多角度旋转、缩放、回正、轻转与视角保存 | 实际模拟器验证拖动、圈选冻结、旋转后保存重开；PHOTO 仍是平面 |
| 柔和彩色氛围、光晕、粒子、玻璃回复区 | 已接入；运动可关闭，背景装饰不改脸部 shader 或 PNG |
| 舒缓音乐开关 | 三段随包音轨，原生播放/切换/后台暂停通过；默认关闭 |
| 根据主动话语调整氛围 | 有限本地规则，生产 Node/Hypium 验证；真实键盘闭环待独立输入法许可 |
| 原貌/当前效果保护、同管线对照、PNG 私有保存 | 有真实执行与像素检查；保护仅一处，范围见验收表 |
| 唇色与局部颜色 | **通用数字表达**，公共闭嘴样本；不是品牌实测 |
| PHOTO 平面编辑、裁切、平移/缩放 | 生产代码与桌面测试通过；系统选图取消通过，实际选入照片成功路径待模拟器验证 |
| OLAY Super Serum 1 oz 美国资料 | 官方文字摘要与来源；配方编号未知，无标定、无包装图复用 |
| 可播放观察层 | 自有颜色参数色块动画，不表示真实功效，不修改作品 |
| 私密文字 | 原生主动保存/修改/删除实现；不是心理治疗，临床审阅未完成 |
| 自动唇区/痣雀斑定位、个人 3D、云 AI、产品功效模拟 | **未接入**，没有假完成按钮 |

## 打开与构建

第一次在 IDE 启动，请先看 [DevEco 启动步骤与 Previewer 报错说明](docs/start-in-deveco.md)。完整功能应通过 Device Manager 启动手机模拟器，再运行应用 entry；Previewer 只提供部分接口的模拟实现。本工程已使用 API 26 SDK 构建，最低兼容 API 19 不等于只能在 API 19 运行。

在 DevEco Studio 打开本根目录，使用已安装的 HarmonyOS 26.0.0 SDK。工程兼容目标 API 19，当前默认产品不含签名账号/密钥。不要把 unsigned 测试包当可发布包。

本机 PowerShell 可执行：

```powershell
Set-Location 'D:\STUDY\College\mine\olay'
& .\scripts\Check-Environment.ps1
# 如依赖缺失，使用 node 直接调用 npm，规避本机 CMD AutoRun 改目录：
& 'C:\Program Files\nodejs\node.exe' 'C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js' ci --ignore-scripts
& 'C:\Program Files\Huawei\DevEco Studio\tools\node\node.exe' 'C:\Program Files\Huawei\DevEco Studio\tools\ohpm\bin\pm-cli.js' install
# 原始授权资产已随工程附带；重新抓取才需要网络：
& .\scripts\Fetch-Assets.ps1
& 'C:\Program Files\nodejs\node.exe' .\scripts\prepare-assets.mjs
& 'C:\Program Files\nodejs\node.exe' .\scripts\validate-assets.mjs
& .\scripts\Build-Hap.ps1
& .\scripts\Install-Emulator.ps1
```

安装目录不同时，为 PS 脚本传 `-DevEcoHome '实际路径'`。多个设备连接时必须为安装/原生测试脚本传 `-Device 'hdc列出的设备'`；不会自动挑真机。已有模拟器实例可从 DevEco Device Manager 启动。当前实例曾以官方命令启动：

```powershell
& 'C:\Program Files\Huawei\DevEco Studio\tools\emulator\Emulator.exe' -start Huawei_Phone -instancePath 'C:\Users\30243\AppData\Local\Huawei\Emulator\deployed' -imageRoot 'C:\Users\30243\AppData\Local\Huawei\Sdk' -bootMode coldboot -noWindow
```

许可接受只在本用户明确同意之后执行过；脚本不替他人自动接受新协议。需要可见模拟器窗口时由 DevEco 打开，不要重复启动同一实例。

产物：`entry/build/default/outputs/default/entry-default-unsigned.hap`；交付副本在 `artifacts/SELF-debug-unsigned.hap`。构建脚本先更新 rawfile，再构建 HAP，避免网页源码与包内版本分离。依赖、原资产、renderer 与 native 源码都保留，不是只交示例截图。

运行 `scripts/Package-Delivery.ps1` 可重新生成 HAP 副本、`artifacts/SELF-source-and-evidence.zip` 与 SHA-256 清单；压缩包排除依赖缓存、签名、构建目录，保留实际源码、许可、资产和证据。HAP 构建会先生成三段本项目舒缓音轨，无外部音乐服务。

## 使用

启动即显示明确标记的公共示例，无登录、问卷或扫描。可输入“自然一点”获得候选，再点“试一下”；“保留现在”不修改。工具内可调淡/换色，明确调节不重复索取授权。圈选时闭合路径且只使用可见表面，完成后进工具选择局部试色或“这里别动”。保护原貌与保护当前效果是两个不同选项。

“作品与记录”保存成功操作和保护锚点，支持重开与删除。原样也能在工具中“保存当前画面 PNG”。导出位于应用私有目录，不会谎称进了系统相册。当前每次覆盖私有 `self-export.png`，无发布/分享功能。

示例 head 的 CC BY 3.0 署名是 Lee Perry-Smith / Infinite / www.triplegangers.com，见 [来源许可](docs/references.md)。个人照片不是扫描重建：只作为本地平面操作；不上传、不自动定位唇部，不因导入失败改变原作品。

可以拖动转头、双指缩放，或点“轻转”慢速观察。圈选、对照、详情和后台会停止轻转。音乐默认关闭；“氛围”里可切换微光/暖阳/清透、关闭柔和运动或关闭“随我的话语调整”。当前规则只处理少量明确表达，不是任意聊天情绪识别。现有闭眼扫描没有表情骨骼，尚不能眨眼或微笑。

视觉参考了华为最新官方公开的光感与空间设计，实际使用 API 19 可运行的材质实现；没有把旧模拟器声称为 HarmonyOS 7 真机。设计依据、约束与已发现问题见 [设计审查](docs/design.md)。

## 测试与证据

```powershell
& .\scripts\Test.ps1
& .\scripts\Test-Native.ps1
# 从本项目全新启动的主应用状态执行端到端；只操作测试应用自身数据：
& .\scripts\Install-Emulator.ps1
$env:SELF_DEVICE='127.0.0.1:5555' # 仅本次示例，按实际 list targets 结果填写
& 'C:\Program Files\nodejs\node.exe' .\scripts\emulator-full-test.mjs
# 沉浸检查也从全新主应用状态执行：
& .\scripts\Install-Emulator.ps1
& 'C:\Program Files\nodejs\node.exe' .\scripts\emulator-immersive-test.mjs
```

`Test.ps1` 的桌面测试需要 Chrome；自定义安装路径设置 `SELF_CHROME`。它不冒充模拟器。Hypium 测试直接导入生产 ArkTS 规则，在测试 HAP 中执行。完整模拟器脚本用官方 hdc/uitest 操作原生 UI，并将 CDP 输入发到实际 HAP 的 ArkWeb，记录像素导出与原生文件落盘。

- [实际模拟器截图](docs/evidence/emulator-full/initial-ui.png)、[候选授权界面](docs/evidence/emulator-full/consent-ui.png)、[真实导出](docs/evidence/emulator-full/after-compare.png)
- [模拟器完整流程](docs/evidence/emulator-full/results.json)、[Hypium 原生结果](docs/evidence/native-tests.log)
- [桌面基础结果](docs/evidence/browser/results.json)、[桌面保护与生命周期结果](docs/evidence/browser/advanced-results.json)
- [模拟器音乐/氛围/旋转结果](docs/evidence/immersive/results.json)、[新版界面](docs/evidence/immersive/initial-ui.png)、[减少运动专项](docs/evidence/browser/design-results.json)
- [协议](docs/contracts.md)、[环境](docs/environment.md)、[28 项验收](docs/validation.md)

## 调试与常见问题

Native 使用 DevEco 日志/HiLog 过滤 SELF。Web 仅 Debug 开启官方调试；`emulator-full-test.mjs` 从当前 PID 找调试 socket，建立本项目端口 9223 并在结束清理。原生包名 com.self.mirror。不要硬编码上次 PID；不要清理其他任务的转发。

- GLB 纹理倒置：本资产打包时 V 已翻转一次，不要再对加载材质随机 flipY。
- 本地 GLB 内嵌纹理加载失败：ImageBitmapLoader 使用 blob fetch，CSP 需保留 `connect-src blob:`；不需要开放 HTTP。
- 对照导出被裁切：RenderTarget 的 viewport 是物理 texel，不能再调用受 DPR 放大的屏幕 setViewport；已保留回归测试和旧失败截图。
- WebGL context 恢复后背景不同：Three 恢复时重建内部状态，本项目重新设置清屏颜色再重放有效状态。
- 模拟器照片选择器动画未结束：测试需等待系统浮层消失；不要点击其下方不可见的原生控件。
- SDK 字符串：本机接受 target `26.0.0`；曾用 `26.0.0(26)` 导致构建失败，已经纠正。
- HAP unsigned：当前 API 19 模拟器实装成功；真机需要正式签名，未代用户登录或配置证书。

`docs/historical/SpikePage.ets` 与 `scripts/emulator-test.mjs` 仅保存最小纵向验证历史，不是当前应用入口或当前完整测试命令。

