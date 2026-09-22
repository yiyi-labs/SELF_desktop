# 2026-09-22～23 对话、沉浸视觉与平板相机核验

本轮从干净的本地提交 `e714eff` 继续修改，保留包名、签名配置、私有作品及用户资源。只向正在运行的 **MatePad Pro 13 平板模拟器** 安装和调试；当前端口为 `127.0.0.1:5555`，端口不代表固定机型。无手机或真机本轮验收结论。

## 实际改动

- DeepSeek 每次接收最近最多三轮短问答、明确的当前选区、已有图层和结构化选项。数字“1”绑定上一轮第一个选项；没有可绑定选项不能产生编辑。选中颜色与候选预设不符、改变当前选区、产品请求被变成通用染色时拒绝候选。内置预设对用户只显示“柔玫瑰/暖陶棕”。这不是任意自然语言均无冲突的保证。
- 去掉每次发送的整页弹窗。第一次在对话中简短开启本次云端会话，此后只有主动发送才上传静态视图和最近问答；设置可关闭，关闭或取消使旧响应失效。没有上传摄像头视频；新增外观候选仍需确认。
- 交互语气改为简短、亲切、平等的中文。外貌困扰不再被本地固定安慰语截断，允许 DeepSeek 结合用户点名或圈选回应；不主动指出痣、斑、皱纹等特点，不打分、强行夸赞、推销产品或保证改变后的心理效果。承接的话与唯一问题分别显示，重复问句会去重。没有偏好写入工具；模型出现“已保存/我记着”等不实提示时，展示层回退为仅本轮保留的简短回应，不更改操作。
- 圈画使用加粗双色轨迹和笔尖；松手后显示淡填充、发光边缘与虚线边界，转动/重新圈画后清除屏幕轮廓，防止错位。实际蒙版、授权、导出像素不依赖这层 UI。对话仍在选区旁出现。
- 原生背景增加可见的丁香紫、薄荷与暖桃色、柔光环、低速粒子；关闭运动保留静态环境。轻转改为按经过时间计算的小幅往返，避免帧率决定速度与累计漂移；选择“先看示例”可轻转，开始操作即停止。
- 起始页面直接展示“拍摄我的面容”。从系统相机 picker 改为本项目实现的 Camera Kit 原生 Surface 预览、能力枚举、前置优先和无声 MP4 采集路径。权限拒绝、切后台、关闭、缺失编码器均有处理，不以空文件冒充视频。当前平板只能验证预览，不能验证 MP4 成功路径。

## 相机配置、SDK 与格式

实际环境：DevEco Studio **26.0.0.821**，随附商业 SDK **26.0.0.105 / API26**，平板镜像 **HarmonyOS 7.0.0.106**、2880×1920。

华为官网当前列出的最新大版本为 [26.0.0](https://developer.huawei.com/consumer/en/doc/harmonyos-releases/2600)。HarmonyOS 使用 [Camera Kit 相机服务](https://developer.huawei.com/consumer/cn/doc/doccenter-references/api/camera-api)；本机已有该版本声明，不额外引入旧 Android/EMUI Camera Engine 包，不声称下载过新包或确认了最新补丁号。实现对照官方[原生录像说明](https://developer.huawei.com/consumer/cn/doc/HarmonyOS-Guides/native-camera-recording)中按设备查询规格、匹配预览/录像比例的要求，以及本机 `@ohos.multimedia.camera.d.ts` / `@ohos.multimedia.media.d.ts` 的 `getSupportedCameras`、`getSupportedOutputCapability`、`createSession`、`frameStart`、`getAvailableEncoder`、AVRecorder 配置核对。没有复制 SDK 文件或整份样例。

平板镜像 `features.ini` 原本已有 `camera.feature=on` 和 `camera.front.back.enable=on`；Windows 相机权限为 Allow，并识别 Integrated Camera / Integrated IR Camera。因此没有重置模拟器、改注册表或安装虚拟摄像头。`Check-TabletCamera.ps1` 可重查实际配置，且拒绝误选手机。本轮 Windows 记录到 Emulator 对摄像头的访问，应用得到真实 Camera Kit 预览启动事件。没有收集或向模型上传宿主摄像头的画面来充当测试图片。

“视频→个人3D”仍缺少可运行的重建环节。平板探针返回 Spatial Recon 运行库不可用。即使能够保存 MP4，也还需要有效的多视角、相机内参与位姿、重建和结果校验，不能把 MP4 改扩展名变成 GLB。当前真实重建/PLY/GSEdit 的门槛和格式分工继续见 [原生重建审查](native-reconstruction-review.md)，没有采用 Blender 运行时格式。

## 本轮证据

所有证据位于 `docs/evidence/interaction-camera/`；下表中的通过仅限列出的范围。

| 验证 | 结果 | 证据 |
|---|---|---|
| x86_64、arm64-v8a 原生 HAP 与测试包编译 | 通过；存在已有警告，debug unsigned | `final-build.log` |
| 平板协议/保护/作品/圈选/PNG UI 回归 | 14/14 通过；自然文案版本再次 14/14 通过 | `tablet-regression/hypium-results.log`、`tablet-voice-final/hypium-results.log` |
| 平板原生 GLB、贴图、蒙版、保护、EXIF、错误资源回滚、PNG 和六组产品开合 | 像素检查通过 | `tablet-native/probe.log`、`pixel-checks.json` |
| 真实 DeepSeek 图片＋两轮工具调用 | 通过：选中文颜色→回复“1”→原选区、轻柔强度、无产品植入 | `live-dialogue.json`；仅使用公开授权示例扫描 |
| 平板真实模型→确认→渲染→账单、第二次发送无重复弹窗 | 1/1 通过，实际提交 rose / 0.18、一条账单，随后撤销 | `tablet-voice-model/results.log`、`events.log` |
| 后端协议/HTTP/产品边界 | 30 项通过 | `backend-tests.log` |
| 部位相关的自然回应 | 两项真实调用通过不编辑、不推荐产品、简短回应检查；语气另经阅读核对，不代表全部表达都能通过 | `live-voice.json`：鼻部困扰、主动保留痣 |
| Windows 摄像头→平板 Camera Kit 预览与能力降级 | 1/1 通过，1280×720；测试只保存元数据 | `camera-environment.json`、`tablet-final-camera/results.log`、`tablet-camera-preview/events.log` |
| 平板 MP4 编码 | **失败/不支持**：第一次 prepare 失败；枚举显示只有 AAC 音频编码器，没有视频编码器。现在禁用录制按钮、继续预览 | `tablet-camera/results.log`、`tablet-camera-encoder-check/results.log`；后续预览通过不覆盖这两次失败 |
| 视频转个人3D、采集精度、真实表情/眨眼、真机录像与流畅度 | **未验证/未完成** | 平板 `SELF_RECON_SUPPORT available=false`；没有对应通过证据 |

另一次 `tablet-release/hypium-results.log` 在第13项出现 TestAbility 意外销毁，未计为通过，原因未能确定；检查时设备 faultlogger 目录无崩溃文件。这不证明没有问题。后续 `tablet-voice-final` 完整重跑14项通过，保留原中断记录。

## 示例人像为何静态

仍是既有 CC BY 3.0 Lee Perry-Smith 扫描，约 17,684 个三角形、1024 纹理，闭眼，未包含骨骼或表情形变。现有渲染器遵守烘焙外观基线，没有去光照后的皮肤材质或物理皮肤散射；这两个因素共同限制真实感。背景、视角运动不增加采集精度，不等于微表情，也没有扩充模型几何或伪造皮肤细节。原始几何与贴图均保留。真实人像替换必须建立在已验证的采集/重建资产上。

DeepSeek 上下文依据其[多轮对话说明](https://api-docs.deepseek.com/guides/multi_round_chat/)补齐；只携带有限的已显示问答，不伪造工具执行历史。视觉遵循已有 ArkUI 材质层次，氛围 GLSL 和交互代码为项目自写；没有下载网页装饰图、增加新第三方素材或宣称官方设计认证。
