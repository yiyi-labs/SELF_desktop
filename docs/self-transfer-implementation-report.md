# SELF 模型互传实施与验证记录

已在两个正式工程接入 API 26 SDK 的官方 HarmonyOS Share Kit、统一包协议和各自的模型 Repository。两端都有发送与接收/导入能力。左上角所有自定义传输提示已按用户要求删除，使用系统原生分享界面；手机显示名称改为「SELF」。**尚未执行人工碰触、上滑发送、真机 GPU 外观验收，因此不能宣称全部最终验收完成。**

## 原始工程与 SDK

| 项目 | olay | olay_harmony |
| --- | --- | --- |
| 初始分支 | master | master |
| 初始 HEAD | c4a8262 | a261c12 |
| bundleName | com.self.mirror | com.self.mirror.harmony |
| 显示名称 | SELF | SELF（原 SELF 端侧版） |
| 模型 | Stage | Stage |
| module / Ability | entry / EntryAbility | entry / EntryAbility |
| window | onWindowStageCreate 的真实主窗口 ID | 同左 |
| target/default compile SDK | 26.0.0 | 26.0.0 |
| compatible SDK | 5.1.1(19)，未提高 | 5.1.1(19)，未提高 |

DevEco Studio 26.0.0.821；安装 SDK 26.0.0.105/API 26。compileSdkVersion 没有单独显式覆盖，由 target/default SDK 解析。完整 Git 初始状态、最近五次提交、SDK 声明、真实 PLY header/bounds 与源文件摘要在各仓库 `docs/evidence/self-transfer-api26-audit.json`。原有未提交的 FreckleDemo、渲染器、素材、日志等保持原状，未纳入本任务提交。已有编辑器文件仅选择性提交传输相关修改。

## 官方支持与用户确认的调整

参见两端一致的 [SELF Transfer Protocol v1](self-transfer-protocol-v1.md) 及文末华为官方链接。API 26 SDK 中存在 window capability 版本的 on/off、SharableTarget.share、ReceivableTarget.receive；均按本地 d.ts 实现，没有使用 Android OneHop 或自建传输链路。

华为明确：phone 上 dataReceive 不响应；tablet 自 API 23 支持，2in1 支持。ZIP 不支持指定应用碰一碰自动直达。用户已明确接受手机由系统收文件后手动用 SELF 打开/导入，平板使用沙箱自动接收。手机主页或接收覆盖状态下也可从现有设置选择「导入模型文件」。内部 bundleName 保留不同值以维持安装身份、签名与旧数据；桌面名称两端均为 SELF。

API < 20 不调用新 HarmonyShare API，隐藏交接入口，其余业务保持。API ≥ 20 先检查 HarmonyShare 系统能力；平板/二合一按官方接收能力选择自动入口，phone 的页面角色仍可为 RECEIVE，只是传输入口是系统文件接收后手动导入。未在 API 19 实机运行，旧系统保护由自动测试验证。没有采用 API 26 才新增的 apiAvailable 函数来保护 API 19，以免保护函数本身在旧系统缺失。

## PLY 契约审计

| 项目 | 两端共同证据/契约 |
| --- | --- |
| loader | PlayCanvas 2.22.4，同一 PLY parser/GSplatData 实现摘要 |
| encoding | binary_little_endian 1.0 |
| property type | float32 scalar；按属性名查找，顺序可变 |
| 基本属性 | x/y/z、f_dc_0..2、opacity、scale_0..2、rot_0..3 |
| 球谐 | 支持 SH0–3，连续 f_rest 属性数 0/9/24/45；实际代表样本为 SH3 |
| opacity | logit，Viewer 使用 sigmoid |
| scale | 对数，Viewer 使用 exp |
| rotation | wxyz，rot_0 为 w |
| 坐标 | 传输保持原坐标；Viewer 模型变换为 identity，camera/target/up 确定视角 |
| 额外属性 | float32 原样保留；拒绝不支持的编码/结构，绝不偷偷转换 |

绝对世界单位和重建坐标轴不能仅由 header 推断。两端同编号 0670... 的样本 SHA 相同，不能据此声称来自独立设备生成；另选择手机仓库不同摘要的 0748... 作为第二代表样本。传输格式严格为 `self.gsplat.f32le.sh0-3.logscale.logit.wxyz.v1`。已有试色是独立编辑 recipe，不是持久化修改后的 PLY；包含未固化编辑时禁止发送，避免把原始外观伪装成当前外观。

## 实际修改

两端均新增 `entry/src/main/ets/transfer/`：

- SelfTransferContract、TransferState、TransferCoordinator：协议、页面角色、互斥监听、生命周期与迟到任务隔离。
- HarmonyShareBridge、SelfTransferRuntime：唯一 Share Kit 边界、真实 windowId、稳定回调、系统 Want/文件选择导入。
- TransferFiles、SelfTransferZipGuard、SelfTransferPly、SelfTransferPackage：官方 ZIP/文件 SHA、分块验证、安全解包、空间检查和缓存回收。
- ModelExportAdapter、ModelImportAdapter：通过现有 PortraitStarStore 导出当前模型，原子登记新本地模型，包编号去重。

最小接入文件：EntryAbility.ets、SelfMirrorPage.ets、PersonalPortraitEditor.ets、PortraitStarStore.ets、module.json5；新增 List.test.ets suite 注册、SelfTransfer.test.ets、audit/test 脚本、协议与证据文档、package.json 的 test:transfer 命令。手机另外修改 AppScope 的 app_name。没有修改后端契约、PLY 内容、算法、数据库 schema 或新建数据库，没有软链接、submodule 或影子工程。

## 页面方向与系统界面

| 状态 | 行为 |
| --- | --- |
| 当前已保存模型 Viewer，加载完成且无编辑事务 | 提前准备包 → SEND_READY，注册 knockShare，sendOnly:true |
| Home / 模型列表 | RECEIVE_READY；不会发送最近模型 |
| Viewer → 设置 → 接收模型 | 临时 FORCE_RECEIVE；取消/完成/离开恢复 AUTO |
| 拍摄 / 重建 / 保存 / 导入 / 未固化编辑 | NONE，移除两个方向监听 |
| 后台 / 窗口销毁 / 页面失效 | 清理监听，generation 使迟到结果不可发布 |

没有左上角传输文字、进度栏或自制发送弹窗。碰触回调将准备好的一个 file URI 提交给系统；“上滑发送”的具体 UI 属于设备系统，代码不能自行保证某个动画。share Promise resolve 只记录 SELF_SHARE_SUBMITTED，不声称对端成功导入。接收必须同时得到 SharedData 和 SHARE_SUCCESS；取消/失败不导入。原列表刷新后通过原有 openStar 流程请求打开收到的模型，MODEL_OPEN_REQUESTED 日志不伪装成已完成 GPU 加载。

## 组合与模型完整性验证

| 方向 | 协议/适配器自动测试 | 真机碰一碰 |
| --- | --- | --- |
| olay → olay_harmony | 通过，含实际保存 PLY 往返 | 未执行 |
| olay_harmony → olay | 通过，含不同实际保存 PLY 往返 | 未执行 |
| olay → olay | 通过，独立源码导入/导出适配器测试 | 未进行双真机同版本测试 |
| olay_harmony → olay_harmony | 通过，含实际保存 PLY 往返 | 未进行双真机同版本测试 |

以下是主机隔离临时目录测试的原始文件和导入文件摘要，所有 match=true。完整点数、包围盒、路径、时间与主机峰值 RSS 在各仓库 `docs/evidence/self-transfer-real-models.json`。

| 样本 | 字节 | vertex count | 源/收到 PLY SHA-256（相同） |
| --- | ---: | ---: | --- |
| tablet 代表 0670... | 54,784,393 | 232,131 | d0cd64a70d99d55fcff037766030e138aff7a193cb801d39b43fb31d2fe8873a |
| phone 代表 0748... | 18,746,720 | 79,429 | 44f7f814ee61231843e2c500b76d35e42fd01157cbdb562d234c794eebe95540 |
| 当前手机仓库最小保存样本 f3a0... | 6,759,572 | 28,636 | 3c3495d42f4fd0bd9875a9431ec5af64f883074af6c64581d65e9359f78be053 |
| 当前手机仓库最大保存样本 a2ce... | 73,848,473 | 312,911 | 53fd1ac282cb7d9287b55b611e9fd3deca5607c7db203646e1eeb930dad8a8c8 |

真实接收文件经过接收方安装的 PlayCanvas readPly 解析，点数与关键属性存在且长度一致；业务验证器的完整点数/包围盒前后一致。主机 ZIP 是明确标注的 Python zipfile 测试替身，不冒充官方设备 codec；官方 zlib 已分别在连接的 phone 和 tablet 实际测试。主机测得打包约 0.15–0.51 秒、导入约 0.14–0.36 秒，仅为当前机器结果；RSS 包含 Viewer parser、运行时和全部测试，不代表 HarmonyOS App 峰值内存。未测真机大文件 CPU/RAM、无线时间、100/300/500 MB 扩展样本、GPU 色彩或视觉朝向，不宣称这些已通过。

## 构建与测试结果

| 验证 | olay | olay_harmony |
| --- | --- | --- |
| API 26 正式 debug HAP | BUILD SUCCESSFUL | BUILD SUCCESSFUL |
| API 26 ohosTest HAP | BUILD SUCCESSFUL | BUILD SUCCESSFUL |
| 传输专项（含实际 PLY 测试） | 30/30 | 30/30 |
| 原 renderer-web tests | 24/24 | 24/24 |
| 原 viewer-gs 全集 | 66/84，18 个既有失败 | 108/126，18 个既有失败 |
| 原 star-naming 脚本 | 既有 harness TypeError | 既有 harness TypeError |
| 真机 SELFTransferNative | 2/2，ResultCode 0 | 2/2，ResultCode 0 |

传输专项覆盖：页面角色、20 次反复进入无重复监听、退出/后台/忙碌、覆盖与取消、迟到打包/导入隔离、手动复制互斥、真实 windowId/同一 callback off、API 19 不调用接口、phone 手动接收、官方回调数据/结果两种顺序、取消后绝不导入；包生成、原始字节不变、版本/特性、缺文件、坏 SHA/长度/PLY/ZIP、路径穿越/盘符/绝对路径/重复路径、本地与中央头不一致/Unicode alternate-path、重复导入、空间不足、四组合及真实模型解析。

既有失败已使用内存中的 Git HEAD 页面/Store 源码复跑，数量和错误相同，没有回滚工作树。原因：ply-contract 指向不存在的 backend/.sources/playcanvas 依赖；17 项 universe-native-journey 测试夹具缺 clearPreviewToolsTimer；star-naming 夹具缺 tr 方法。没有为掩盖问题修改渲染器或无关导航。项目未配置独立 npm lint，Hvigor ArkTS 编译与 compatibility checks 保持开启；仍有已有警告及 guarded API 高版本/异常提示警告，未禁用检查或提高最低版本。生产与测试包均覆盖安装成功，使用 `install -r` 保留数据，未卸载。

## 可重复验证

```powershell
npm run test:transfer
# 使用两个正式仓库中的实际保存样本；默认不要求这些本地未入库的大文件：
$env:SELF_TRANSFER_REAL_MODELS='1'
npm run test:transfer
```

Python 优先 SELF_TRANSFER_TEST_PYTHON，其次本机 bundled runtime，最后 python。测试只在系统临时目录建立模型 Repository，不修改正式用户模型。四组合测试读取两个正式仓库的源码，需要两个仓库均在同级目录。

构建日志：各仓库 artifacts/self-transfer-build.log、self-transfer-native-build.log。测试日志：self-transfer-tests.log、self-transfer-existing-tests.log、self-transfer-viewer-tests.log、self-transfer-viewer-baseline.log、self-transfer-star-tests.log、self-transfer-star-baseline.log、self-transfer-native-device.log。受审计证据与原生测试日志另外存入 docs/evidence；原有 docs/evidence/hap-build.log 未被本任务改写或提交。

## 尚待人工最终验收

已连接 phone 与 tablet，各自官方 ZIP/SHA 接口测试通过，且新版已安装启动。实际设备顶部碰触、系统卡片与上滑发送、两方向无线传输、手机「用 SELF 打开」、收到模型的 GPU 加载/朝向/颜色仍需人工实操。双方 Viewer 时需在一端设置里选择接收；双方 Home 时不应发送。现场没有第二台对应版本设备，未宣称同版本双真机验收。

代码、协议、构建和自动测试已落实；最终 Git commit hash 见任务最终回复。完整产品验收仍以上述人工结果为准。
