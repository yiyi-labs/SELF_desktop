# 面容引导真机复测（2026-09-23）

设备：HUAWEI MatePad Edge QXS-W10，HarmonyOS 7 / API 26，USB HDC 连接。构建使用本机 DevEco Studio 商业 SDK，调试签名沿用工程已有配置。

## 已证实的问题和修复

`LocalFaceGuide.ets` 从 Camera Kit 的第二路预览收到 1920 × 1080、CameraFormat 1003 的 NV21 缓冲区。旧代码创建 PixelMap 时只传 `pixelFormat: NV21`，漏了 `srcPixelFormat`。商业 SDK 的 `InitializationOptions` 明确把 `srcPixelFormat` 定义为**输入缓冲区格式**，未设置时默认为 BGRA_8888；`pixelFormat` 是**生成的 PixelMap 格式**。因此旧代码把 NV21 数据按 BGRA 读，导致分析图像下半部接近黑色，两个检测器持续报 0 张脸。华为 [预览帧格式说明](https://developer.huawei.com/consumer/cn/doc/doccenter-dev-faq/faqs-camera-63) 也要求 CameraFormat 1003 对应 NV21，并根据格式正确创建 PixelMap。

现在按 `srcPixelFormat: NV21, pixelFormat: RGBA_8888` 创建图像，再缩放和检测。修复前真机分析帧四象限红通道均值约 `98,98,16,16`，原始 Y 通道却为 `134,156,113,94`；修复后分析帧约 `151,176,104,83`，下半部不再丢失。统计仅记录通道均值，不保存或记录人像像素。

华为 Core Vision Kit `faceDetector.init()` 在该平板返回 `true`。排查时四方向识别探针及原有本地 CNN 均成功运行；正式路径只在与预览一致的方向检测。恢复 SDK 的预览旋转 180° 后，真机日志出现 `faces:1`、本地检测置信分数 86–90，并出现一次 `SELF_CAMERA_GUIDANCE_FOLLOWING`。UI 也出现“看见你了”。随后面容离开或识别中断时小圈会复位，因此**持续跟踪稳定性与面部粒子贴合度尚未通过**。UI 不会把“没有检出”伪装成已锁定。

## 本轮链路证据

- 签名 HAP 在真机安装成功，应用启动、前置相机预览和 1920 × 1080 NV21 分析帧持续工作。
- 拍摄键恢复后，Camera Kit / AVRecorder 的 1920 × 1080 MP4 在真机完成开始、停止和落盘：一次测试记录 `durationMs:16220`、`bytes:16205805`。这是测试片段，应用内删除动作有 `SELF_CAMERA_CAPTURE_DISCARDED` 日志；没有把片段用于建模，也没有保存到仓库。录像启动/停止顺序按华为[录像开发说明](https://developer.huawei.com/consumer/cn/doc/doccenter-capabilities/camera-recording)调整。
- 空白场景中原本本地 CNN 偶尔报 1 张脸而 Core Vision Kit 报 0，存在误锁风险。现已改为系统检测先确认同一张脸，本地 CNN 高频跟随；一次空白场景复测未锁定。真实面容慢速移动下的灵敏度、误锁率和粒子贴合尚待复测，不能把单次复测当成稳定性结论。
- App 经 USB/HDC 反向端口访问本机服务，`SELF_RECON_USB_HTTP` 报 `protocol:1, binaryRoundTrip:true`，二进制往返已验证。
- 后端分块上传、SHA-256 校验、断点幂等和鉴权的两个 `unittest` 用例通过。
- 当前 `engine` 仍为 `not-verified`，相机页面可手动录制高清片段，但**未自动录制或上传**，也未生成个人 3D 资产。真机多视角采集质量、重建计算、GLB/3DGS 回传与显示尚未通过，不得据此宣称整链完成。

## 后续验收条件

完整面容在画面内，检测器连续检出同一张脸，移动镜头后提示消失、小圈及低透明度粒子真实贴合面部；录制出包含足够视角且清晰的源片；Windows GPU 端重建产物经过资产校验并回传真机显示。若视频视角不足或重建失败，必须明确失败并允许重拍，不能显示示例面容代替结果。
