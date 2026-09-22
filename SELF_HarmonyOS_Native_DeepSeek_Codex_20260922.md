# SELF：鸿蒙原生渲染 + DeepSeek 多模态编辑｜完整实施规范

核对日期：2026-09-22。交付对象：在用户现有工作区实际实施的 Codex。

## 0. 任务性质、证据与替换范围

在当前 SELF 工程中实际完成原生面容渲染与 DeepSeek 图像理解驱动的编辑闭环，不只写方案或留下模型 TODO。用户此前给出的目录是 `D:\STUDY\College\mine\olay`，先核对当前工作区、AGENTS.md、未提交修改和实际代码。

已知运行报告：鸿蒙 7.0 / API 26 模拟器可安装、启动现有界面，但 ArkWeb/WebGL2 面容显示失败。原生 OpenGL ES 尚无本次独立验证结果。不要把报告中的错误文案当成已定位的根因。

本规范替代此前“ArkWeb/Three.js 为手机主渲染器”“模型仅作为可选占位”的实施条款。保留现有包名、签名、作品、偏好与有效业务代码，不卸载、不清数据、不整仓重写。旧提示词中的产品真实性、面容自主权和沉浸交互要求在本规范中继续落实。

截至本次读取，DeepSeek 官方模型表将 `deepseek-flash` 标为支持 Vision / Tool Calls / JSON Output，`deepseek-v4-pro` 标为不支持 Vision。实际接入前用真实配置作能力测试；模型名称、端点与能力不从旧文章推断。此处没有完成用户电脑上的构建、运行或付费 API 调用，实施者必须实际验证。

## 1. 唯一生产架构

鸿蒙客户端：
ArkTS / ArkUI（Stage 应用、现有业务状态）
→ 类型化 N-API 窄接口
→ C++ 面容编辑渲染器
→ EGL / OpenGL ES 3.0
→ XComponent 的 SURFACE。

云端规划：
客户端主动提交文本及获准的静态图像
→ 一个轻量后端（已有后端优先；新建时 Python / FastAPI + HTTP 客户端 + 类型校验）
→ DeepSeek Vision + Tool Calls
→ 候选编辑计划
→ 客户端核对最新授权和状态
→ 原生渲染器执行。

不把大模型部署到手机，不每帧调用云模型，不让模型输出任意 GLSL/C++/可执行代码。不再将 ArkWeb、Three.js、WebGL 或 MediaPipe Web GPU 作为核心链路前提。网页渲染可保留为开发参照，但没有第二套生产作品或自动回退引擎。

渲染表示为带 UV 的网格、真实/示例纹理、语义蒙版与版本化操作。首版不开发高斯泼溅渲染器、全脸生成式重绘或长期护肤效果预测。

## 2. 最新接口的采用规则

优先级：本机实际商业 HarmonyOS SDK 的声明/头文件/示例 + 对应版本的华为官方文档；其次官方 OpenHarmony 文档与源码用于交叉核对；第三方文章不作接口契约。

保留已安装 API 26 工程的有效配置。读取并记录 DevEco、SDK、NDK、编译模式、target/compatible 配置、模拟器镜像、ABI、hdc 和 Hvigor 的实际版本。不编造 `26.0.0` 字段的格式、wrapper、导入名或不存在的 API。当前官方网页动态加载或访问失败时，记录这一限制并核对本地 SDK，不声称所有网页正文均已核实。

“使用当前推荐接口”不等于把所有调用换成最高 API 的新接口，更不等于贸然切换 ArkTS 编译模式。新增代码与现有工程使用同一受支持的互操作机制。保持最低兼容版本必须有接口和链接依据；只改 compatible 数字不能使高版本 Native 符号在旧设备可用。

拟采用的正式能力：
- Stage / UIAbility：`@kit.AbilityKit`；沿用现有生命周期入口。
- UI：ArkUI；新独立组件优先状态管理 V2，支持时采用 `@ComponentV2`、`@Local`、`@Param`、`@ObservedV2`/`@Trace`。不能在同一 struct 混用 V1/V2 装饰器，不为了迁移图形重构全部已正常页面。
- 自绘：声明式 XComponent SURFACE + Native `OH_ArkUI_SurfaceHolder` 生命周期，具体见下一节。
- 帧调度：NativeVSync；不用 UI setInterval 驱动 GL，也不叠加多套帧回调。
- 网络：`http` from `@kit.NetworkKit`，异步访问自己的后端；第三方密钥不进 HAP。
- 图片选择：`photoAccessHelper` from `@kit.MediaLibraryKit` 的系统选择能力。
- 图片解码/编码：`@kit.ImageKit` 或同 SDK 对应的 Native Image API；显式处理像素格式、stride、alpha、色彩和方向。
- 文件：`fileIo` from `@kit.CoreFileKit`。不要把抽象的“FileKit”直接写成未核实的 import。
- 轻量偏好/已有数据：`@kit.ArkData` 对应能力，保留现有存储结构并做必要的版本迁移。
- 日志：`@kit.PerformanceAnalysisKit` 的 hilog，Native 采用对应日志接口。

上列能力逐项实际编译。具体方法签名、权限和线程约束以本机 SDK 为准，不能用这里的架构描述替代编译验证。

## 3. 原生图形门槛：先做一个完整小探针

先定位现有 WebGL 提示的触发层：独立 canvas 上的上下文创建、着色器、资源、通信错误分别记录。不只删检测或升级 API。这个诊断不能延误原生小探针的实施。

在同一个目标 API 26 模拟器中验证：
1. XComponent 与原生 NativeWindow 生命周期。
2. EGL ES3 配置、context、window surface 与 makeCurrent。
3. 三角形、带 PNG 的网格。
4. RGBA8 离屏 FBO、像素读回、编码 PNG；方向/颜色/透明度正确。
5. 一个实际人脸 GLB 的网格和纹理显示、旋转。
6. ArkUI 浮层/键盘、触摸、前后台、surface 重建和销毁。

所有 EGL 属性数组以 EGL_NONE 结束；检查返回值、EGL 错误和 shader 编译链接日志。不要无条件依赖浮点渲染目标或未声明的 sRGB window 扩展。记录 GL_VENDOR、GL_RENDERER、GL_VERSION、GLSL 版本、必需能力及运行 ABI。

原生路径绕过 WebView 的限制，但仍依赖宿主/模拟器图形后端。探针失败时须区分配置、镜像、驱动与代码，不宣称“原生一定能跑”。可用隔离测试工程在另一个官方支持的镜像作对照，不改坏当前工程或清除数据，不以不同镜像成功冒充 API26 成功。

禁止擅自修改 BIOS、虚拟化、全局防火墙/驱动、终止无关进程。真实需要用户登录、安装镜像或提供密钥时只说明具体阻塞，继续完成不受影响的代码。

## 4. XComponent、生命周期和线程

采用当前官方指南推荐的声明式 XComponent + OH_ArkUI_SurfaceHolder 路线：
- ArkTS 创建 XComponent，并在合适生命周期取得 FrameNode。
- Native 用本机已核实的节点转换接口取得 ArkUI_NodeHandle。
- 建立 OH_ArkUI_SurfaceHolder、OH_ArkUI_SurfaceCallback，注册创建/变化/销毁事件。
- 回调中按正式接口取得 NativeWindow，交给原生渲染对象管理。
- 根据 SDK 核对自动初始化与挂树时序，避免绑定过晚遗漏已存在表面。

不要同时让 XComponentController、旧 OH_NativeXComponent 回调与 SurfaceHolder 三套机制各自初始化/销毁同一 EGL surface。现有渲染代码须通过一个适配点迁移到选定机制，不长期叠加。

EGLContext 由一个明确的渲染线程持有；所有 GL 调用在正确上下文所属线程执行。官方 NativeVSync 回调运行于其自身线程，不应假定就是 GL 线程；回调仅更新时间/唤醒队列，渲染线程实际绘制。

每个会话只有一个有效循环。静止按需重绘，交互/动画期间按 VSync 调度。后台停止调度。

区分借用和自有的 NativeWindow 引用，不释放不属于应用的借用资源。surface 销毁要先失效 generation、停止提交与旧回调，再让渲染线程在正确上下文清理。引用计数不等于 surface 永远有效。退出不得出现 UI 等渲染线程、渲染线程又等 UI 的循环等待。

在节点实际失效前移除并释放绑定该节点的 SurfaceHolder/回调；顺序参照 SDK 文档并用重复开关页面测试。不能删除节点后继续用其句柄。

Native 结果回 ArkTS 使用合法的线程投递机制；不能在渲染线程直接使用只属于 JS 线程的 napi_env/napi_value。N-API 入口中取得的 ArrayBuffer/对象需转成有明确所有权的数据，异步任务不能访问已经失效的 JS 临时内存。

CMake 依据实际 SDK 配置 EGL、GLESv3、ArkUI/Node-API、NativeVSync、日志和图像等链接项；从源码构建目标 ABI，不复制别人设备的 .so。支持的模拟器 ABI 与真机 ABI 分别构建测试。

## 5. 工程模块与状态所有权

保留现有目录，按以下职责组织，不要求为匹配名字整仓移动：
- ArkTS：MirrorPage / SessionStore / PolicyEngine / PlannerClient / AssetRepository / LocalStore / NativeRendererPort。
- Native：RendererSession / SurfaceLifecycle / FrameScheduler / GltfAssetLoader / TexturePipeline / RegionSelection / EditCompositor / ExportService。
- 后端：VisionPlanner / DeepSeekClient / ProductRepository / PlanValidator。
- 共享契约：版本化 JSON Schema、测试样例、产品与效果预设协议。

ArkTS 持有用户意图、授权、偏好和已提交操作历史，是客户端业务状态源；Native 持有实际网格、纹理、蒙版及可重建缓存。后端只能提出候选计划，不能更改手机上的当前作品。

拆分版本：
- assetVersion/textureVersion/regionVersion：实际编辑资源。
- sceneRevision：已提交编辑、保护/授权范围等业务变化。
- viewRevision：相机旋转/缩放与显示尺寸，不自动等于作品变化。
- surfaceGeneration：NativeWindow/context 生命周期。
- requestId/snapshotId：一次云请求和它实际看到的图像。

用户在等待 AI 时可以旋转面容。只发生 viewRevision 变化、已注册区域与业务状态不变时，不必丢掉一个仍有效的计划；编辑、蒙版、规则或面容改变时，旧 sceneRevision 的计划不自动执行。

## 6. 资产协议与 GLB 实现

运行资产采用自包含 glTF 2.0 GLB + manifest + 语义/保护区域记录。只有格式检查通过不够，必须检查 UV 与区域能力。

首版支持静态三角网格、POSITION/NORMAL/TEXCOORD_0、明确节点变换与 PNG/JPEG 纹理。cgltf 只用于解析，buffer/accessor 解读、图像解码、材质、纹理上传和 GL 绘制由本项目实现。

须处理 accessor 偏移/stride/component type/normalized、索引类型、节点层级变换、材质/primitive 对应。可选/未支持的 sparse accessor、skin、morph、压缩扩展、复杂动画等在导入前检测并说明，不忽略后称正确。首版资源制作时统一转换到支持子集。

UV 不得让左右脸镜像重叠；区域蒙版绑定 mesh/primitive、UV集合和版本。像素方向、照片EXIF、前置镜像统一处理一次。

manifest 至少有：assetId、version、source、license、尺度/朝向、textureVersion、baselineKind、区域及支持能力。

baselineKind 本版优先 BAKED_APPEARANCE（照片中已有光照的固定外观）：正确显示原有纹理，不重复打光、不额外全脸磨皮。它不是解耦光照的真实皮肤光学模型；不能在这种基底上开放任意光照下的真实护肤反射仿真。

示例资产标为示例。个人照片手动编辑可作为同一渲染器中的平面资产类型，但不是个人 3D 重建。个人完整网格从获准的外部建模流程导入，准确核对后使用。

不把 Remy/PLY/高斯资产改扩展名当 GLB。本版不新增高斯引擎。未来提取或绑定网格属于独立重建与验证流程，不宣称无损转换。

## 7. 选择区域的确切实现

圈选是关注，不自动成为编辑授权。默认拖动旋转；点“圈一下”后冻结该笔视角，圈画完成/取消再恢复。两指、取消事件和浮层抢占时正确结束手势。

所有坐标经显式转换：ArkUI布局单位 → 实际视口像素/标准化设备坐标 → 当前可见三角形 → UV。禁止混用vp、屏幕像素、渲染分辨率和蒙版像素。

闭合轮廓须得到内部填充。实现可采用冻结视角的CPU射线/可见性栅格化，或一次性的ID/UV离屏通道；选定并验证一个正式算法，不每帧全屏GPU读回。需处理遮挡、纹理接缝、鼻子两侧与多个三角面，不直接把UV边界点连成多边形。

输出稳定 regionId 和实际蒙版数据，并进入 Native 资产存储及 ArkTS 元信息登记。仅返回 maskId 且无法恢复实际蒙版不算完成。

照片里未定位嘴唇时允许人工精细确认；DeepSeek 的框选/自然语言位置不当作精密唇边蒙版。自动检测或分割仅作为用户可修正的候选。

## 8. DeepSeek 接入必须真实完成

模型配置在后端：
- DEEPSEEK_BASE_URL 默认 `https://api.deepseek.com`。
- DEEPSEEK_MODEL 默认本次官方公布的 `deepseek-flash`。
- DEEPSEEK_API_KEY 只放环境变量，不写进HAP/Native库/日志/产品文件。

本次官方表里 deepseek-flash 对应 DeepSeek-V4.1-Flash，支持图像理解；deepseek-v4-pro 不支持图像理解。旧 alias 不作为首选。上线前重新核对，记录请求/返回的模型标识和可用的版本指纹；模型别名不等于永远冻结的权重版本。

先用无个人隐私的自制测试图片验证：
1. 实际图像输入可以正确识别明显不同的测试内容。
2. 同一个模型请求同时接受图片与 tools，能返回所定义的候选计划工具调用。
3. 后端校验拒绝无效/越权参数。
仅 GET models 成功不能证明视觉能力；HTTP200和能聊天也不能证明看到了图片。

真实密钥未提供时，可完成接入代码与模拟响应单元测试，但必须标记“真实DeepSeek调用未验证”。离线模板用于基本可用性/测试，不能冒称已接入大模型，也不能替代本版模型验收。

正式架构是“DeepSeek看图并选择有限编辑操作”，不是DeepSeek输出改好的GLB/精确蒙版/皮肤材质。图像理解、工具调用、图像生成不是同一能力。当前查到的接口没有为本项目提供直接生成编辑图片的保证，不臆造 `/images/edits` 之类端点。

## 9. 给模型发送什么

只在用户提出一次新编辑/解释请求时发送，不逐帧上传摄像头。

一次快照固定对应 assetVersion + sceneRevision + regionVersion + snapshotId，并包含冻结视角/裁剪/镜像变换记录。准备：
- 一张无UI、未叠加圈线的干净当前视图；必要时补充清楚标为原始基准的参考。
- 一张同快照的区域标注图，或一个有编号的局部裁剪；文字说明标线是选择提示，不是皮肤特征。
- 用户原话、已确认区域编号及可读说明、用户目标。
- 本次可用的少量效果预设、产品证据和已生效保护范围摘要。

精确UV蒙版和原始资产留在客户端；模型只引用已存在的regionId。用户要新区域时先由程序产生/确认该区域，不信任模型临时编出的坐标。

不默认发送整个GLB、全相册、全目录或完整对话历史。可从长边768—1024像素、1—2张图起步，这是项目预算不是DeepSeek平台上限；小特征需要原始局部裁剪并验证识别质量，不为了省数据把关键细节缩没。

客户端到自有后端可使用受支持的multipart二进制与JSON元信息。后端按DeepSeek官方格式构造 `image_url` 内容块，支持data URL；不要把二进制GLB当图片，不把Base64字符串放进普通text块假装图像输入。不要让模型URL访问应用私有路径。

云端图片处理需要用户明确知道并授权；拒绝时保留本地编辑。自己的后端默认不持久保存图片、不记录请求body。第三方处理与留存以其实际条款为准，不能声称所有第三方均零留存或撤回就能删除已发出的每个副本。

## 10. 唯一模型调用协议

首版使用普通 Chat Completions + 一个 function tool `propose_edit_plan`。使用稳定端点，普通工具参数仍执行严格的应用侧校验；不依赖未经组合测试的Beta strict模式，不误用json_schema响应格式。

请求原则（字段依据本次官方文档，实施时重新核对）：
```json
{
  "model": "deepseek-flash",
  "thinking": { "type": "disabled" },
  "stream": false,
  "max_tokens": 1536,
  "messages": [
    { "role": "system", "content": "只根据已提供区域与能力提出候选方案；不得授权、诊断或发明产品效果。" },
    { "role": "user", "content": [
      { "type": "text", "text": "用户目标、快照编号、区域及允许预设由程序在这里提供。" },
      { "type": "image_url", "image_url": { "url": "data:image/jpeg;base64,<由后端编码的真实图片>" } }
    ] }
  ],
  "tools": [
    { "type": "function", "function": {
      "name": "propose_edit_plan",
      "description": "返回候选计划，不执行修改，不代表用户授权。",
      "parameters": {
        "type": "object",
        "properties": {
          "decision": { "type": "string", "enum": ["edit", "explain", "clarify", "support"] },
          "shortMessage": { "type": "string" },
          "operations": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "operation": { "type": "string", "enum": ["set_digital_tint", "set_effect_level", "remove_effect"] },
                "regionId": { "type": "string" },
                "presetId": { "type": "string" },
                "intensityLevel": { "type": "string", "enum": ["none", "light", "medium", "strong"] },
                "layerId": { "type": "string" },
                "productProfileId": { "type": "string" }
              },
              "required": ["operation", "regionId", "presetId", "intensityLevel"],
              "additionalProperties": false
            }
          },
          "explanationRefs": { "type": "array", "items": { "type": "string" } },
          "question": { "type": "string" }
        },
        "required": ["decision", "shortMessage", "operations", "explanationRefs", "question"],
        "additionalProperties": false
      }
    } }
  ],
  "tool_choice": { "type": "function", "function": { "name": "propose_edit_plan" } }
}
```

上面给出首版可用的完整工具参数结构；图像data URL等运行值由真实请求填入。schema必须跟实际实现的操作注册表同步；没有实现的操作从enum删除，不能只改文档。应用侧补足条件校验：调整/移除操作必须指向当前有效layerId；删除时presetId须与该层一致且intensityLevel为none；新建数字表达不得附带真实产品模拟声明。未涉及的question为空字符串。关键语义如下：
- decision：edit / explain / clarify / support。
- shortMessage：简短、不评判外貌、不能声称尚未执行成功。
- operations：有限数组，每项仅含operation、regionId、presetId、受限intensityLevel，涉及真实产品时引用已存在productProfileId。
- explanationRefs：仅能引用检索到的证据编号。
- question：只有确有歧义时的一次简短澄清。
- explain/clarify/support原则上没有执行操作；不得夹带产品推销或隐式改图。

允许操作按实际能力登记，例如局部数字唇色、局部数字颜色表达、调整已有层；不返回任意代码、文件路径、授权字段或疗效数值。强度只映射到项目明确定义的数字效果范围或产品已标定预设，不解释成真实剂量百分比。

DeepSeek官方文档限制：强制指定tool/required与思考模式存在不兼容；本版显式关闭thinking，不同时传相矛盾的reasoning配置。不要把模型默认开启思考的行为留给猜测。

收到完整工具参数后检查finish_reason、JSON、类型、枚举、有限数值、ID存在性、产品能力及当前状态。拒绝额外字段、截断、空内容、多个互相冲突的工具调用。至多一次受控修正请求，仍失败就保持原结果，不无限修复循环。

工具调用的含义是“提交候选计划”，不是后台执行图形操作。没有必要为了凑agent回合再向模型谎报渲染成功。

## 11. 后端与模型上下文

自有后端的 `/v1/edit-plans` 等路径是本项目接口，不是Huawei或DeepSeek官方接口，文档中明确标注。

后端使用异步HTTP客户端，设置连接/总请求超时和取消处理；日志仅存错误类别、耗时、模型标识与脱敏请求编号。不把文件路径、照片字节、密钥和外貌困扰全文写入日志。

产品检索先按区域、需求、能力和用户偏好筛选少量条目，不把全商品库塞进每次prompt；资料内容当数据，不允许其中的文字覆盖系统限制。

图像嵌在一次有目的的请求中；缩减多轮上下文时保留已确认的操作摘要和指代对象。不能因省略先前上下文，把“再淡一点”错误作用到另一个区域。

手机使用NetworkKit访问自己的后端，不将Node/npm的模型SDK导入ArkTS。网络权限、URI、TLS和证书按实际SDK处理；不通过禁用TLS校验解决连通问题。不默认模拟器localhost等于电脑，不照搬Android固定宿主地址。

开发只开放所需端口；对公网部署的付费模型代理提供与保护接口相关的最小鉴权/限流，不能裸露模型密钥代理。不要为首版添加账户、支付、营销或多智能体平台。

## 12. 授权与提交状态机

状态顺序：理解/候选 → 校验 → 必要确认 → 已授权待执行 → Native准备/检查 → 提交有效结果 → 账单。

模型输出、用户授权、Native执行成功三者不可合并。检查失败不进入有效作品；不要先显示越界结果再“回退”。候选渲染与检查在后台准备，合格后原子切换到当前有效结果。

模糊请求如“自然一点”先显示一句范围说明，点“试一下”；明确且在已有范围内的“唇色淡一点”直接调整。仅在新区域、不同操作或保护冲突时轻量确认，不重复让用户填写脸型/肤色/雀斑清单。

保存长期偏好仅在明确要求“以后都这样”时执行。已有保护与当前要求冲突时说明本次例外，不把普通聊天当成永久解锁。

若等待AI时用户改变了编辑、区域或规则，原请求过期；网络恢复不执行旧计划。旋转/缩放自身不等同于业务修改，见版本拆分。

区分冻结原始外观和冻结当前有效外观；前者引用基准，后者引用明确的已提交版本。不能冻结一个尚未成功渲染的结果，不能构造循环引用。

## 13. 皮肤编辑与保护算法

设C为授权目标、T为授权过渡、S为操作适用区、P为仍严格保护的区域：
A = ((C ∪ T) ∩ S) \ P。

实际效果蒙版在A内，在边缘内部平滑趋零。抗锯齿、mipmap、重采样同样不能绕过保护。纯数字表达可使用受限融合，真实产品必须服从实际标定的联动参数，不能随意拆掉不想要的效果。

固定原始几何与基底纹理；编辑保存为操作及绝对参数，从对应基底重算，不把每次结果再当新原图，避免多次“轻度”累加失控。

局部唇色：已确认嘴唇蒙版，排除口腔/牙齿/皮肤；在正确颜色空间中使用有界颜色与覆盖计算，保留必要纹理细节。不用纯平面色块盖掉全部唇纹，不把示意称为完整物理仿真。

固定对比时的相机、光照、曝光与输出转换。非授权/严格保护区使用同条件参考结果；“不做数字美白”不等于禁止产品真实反光，但真实产品可见变化必须先说明并获准。

不用全脸平均色差证明局部没改。对局部保护区和非授权区分别测试，误差阈值要与渲染/采样条件对应，不能为了通过调高阈值。

保护、自然融合和真实产品作用无法同时满足时，不伪造兼容结果：降低到已验证条件、重获范围授权、换兼容方案或停止该模拟。

## 14. 性能与“AI等待不拖垮本地交互”

以下是初始预算，不是实测承诺：一个2万—5万三角面的人脸，1K—2K主纹理，少量活跃编辑层，720p级内部渲染起步；约30fps连续交互目标，帧时间分布/长帧另测。

- 旋转、缩放、滑块、对比和回放全部本地执行。
- 每次语义目标变化才申请AI；模型延迟单独统计，不能混入帧率。
- 不在UI线程解析大GLB、编码图像或等待网络；图像解码/编码独立工作任务，GL仍在专属渲染线程。
- GPU缓冲/纹理重复利用；区域修改更新脏区/参数，不每帧上传全模型和全蒙版。
- 提交检查/圈选结束/导出才做必要读回，不每帧全图glReadPixels。
- 请求合并但不能漏掉明确的撤销/取消；返回结果必须带请求及版本。
- 不用高分辨率截图、实时相机、点云重建、长推理同时争抢首版资源。

在真实目标环境运行至少10分钟连续旋转/编辑/比较/详情切换，记录帧时间p50/p95、长帧、峰值内存、前后台恢复和AI请求耗时。目标值与实测值分别列出；CPU提交时间不是GPU完成时间。

## 15. 预览、导出和已有数据迁移

预览、原始对照、回放、保存使用同一操作模型和渲染函数。分屏对照需要恢复GL viewport/scissor/FBO等状态；导出关闭交互蒙版线，不另调用高清美化模型。

导出Native离屏结果，经官方图片编码路径生成真实PNG字节，正确处理行跨度、Y方向和alpha；临时路径或网页blob不是已保存作品。

读取旧工程资产、历史与偏好的真实结构；以明确映射迁移坐标、UV、版本和操作。旧作品无法准确重算时保留原文件并说明能力，不覆盖为错误的新结果。

保留包名、签名及用户数据，迁移失败不清库。卸载、Wipe User Data、清缓存不是默认排错步骤。

## 16. 沉浸风格与宗旨

界面是“面容主体 + 底部一句话输入 + 少量操作 + 单层详情”。不是聊天网页壳，不是卡片仪表盘。保持原有效视觉设计，不因原生迁移变成工程控制台。

首次使用不强制账号、完整3D扫描或面容宪章表单。示例与个人资产明确标识；个人3D未建立时不伪造扫描进度。

默认不增加未经请求的美白、磨皮、瘦脸、特征消除。保留和改变平等，不因为用户想遮盖就说教。只在出现真实困扰表达且愿意时自然支持，普通试色可以直接结束。

“我的发现”是用户主动留下的一句话，不自动替用户编优点，不强制打卡。不从人脸、点击次数或修改频率诊断自卑或心理疾病。不提供颜值分数、标准脸差距、凭脸判断能力/可信度。疤痕、白斑、胎记、皱纹不默认被列为缺陷；青少年相关体验需单独审阅，不自动推结构重塑。

用户说“我不喜欢这里”不立即推OLAY或任何产品。具体SKU只有经过核实的资料和标定才开放相应展示；没有标定只开放资料/真实素材/清楚标识的示意。通用妆效不贴品牌名冒充实测。保留OLAY与其他品牌关系的准确边界，赛事范围以实际题目为准，不宣称官方合作。

原理动画采用原生时间轴/简单程序化示意/已许可视频；不继续依赖Three.js AnimationMixer，不伪造皮下扫描、含水量或未来功效。详情关闭后回到原视角与有效作品。

所有偏好、账单和发现默认私密，可删除。授权记录不是全网防编辑锁，也不是现实肖像身份认证。实际公开分享需要独立动作。严重困扰的回应采用经过专业审阅的支持指引，不把编辑器包装成治疗。

## 17. 首版必须闭环的实际场景

场景A：示例3D面容可旋转 → 手工圈出区域 → 请求DeepSeek理解 → 提出已登记的局部数字表达 → 确认 → 原生执行 → 比较/撤销/保存。

场景B：用户导入照片 → 正确处理方向 → 标记嘴唇和保护区 → 同一模型链提出局部计划 → 程序受限编辑。照片不冒称完整个人3D。

场景C：明确“这里保留” → 后续模型提出冲突计划 → 规则阻止静默覆盖，只作一次必要确认 → 本次例外不改变长期偏好。

场景D：断网或模型失败 → 原生旋转/滑块/撤销仍正常，当前作品不变；显示可理解状态，不拿离线回复冒充云调用。

场景E：用户对自己困扰 → 支持性交流可跳过 → 不自动推商品，保留/修改同等可用；普通试色无强制自我发现。

## 18. 必须实际执行的测试

1. 本机SDK/ABI/工具链记录与原生探针完整通过；明确API26结果，不由API20/22参考替代。
2. 离线冷启动，真实人脸GLB和纹理显示，非球体占位。
3. NativeWindow创建/改变/销毁、前后台和上下文重建。
4. VSync回调线程与GL线程正确，关闭后无重复循环/悬空回调。
5. 多次进入退出无持续资源增长，UI浮层/键盘/字体和不同窗口尺寸可用。
6. 2D/3D圈选内部填充、遮挡、镜像、UV接缝及部位分割正确。
7. 唇色不染牙齿和皮肤，保护蒙版含边界不泄漏。
8. 重复调节从基底计算，不累积绕限，非授权区域同条件不变。
9. DeepSeek真实视觉测试，至少两张内容明显不同的无隐私图片。
10. 同一请求的Vision + 指定tool组合真实可用，非只聊天/只HTTP200。
11. 模型输出引用不存在region/preset/product、越范围强度、未知操作、额外字段被拒绝。
12. 模型意图正确但精确位置不可确定时，不擅自生成蒙版。
13. 只有完整且校验合格的候选计划能进入授权；授权不等于渲染提交。
14. 等待AI时旋转不冻结画面；编辑/规则改变后旧计划不能覆盖新状态。
15. 超时、取消、重复响应、截断、空工具输出、服务错误不污染作品。
16. 用户拒绝图片上传不会后台外发，后端日志不包含照片或密钥。
17. 普通试色不强制发现优点，困扰场景不立即推商品，改变不受道德劝阻。
18. 未标定SKU无法打开真实功效模拟；数字表达的来源标识保留。
19. 对照/回放/导出同一有效版本，PNG像素方向和颜色正确。
20. 旧作品和偏好保留，重新打开/删除有效；换面容旧蒙版不盲目沿用。
21. 真实模型不可用和模拟器图形不可用分别报告，不靠截图或二维回退伪装完成。
22. 性能预算、帧时间、持续操作、真机与模拟器分别记录。

仅实际运行过的测试标“通过”。没有密钥/真机/SDK等时交付能完成的代码与失败记录，明确未验证层级，禁止声称保证所有鸿蒙设备都流畅。

## 19. 执行顺序与交付

顺序：现有工程核对 → 原生探针 → 单面容GLB/蒙版编辑 → DeepSeek真实图片+tool能力测试（可与资产工作并行）→ 完整编辑事务 → 简约界面和产品观察 → 迁移/性能/回归。

每阶段落实实际代码，报告短小真实结果后继续，不把任务变成重复方案讨论。探针失败先定位，不堆砌新引擎；模型能力测试失败先核对实际模型/端点，不虚构多模态支持。

交付：
- DevEco可打开的完整工程、原生源码、后端源码与固定依赖。
- 模型/纹理/蒙版/许可/manifest，资产预处理与校验脚本。
- `.env.example`无密钥，模型能力测试与后端运行脚本。
- HAP（有实际构建/签名条件时），ABI与签名说明。
- docs/environment.md、api-compatibility.md、asset-contract.md、model-contract.md、validation.md。
- 真实模拟器日志、截图、模型测试结果摘要，不泄露私密数据。
- 实现/示意/未接入能力清单，以及旧数据迁移说明。

## 20. 官方资料与使用边界

以下为本次核对入口。Huawei动态文档部分正文未被网页工具完整提取；OpenHarmony源文档用于核对公开契约，不替代实际商业SDK。第三方样例和竞赛基线只提供结构参考，不当成最新平台接口标准或完成的美妆系统。

### 华为 / HarmonyOS 官方入口
- https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/napi-xcomponent-guidelines
- https://developer.huawei.com/consumer/cn/doc/harmonyos-references/capi-native-interface-xcomponent-h
- https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/native-vsync-guidelines
- https://developer.huawei.com/consumer/cn/doc/harmonyos-references/opengles
- https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/abilitykit-overview
- https://developer.huawei.com/consumer/cn/doc/harmonyos-references/js-apis-http
- https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/image-source-c

### 已读取的官方开源资料（固定实际使用提交，不盲追master）
- https://github.com/openharmony/docs/blob/master/zh-cn/application-dev/ui/napi-xcomponent-guidelines.md
  采用声明式XComponent + SurfaceHolder结构；不要混用五种开发范式。
- https://github.com/openharmony/docs/blob/master/zh-cn/application-dev/graphics/native-vsync-guidelines.md
  核对回调线程、唤醒渲染线程、创建与销毁。
- https://github.com/openharmony/docs/blob/master/en/application-dev/ui/state-management/arkts-new-componentV2.md
  核对V2范围与V1混用限制，不改写成React式组件。
- https://github.com/openharmony/docs/blob/master/en/application-dev/media/medialibrary/photoAccessHelper-photoviewpicker.md
  核对MediaLibraryKit与CoreFileKit，URI不当普通磁盘路径。
- https://github.com/openharmony/docs/blob/master/zh-cn/application-dev/ui/arkts-arkui-frameNode-faq.md
  核对节点/SurfaceHolder释放顺序风险。
- https://github.com/jkuhlmann/cgltf
  只复用glTF解析，另行实现实际渲染；记录版本与许可证。
- https://cadcg2026.nju.edu.cn/?pages_20/=
  华为组织赛事列出原生ES3与部分模拟器环境，仅作技术参考，不证明本机API26已运行。

### DeepSeek 官方接口
- https://api-docs.deepseek.com/
- https://api-docs.deepseek.com/quick_start/pricing/
- https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/
- https://api-docs.deepseek.com/guides/tool_calls/
- https://api-docs.deepseek.com/guides/json_mode/

特别注意：Vision模型选择、image_url输入、thinking默认值、强制tool限制、工具参数校验、Beta strict条件均以真实接口为准。只读到文档不是完成模型联调。
