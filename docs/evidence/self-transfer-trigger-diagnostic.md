# 手机轻碰 MatePad Edge 屏幕：现场诊断

用户确认：手机完整模型页、平板 SELF 主页，均亮屏解锁、华为分享开启；手机轻碰平板屏幕后没有系统动画或卡片；两端登录不同华为账号。

华为官方手机与 PC/2in1 的碰屏幕分享使用约束明确要求相同华为账号。该文档从 API 23 加入 Tablet 支持，但账号约束的文字仍写 PC/2in1；现场 MatePad Edge 需先满足这一条件，再实际复验。不同账号是已发现的官方使用条件缺口，不冒充已证实的唯一故障原因。

官方依据：https://developer.huawei.com/consumer/cn/doc/doccenter-capabilities/knock-share-pc-phones-overview.md

真实窗口调试读数（设备日志当地时间 2026-10-07 11:17:21，requestId 10703）：

| 读数 | Pura 80 Pro | MatePad Edge |
| --- | --- | --- |
| sdkApiVersion | 26 | 26 |
| deviceType | phone | tablet |
| HarmonyShare syscap | true | true |
| windowId | 358 | 1354 |
| 前台页面 | VIEWER | HOME |
| phase | SEND_READY | RECEIVE_READY |
| 已完成打包 | true | false（接收端无需打包） |
| sendRegistered | true | false |
| receiveRegistered | false | true |
| knockCallbacks / receiveCallbacks | 0 / 0 | 0 / 0 |

这证明应用进入可发送/可接收状态，未证明系统物理碰触触发或无线交付成功。用户复碰仍无卡片。没有执行账号登录、更换、注销，也没有重置设备数据。

本轮加入 debug-only Want 诊断，读取真实页面/窗口/监听/回调计数，不添加产品 UI，不含模型路径、内容或账号信息。测试以 requestId 校验新鲜读数，并等待实际前台 Ability 就绪。测试安装/启动会重启应用，不能用重启后 HOME 读数否定先前 VIEWER 状态。

最终验证：两仓库正式 debug HAP 与 ohosTest HAP 构建成功并覆盖安装；SELFTransferDiagnostics 各 1/1、Failure 0、Error 0；主机专项各 29 通过、0 失败、1 个实际样本测试未重跑（此前已有 30/30 记录）。最终诊断测试中 phone 为 HOME 手动接收、tablet 为 HOME 自动接收，符合官方限制。物理碰触、原生卡片、上滑及无线传输仍未通过验收。

后续人工步骤：两端登录相同华为账号；亮屏解锁并开启华为分享；重新打开手机已保存的完整原始模型、平板保持 SELF 主页；用手机轻碰屏幕有效区域，按系统卡片提示上滑发送。同账号后若仍无响应，再看回调计数及系统触发条件，不直接归因于 SDK 版本。


## 后续已成功与当前版本状态

用户之后确认无线传输成功；修复dataReceive监听时序后，用户确认平板不再跳文件管理器；再修复沙箱返回记录的路径/UTD解析和已保存试色后，用户明确回复“成功了”，对应自动打开、原名和口红颜色接续。初始账号差异仅保留为历史排查信息，没有证据能认定它是唯一原因，也未操作任何账号。

此后完成双视角源码和电脑验证（两工程41/41，相机数学各3/3，API26正式签名HAP构建成功）。用户要求录屏期间不要安装平板；本轮双视角包两端均未安装，也未重启/操作录屏设备。不能将前一版本的用户成功反馈当作新双视角真机验收。
