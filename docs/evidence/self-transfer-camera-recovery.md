# 双视角版本碰一碰回归修复

用户在双视角版本覆盖安装后反馈又提示不支持碰一碰。2026-10-07 现场调试诊断（requestId 1071201）：手机 API26/window387、VIEWER、knockCallbacks=1、prepared=true，但 phase=ERROR、sendRegistered=false，message为“系统未能发起发送，请重新碰一碰”；平板window1453/HOME/RECEIVE_READY、receiveRegistered=true、receiveCallbacks=0。系统已触发手机回调，失败在应用发送准备阶段。

原因：ArkWeb runJavaScript 返回 JSON.stringify 的字符串结果时，结果是外层 JSON 字符串。旧代码只执行一次 JSON.parse 得到 string，而非 SelfViewerState，对有效相机调用 validViewer 返回false；外层桥接将具体错误统一成系统发送失败，协调器又永久注销监听，后续碰触无法注册内容。SDK没有失去支持。

修复：共用 parseWebCameraResult 解析外层字符串并验证实际相机，兼容直接对象 JSON；发送错误保存真实原因和准备阶段；仅在发送/系统接收操作失败后恢复当前页面监听，不自动重发、不在打包失败时循环重试。切换页面期间旧操作失败时按新页面重新判断SEND/RECEIVE，防止注册旧模型。两端同步。加入显式 debug-only selfTransferProbe，用实际ArkWeb和官方zlib验证准备链路，不调用target.share，不更改模型索引或文件。

两端 API26 正式签名HAP构建成功，install -r 覆盖安装并启动，未卸载。手机真机诊断（requestId 1071203，日志12:33:56.221）：API26/window391、VIEWER/SEND_READY、sendRegistered=true、knockCallbacks=2、lastSendError为空；sendPreparation.stage=ready、error为空；cameraRead.encoding=json-string、resultBytes=328、valid=true。这证明真机确实使用带外层JSON字符串的返回格式，并已完成读取与官方最终ZIP。平板真机诊断（同requestId，日志12:33:56.532）：API26/window1465、LIST/RECEIVE_READY、receiveRegistered=true、receiveCallbacks=2。

用户随后明确反馈：“卡片、传输和首次视角都正常”。这是本次修复版的物理碰触、系统卡片、实际交付及首次视角人工验收，不仅是主机替身测试。

两仓库完整回归各44/44、失败0、跳过0，保留实际PLY样本和PlayCanvas解析、名字/试色、单次视角和长期正脸的既有覆盖；新用例验证真实返回编码、第一次准备失败后同模型第二次碰触可发送、离页后恢复接收而非旧发送。日志：artifacts/self-transfer-camera-recovery-tests.log、self-transfer-camera-recovery-build.log。源码与用户既有改动均保留在工作树，未提交无关编辑。
