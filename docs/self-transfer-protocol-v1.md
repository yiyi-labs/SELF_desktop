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

只包含有限的三维向量与 10–90 度视角，camera 与 target 不重合，up 非零。特性名 `viewer.camera.v1`。接收适配器生成自身的 `portrait.view.json`；无有效 viewer 状态时根据模型包围盒产生默认视角。该相机状态不包含发送端私有 metadata。

## 方向、能力与生命周期

角色由当前页面决定：有效且已保存的当前模型 Viewer 为 SEND；主页/列表为 RECEIVE；拍摄、重建、保存、导入、不可中断编辑为 NONE。只发送明确打开的 modelId，绝不回退到最近模型。Viewer 可临时 FORCE_RECEIVE，完成/取消/退出恢复 AUTO。已保存试色通过 extensions/saved_edits.json 接续；正在预览、比较或尚未保存的变化禁止发送。

每个真实前台 windowId 一个 TransferCoordinator，稳定 callback 引用，切换方向先 off 旧监听，再 on 新监听。后台/窗口销毁/页面失效清理监听。手动文件复制与自动接收互斥，生命周期 generation 使迟到任务无法发布模型。发送包提前准备，并按当前模型 revision、名字、试色记录 revision、mtime、size 复用；触碰回调只提交已经准备好的文件。

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

## 已保存试色扩展（本次现场修订）

两端现有 SET_HISTORY 均支持 rose/terracotta 和 .18/.32/.5 的相同颜色重放语义，已用实际 applyDigitalLayers 对比 float32 颜色数组。已保存且非预览状态允许发送。在 extensions/saved_edits.json 写入 self.transfer.edits/version=1、原 PLY SHA-256/字节数/点数、按原顺序的分组和图层（名称、时间、颜色、强度、base64 mask、FNV-1a checksum）。不带发送端 modelId、账号、planner 或对话数据。文件登记为 saved-edits required asset，requiredFeatures 加 viewer.edits.v1；原始无试色包仍只需 model.ply。旧版本接收端必须拒绝无法恢复的外观，不能静默丢掉颜色。

源 v2 history 经过严格核验与字段筛选，legacy recipe/mask 转为同一 v2 重放语义；原 PLY 不烘焙、不修改。接收端校验扩展与 PLY 的绑定、最多 12 组/16 层、mask 实际长度和摘要、已支持的颜色与强度，写入新 modelId 的 portrait.edit.v2.json，交给原查看器恢复。沿用现有 history 的 4 MiB 元数据读取边界，此限制不限制 PLY 文件大小。

自动沙箱接收必须保留 dataReceive 监听直到收到 data 与 SHARE_SUCCESS；active 防止重复接受。官方文件记录中的本地路径或归一化 UTD 不沿用外部文件打开的 URI 类型假设，但任何文件都必须直接位于本次专有 incoming session，经过 ZIP/manifest/资产 SHA/PLY/试色校验后才发布到 models 并请求打开。


## 双视角接续（API 26 互传修订）

碰一碰回调触发后，从当前完整模型的实际已渲染相机帧读取 position/quaternion/FOV/clip。四元数转换成相机朝向的 target/up，包含旋转、俯仰、平移和缩放；不把视角当作模型变换，不改 PLY。当前视角登记在 viewer/arrival_view.json（self.transfer.viewer/version=1），单独资产 SHA-256。每次真实发送使用新 packageId，以便同一模型连续两次发送不同视角和正确去重。PLY/试色校验与复制在页面就绪时预先完成；触碰时只读取小视角数据并由官方 zlib 流式生成最终包，不重做 PLY 解析/摘要。已发布基础 ZIP 保持不可变，保留的原始打包目录归 outgoing 缓存管理。

已记录正脸单独登记在 viewer/front_view.json（self.transfer.front-view/version=1），绑定完整 PLY SHA-256；携带 pivot/front/up、头部尺寸、fitDistance/fitFovY/fitAspect/sceneR、resolver/config/render contract。仅允许符合现有 render-contract 的 verified v2 正脸，或保留真实 pitch-limited 标记的已保存有限俯仰记录。剔除原设备 sourceFrame、输入图片引用、inputVersion 和文件路径，来源改记 self-transfer，避免接收端用缺失的原始拍摄输入否定已验证的几何记录。有限俯仰结果仍保持 verified=false，不能升级宣称为完整正脸。正脸/当前视角登记为 required camera asset 并声明 viewer.camera-pair.v1，旧接收端应明确拒绝，不静默忽略用户要求的视角。

接收端长期写入 models/<新本地ID>/portrait.view.json 及 portrait.profile.json 或 portrait.fallback.json，默认保存正脸，而非发送时的临时角度。arrivalView 随导入结果送给原页面，使用进程内一次性 Map，在完整查看器第一次读取 view 时取走；列表/预览不消费它，后续正常打开也不从磁盘或旧传输包读取它。页面模型ID作为查看器实例键，接收另一模型时释放旧相机绑定与编辑器。两端均支持这套持久/一次性语义；平板通过同一投影拟合函数适配新屏幕，手机沿用已有正脸应用函数。复用正脸时不重新调用人脸分析；正常 PLY 读取与GPU绘制仍然需要。

没有已保存正脸的旧模型保留已有默认 camera/target/up/FOV，不伪造正脸分析结果。相机向量、退化方向、FOV/clip、正脸哈希、版本、正交性、头部尺寸均校验；正脸/试色在准备或发送期间改变则拒绝陈旧包。手机仍按华为官方 API 26 的设备能力限制，由系统收文件后用 SELF 手动打开；应用层的模型包、校验、相机和试色收发代码一致。


## ArkWeb相机结果与操作失败恢复

runJavaScript执行JSON.stringify返回的结果可能再包一层JSON字符串，视角读取应解析该层再校验SelfViewerState，兼容直接对象JSON并拒绝null/undefined/退化相机。单次触碰的视角/系统操作失败后恢复当前页面监听，让下一次物理触碰可重试；不自动再次调用target.share。离页后的旧操作错误应按当前页面恢复角色，不注册原模型。真实错误与准备阶段记录在debug诊断，不添加产品UI。
