> 2026-09-23 最新：[拍摄、跟踪与 Remy 参考核验](docs/camera-tracking-validation.md)。平板模拟器已能实际录制无声 MP4、保存和回放；新增本机CPU人脸检测与鼻尖锚点。真人转头贴合按用户要求稍后测试；个人3D重建和背景虚化尚未完成。

> [全屏相机与设置](docs/camera-fullscreen-validation.md)、[对话与背景](docs/interaction-camera-validation.md)是之前的阶段记录，其中“只能预览”已由本轮软件录像实现更新。后续调试使用平板。

# SELF：当前原生版本

这是对现有工程的增量迁移。原版柔和界面、包名、音乐、作品和偏好保留；正式镜面已换为 HarmonyOS 原生 C++ EGL/OpenGL ES3。用户提供的新规范是 `SELF_HarmonyOS_Native_DeepSeek_Codex_20260922.md`。

**本版不是完整验收完成版。** API26 模拟器已有真实图形/触摸/导出证据；DeepSeek 真实合成图片＋tool 两项和实际本机后端请求已通过；平板模拟器上的图片→DeepSeek候选→授权→原生检查→提交→账单已实测通过。真机未测试。示例模型、通用数字颜色、资料动画不冒充个人重建或真实产品功效。

## 运行

DevEco 打开本项目根目录，使用已装 SDK26.0.0。Device Manager 启动已有 Pura 90 Pro Max 或 MatePad Pro 13，选择 entry / EntryAbility，运行到对应模拟器；Previewer 不作为原生 Surface/文件/网络/音频验收环境。

```powershell
& .\scripts\Build-Hap.ps1
& .\scripts\Install-Emulator.ps1 -Device '127.0.0.1:5555'
```

本机 DevEco 在 `C:\Program Files\Huawei\DevEco Studio`。构建脚本为本机 CMD AutoRun 目录问题提供局部适配；若 IDE 直接 Native 构建失败，使用该脚本构建后安装，不修改注册表。发布签名尚未配置；当前 unsigned debug HAP 只证明在该模拟器可安装。

## 使用与模型

默认拖动3D面容旋转，双指缩放。“圈画”或手写笔登记关注范围；附近浮出对话和可选动作。所有新的外观修改先由真实模型提出候选，“试一下”授权后通过原生检查才生效。平板宽屏常用工具浮在画面上，窗口缩窄时改用紧凑布局。支持对照、撤销/重做、保存/重开；照片是可平移缩放的平面，唇区需手工精细确认。保护可保留原貌或当前有效效果；单次例外只作用于明确的那一项。

本次会话首次发送时可在对话旁开启云端图片理解，开启后后续发送不重复弹框，可在隐私设置关闭。拒绝时仍可查看、圈画、撤销、重做已授权历史和恢复原图，不产生新的外观修改。后端密钥只放 `backend/.env`；配置后执行 `scripts/Start-Backend.ps1`，并按 [模型配置](docs/model-contract.md)建立模拟器8787端口映射。`SELF_BACKEND_TOKEN` 是你自己的后端访问口令，不是 DeepSeek API key；开发回环模式可留空。没有密钥时不会冒用离线模板当 DeepSeek。

导出是原生 PNG，保存到应用私有目录 `files/self-export.png`，不是相册或公开分享。原始图、操作与蒙版保存在手机本地；旧作品不被重写。

产品卡只在模型本次回复实际引用相关产品时出现，支持原生3D旋转、开盖和右侧堆叠资料卡；新请求或取消会收起。跟进“这款”会保留核验后的产品身份，不改推其他产品。**目前产品参数模拟未完成**：大陆资料只核验到部分渠道名称/规格，缺少可用的效果标定，产品请求不会拿通用染色替代。3D包装为原创近似外观示意。

## 验证与交付

```powershell
& .\scripts\Test-Native.ps1 -Device '127.0.0.1:5555'
& .\scripts\Start-NativeProbe.ps1 -Device '127.0.0.1:5555'
& .\scripts\Test-Stress.ps1 -Device '127.0.0.1:5555' # 十分钟，一次真实模型请求后仅重放已授权历史
& .\scripts\Test-Backend.ps1
& .\scripts\Test-Backend.ps1 -Live # 有密钥后，真实 API 用量，原创无隐私图片
& .\scripts\Package-Delivery.ps1
```

- [本轮改动与建模/产品边界](docs/overhaul-implementation.md)、[本轮验收](docs/validation-overhaul.md)。
- [此前原生验收结果](docs/validation-native.md)（区分当前通过、已修复失败和未验证）。
- [SDK 与接口](docs/api-compatibility.md)、[资产/保存/迁移](docs/asset-contract.md)、[模型/隐私协议](docs/model-contract.md)、[许可](docs/references.md)。
- 原生源码 `entry/src/main/cpp`；客户端 `entry/src/main/ets`；后端 `backend`；共享协议 `shared/contracts`。
- 交付 `artifacts/SELF-debug-unsigned.hap`、`SELF-source-and-evidence.zip`、`delivery-manifest.json`。

旧 renderer-web 和历史证据保留供追溯；旧浏览器测试脚本不作为当前原生版本验收。主界面只有一个原生引擎，不自动回退到浏览器或照片占位。
