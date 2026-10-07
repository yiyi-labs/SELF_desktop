# SELF Transfer Protocol v1

本文件在 `olay` 和 `olay_harmony` 中保持完全一致。传输兼容性只依据 schema、protocolVersion、requiredFeatures、formatContract，不依赖设备、bundleName 或 producer.variant。

## 物理包与传输

一个模型对应一个标准 ZIP 文件：`SELF_<name>_<UUIDv4>.self3d.zip`。HarmonyOS Share Kit 使用一个 `general.file` record，内容为官方 file URI；不携带模型字节、Base64、网络地址或目录。生产压缩/解包仅使用官方文件级 `zlib.compressFile/decompressFile`，压缩等级 0，`keepTopLevelFolder:false`。

```text
manifest.json                 必需，UTF-8 JSON，最多 64 KiB
model/model.ply               必需，保持原始字节
preview/preview.png           可选
viewer/viewer_state.json      可选，最多 64 KiB
extensions/...                可选扩展资产，必须在 assets 登记
```

包内路径是区分大小写的相对 ASCII 路径；允许目录段字符 `[A-Za-z0-9_.-]`，禁止 `.`、`..`、绝对路径、盘符、反斜杠、空中间段、重复 entry、链接、加密、多卷和重叠文件数据。ZIP 支持 classic/ZIP64、store/deflate；解包前以只读元数据检查器验证中央目录和本地头路径及尺寸，拒绝 Unicode alternate-path extra field，实际编解码仍由官方 zlib 完成。4096 个 ZIP entry、256 个 manifest assets 是元数据防护限制，不是模型字节上限。

## Manifest

```json
{
  "schema": "self.transfer.package",
  "protocolVersion": 1,
  "packageId": "74776304-fada-4cdc-aaf3-b8f9000dba4b",
  "createdAt": "2026-10-06T12:00:00.000Z",
  "producer": {
    "appFamily": "SELF",
    "variant": "olay_harmony",
    "appVersion": "0.1.0",
    "bundleName": "com.self.mirror.harmony"
  },
  "displayName": "收到的星辰",
  "model": {
    "kind": "gaussian-splatting",
    "format": "ply",
    "formatContract": "self.gsplat.f32le.sh0-3.logscale.logit.wxyz.v1",
    "entry": "model/model.ply",
    "byteLength": 123456,
    "sha256": "<64 lowercase hexadecimal characters>"
  },
  "assets": [{
    "role": "model",
    "path": "model/model.ply",
    "required": true,
    "byteLength": 123456,
    "sha256": "<same model SHA-256>"
  }],
  "requiredFeatures": ["model.ply"],
  "optionalFeatures": []
}
```

以上摘要和长度是示意，生产由实际文件生成。`protocolVersion` 为数字 1，packageId 为小写 UUIDv4。producer 是诊断来源，不能选择协议分支。model 信息必须与必需的 model asset 一致。所有现存登记资产都验证实际长度和 SHA-256；缺失可选资产允许继续导入，缺失必要资产拒绝。未知 requiredFeatures 或未知必需资产拒绝；未知 optionalFeatures 忽略。任何未登记的文件拒绝。不得包含账号、token、数据库、私有目录、sourceFrame、后端 URL 或设备绝对路径。

## Canonical PLY

契约 ID：`self.gsplat.f32le.sh0-3.logscale.logit.wxyz.v1`。

- `ply\nformat binary_little_endian 1.0`，仅一个 vertex 元素，所有 scalar property 为 float32，文件长度精确匹配头部。
- 必需属性：x/y/z、f_dc_0..2、opacity、scale_0..2、rot_0..3。
- `f_rest_*` 为连续的 0、9、24 或 45 个属性，对应 SH0、SH1、SH2、SH3；按名称查找，属性顺序可不同。额外 float32 属性原样保留。
- 坐标是原模型坐标；scale 是对数，opacity 是 logit，旋转顺序为 wxyz（rot_0 为 w）。检查所有值有限且四元数非全零。
- 传输和导入绝不量化、重排、重写 PLY 或转换颜色、坐标、SH。接收文件 SHA-256 必须与 manifest、发送原文件一致。
- 两端 PlayCanvas 2.22.4 源码采用同一表示。绝对单位、重建世界轴方向不能仅凭属性名称证明。视觉朝向由相同 camera/target/up 保留；仍需真机人工核验视觉结果。

## 可选 Viewer 状态

```json
{"schema":"self.transfer.viewer","version":1,"camera":[0,0,3],"target":[0,0,0],"up":[0,1,0],"fovDegrees":45}
```

只包含有限的三维向量与 10–90 度视角，camera 与 target 不重合，up 非零。特性名 `viewer.camera.v1`。接收适配器生成自身的 `portrait.view.json`；无有效 viewer 状态时根据模型包围盒产生默认视角。该状态不包含发送端私有 metadata 或编辑 recipe。

## 方向、能力与生命周期

角色由当前页面决定：有效且已保存的当前模型 Viewer 为 SEND；主页/列表为 RECEIVE；拍摄、重建、保存、导入、不可中断编辑为 NONE。只发送明确打开的 modelId，绝不回退到最近模型。Viewer 可临时 FORCE_RECEIVE，完成/取消/退出恢复 AUTO。原有试色是独立 recipe，无法表示为已保存 PLY 时禁止发送，避免收到不同外观。

每个真实前台 windowId 一个 TransferCoordinator，稳定 callback 引用，切换方向先 off 旧监听，再 on 新监听。后台/窗口销毁/页面失效清理监听。手动文件复制与自动接收互斥，生命周期 generation 使迟到任务无法发布模型。发送包提前准备，并按当前模型 revision、mtime、size 复用；触碰回调只提交已经准备好的文件。

按用户最终界面要求，不显示左上角传输提示栏，也不显示自定义准备/发送进度文字或自制发送弹窗。触碰后的卡片、滑动动作、发送反馈由鸿蒙系统处理，具体呈现由设备系统版本决定。必要的「接收模型」「取消接收」「导入模型文件」动作置于原有设置菜单，导入成功刷新原列表并请求打开收到的模型；错误详情仅记录日志，可在设置重试。

按 API 26 本地 SDK 和华为官方说明：

| 系统能力 | 行为 |
| --- | --- |
| API < 20 | 不调用新 HarmonyShare API，隐藏模型交接入口，保留原有应用功能 |
| API ≥ 20 且支持 HarmonyShare | 注册发送入口；API 可用性不决定 SEND/RECEIVE 角色 |
| 2in1；tablet API ≥ 23 | RECEIVE 使用 `dataReceive` 接收到空的应用沙箱目录 |
| phone（包括 API 26） | 官方 `dataReceive` 不响应；系统收文件后选择用 SELF 打开，或 SELF 主页选择「导入收到的模型」 |

ZIP 不支持官方指定应用自动拉起，因此不伪造 shareBundleName 自动直达。用户已确认接受手机手动打开导入。`share()` resolve 仅表示已交给系统，不表示传输完成或对端导入成功。自动接收必须同时获得文件 SharedData 与 `SHARE_SUCCESS` 后才导入；取消/失败删除临时文件。

## 原子导入与清理

收件先进入 `cache/self_transfer/incoming/<UUID>/`，不写正式模型。先检查 ZIP 元数据、空间，再官方解包到 staging；校验 manifest、全部已声明资产和完整 PLY。接收端生成新的 32hex 本地 modelId，移动验证后的 PLY 到隐藏 pending 目录，生成本地 view/receipt，以 rename 发布完整模型目录，随后通过现有 PortraitStarStore.upsert 更新原索引。失败回滚目录；原模型不覆盖、数据库 schema 不改。

`self-transfer.json` 是本地去重 sidecar，不进入传输协议。相同 packageId/摘要再次导入返回已有 modelId；相同 packageId/不同摘要拒绝。删除模型时通过原 Repository 清理 sidecar。每次收件/解包/发布前检查空间；大文件使用 URI、文件复制/移动、官方文件 SHA，业务层每次读取不超过 1 MiB。没有人为模型大小上限。

成功或失败均清理 incoming/staging；发送缓存保留 24 小时以避免 share Promise 返回后提前删除仍由系统使用的文件，后续运行回收过期内容。清理只能在本模块拥有的目录下执行。

## 官方依据

- [HarmonyShare API](https://developer.huawei.com/consumer/cn/doc/doccenter-references/api/share-harmony-share.md)
- [应用沙箱接收](https://developer.huawei.com/consumer/cn/doc/doccenter-capabilities/knock-share-pc-phones-sandbox.md)
- [应用间碰一碰互传](https://developer.huawei.com/consumer/cn/doc/doccenter-capabilities/knock-share-pc-phones-mutually.md)
- [碰一碰概述](https://developer.huawei.com/consumer/cn/doc/doccenter-capabilities/knock-share-pc-phones-overview.md)
- [文件打开接入](https://developer.huawei.com/consumer/cn/doc/doccenter-capabilities/share-access-one-step.md)
- [系统分享接入](https://developer.huawei.com/consumer/cn/doc/doccenter-capabilities/share-interface-description.md)

真实签名以安装的 API 26 `@hms.collaboration.harmonyShare.d.ts`、`@hms.collaboration.systemShare.d.ts` 与 `@ohos.zlib.d.ts` 为准。禁止旧 Android OneHop、自定义 NFC/蓝牙/Wi-Fi 协议、云端或 Windows Backend 中转。
