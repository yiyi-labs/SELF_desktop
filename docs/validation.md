当前生效说明：[原生运行入口](../README-native.md)、[当前验收](validation-native.md)、[接口核对](api-compatibility.md)。以下为旧 Web/Component3D 路线历史记录；不作为当前实现或验收结论。

---

# 真实验收结果

日期 2026-09-21 至 2026-09-22。本文件区分“已实现”“定向测试通过”和“整个条目全部验收”。当前为有真实产物的核心原型，**仍有未完成范围，不宣称 FINAL 文档全量完成或发布就绪**。

## 证据汇总

**2026-09-22 更新：** 下表原有完整/沉浸模拟器结果均来自历史 API 19。当前 API 26 手机镜像已安装并启动主包，但 ArkWeb WebGL 被禁用，不能标记 3D 通过。原生迁移门槛也尚未通过，见新增记录。

| 本次新增检查 | 结果 | 证据 |
|---|---|---|
| API 26 构建、安装、主界面 | 通过；仍有 SDK 警告，unsigned debug | hap-build.log、hap-install.log |
| API 26 ArkWeb WebGL1/2 | **失败**：disable-3d-apis；应用级参数试验无效 | api26/webgl-probe.json、webgl-probe-app-setting.json、webgl-probe-final.json |
| 图形失败明确提示 | 实际模拟器显示原因、镜面不可用；不发送 INIT/模型 | api26/unavailable-ui.png、unavailable-ui.json |
| 桌面失败路径回归 | 通过：生产 bundle 无未捕获错误，READY=false，拒绝 INIT | browser/startup-results.json（不是鸿蒙测试） |
| 桌面正常路径回归 | 9/9 | browser/results.json |
| GLB 结构门槛 | 示例通过；7/7 接受/拒绝格式检查通过，不等于原生效果验证 | model-compatibility.json、model-inspection-tests.json |
| 原生 Component3D | 可构建、安装；曾显示纹理 GLB；**外观失败**，再次启动也出现 scene manager 创建失败 | native3d/initial.png、explicit-unlit.png、no-fringe.png、hilog.txt |
| 原生旋转、圈选、编辑、PNG | 旋转手势代码可编译但尚未完成实测；圈选/编辑/作品导出尚未迁移 | 不得复用 Web 通过记录 |
| 个人拍摄→重建、Remy 文件互通、鸿蒙真机 | **未实现/未验证** | 无实际用户拍摄数据或真机证据 |

| 环境 | 执行与结果 | 证据 |
|---|---|---|
| HarmonyOS 构建 | DevEco 26.0.0.821 / SDK API 26，debug unsigned HAP 编译成功；API 19 真模拟器安装成功 | hap-build.log、hap-install.log |
| 初始模拟器纵向门槛 | 6/6：实际 ArkWeb、GLB/WebGL2、原生往返、编辑、圈选、导出、后台恢复组合检查 | emulator/vertical-results.json、PNG、旧失败截图 |
| 当前完整模拟器 | 9/9：分块往返、原样导出、授权/undo/redo、对照导出、圈选、保护当前效果、保存/重开/删除、取消选图、前后台恢复 | emulator-full/results.json、hilog.txt、saved-workspace.json、截图与 PNG |
| HarmonyOS 原生 Hypium | **7/7，Failure 0，Error 0**；生产 ArkTS 状态/策略/Planner、主动文本氛围、观察角度和作品文件生命周期被实际执行 | native-tests.log、native-test-build.log |
| Node | 24/24；生产 ArkTS 领域类经编译导入，Web 多边形/羽化/传输/颜色函数直接测试 | unit-tests.log |
| 桌面 Chrome | 9/9 基础图形；7/7 保护/操作顺序/上下文/PHOTO/资源复用；3/3 动效与减少运动 | browser/results.json、advanced-results.json、design-results.json |
| 当前沉浸模拟器 | 6 项通过，1 项键盘闭环未验证：真实原生音频、切换、生命周期、动效开关、轻转冻结、旋转视角保存重开 | immersive/results.json、hilog.txt、截图与 PNG |
| 资产工具 | Khronos Validator 0 errors；单 GLB 内嵌纹理、无外部资源 | gltf-validator.json、asset-audit.json |
| 真机 / 发布 | **未验证、未签名发布** | 无真机证据 |

以上数字不能相加后当作 28 条全部通过。历史与最终主包分别保存，Hypium 测试包和产品 HAP 也不同。

## 28 项逐条对应

| # | 结果 | 证据与未覆盖范围 |
|---|---|---|
| 1 | 部分 | HAP 使用本地 rawfile、无 INTERNET 权限，实际首次运行加载成功；桌面已加载后 offline 仍可工作。**未做模拟器整机断网冷启动** |
| 2 | 通过限定范围 | SDK、Hvigor、unsigned HAP、hdc 安装及实际 UI/ArkWeb 均真实；发布签名、真机未验证 |
| 3 | 部分 | 实际两块 65,539 字节全值域/中文/引号/NUL，GLB、1 MiB mask、PNG 完整往返。Node 验证取消/缺块/越界；模拟器取消与 32 MiB 极限未测 |
| 4 | 部分 | GLB Validator 0 errors，真实资产/许可/sha/嵌入图齐全。全 UV 存在 216 重叠采样与 11 退化三角形；editable/lip 区重叠 0，禁全表面编辑。解析接缝证明未完成 |
| 5 | 通过 | 初始模拟器截图：SELF、示例面容，直接镜面，没有登录/扫描/问卷 |
| 6 | 部分 | 圈选、对照、详情互斥与详情覆盖实际使用；照片系统返回取消已通过。复杂多指/系统返回所有分支未遍历 |
| 7 | 部分 | 新版 UI 下真实 MESH 闭合区域回传 4,722 texel（旧布局 4,030）；代码逐最近交点排遮挡。背面、鼻后、嘴内、接缝压力样本缺少完整自动验证 |
| 8 | 部分 | PHOTO 平面代码含 EXIF from-image、局部坐标/平移/缩放/边界裁切；桌面非对称彩块确认不镜像。真实 EXIF JPEG、键盘导致尺寸变更、原生成功选图未测 |
| 9 | 部分 | 桌面 390×720 与 430×932，DPR 2；模拟器 1260×2720，空图库取消及应用内运动开关通过。桌面 prefers-reduced-motion 通过。第二种原生窗口、大字体、系统减少动画、真实键盘仍未验收 |
| 10 | 通过限定范围 | 模拟器确认前无 RENDER_SUCCEEDED，确认后改变；Node/Hypium 旧候选拒绝，直接调节不再问授权 |
| 11 | 部分 | 唇 mask 手绘排除中缝，闭嘴样本只发生局部像素变化。未证明所有周围皮肤边界，露齿/张嘴**未验证** |
| 12 | 部分 | 两视角保护抽样像素逐通道容差 0，内向羽化。**专项一次例外未实现**，不提供绕过保护开关 |
| 13 | 部分 | 会话/资产/版本/revision 约束、串行接收、重新 INIT 清传输、过时 ack 的 Node/Hypium 测试通过。所有页面重建/高频滑动竞态未穷举 |
| 14 | 通过限定范围 | 渲染失败不入账由 Node/Hypium 通过；实际保存/重开/undo/redo PNG 一致，私有目录实际删除。新增原生文件测试验证删除保存记录后当前临时资产仍可再次保存。磁盘满/中途断电故障注入未测 |
| 15 | 部分 | 当前锚点与原始锚点不同；两个视角桌面像素、实际模拟器调节保护/保存重开导出一致。加载当前长期规则；冲突时明确拒绝合并。多处保护/专项例外未实现 |
| 16 | 通过限定范围 | 桌面同条件零操作逐字节 PNG 相同；模拟器 undo 恢复与基准 PNG 相同；同相机材质管线，无对照增光 |
| 17 | 通过限定范围 | 重复绝对强度 PNG 不变，反转两个重叠操作顺序产生差异；原生调节替换末项 |
| 18 | 部分 | 两视角保护区域可观察像素 320 / 397，逐通道容差 **0**；授权外全覆盖验证仍不足，不能以全脸平均误差替代 |
| 19 | 通过限定范围 | yaw 0 / camera z16；yaw .38 / z18，原貌与当前锚点均检查。属于桌面图形测试；模拟器仅正面保护流程 |
| 20 | 通过 | 实际对照后 PNG 与当前完整 PNG 相同，768×1024，非 UI 截图，行翻转/alpha 已检；导出保留数字示意标注 |
| 21 | 部分 | 原生完整接收后 atomic 写入、明确私有目录；**未做大数据导出中断/取消/磁盘满**。未实现相册导出 |
| 22 | 部分 | 实际前后台导出相同；桌面 context loss/restore 全像素相同，8 次替换为 1 geometry / 6 textures，无增长。真实模拟器 context loss/长时内存压力未测 |
| 23 | 通过限定范围 | PolicyEngine 拒绝 productSimulation、空标定拒绝；通用颜色无 SKU 绑定，Hypium 实测 |
| 24 | 部分 | 品牌文本、自有参数动画、非实测标签清晰；原生色块真实播放。动画关闭不改变状态由隔离代码保证，尚无独立模拟器动画前后像素自动检查 |
| 25 | 部分 | 正常试色没有问卷，困扰文本只提出可选支持；可选择保留或继续试色。Planner 实际 Hypium 通过；完整支持 UI 未自动遍历 |
| 26 | 部分 | 无行为推断、评分/诊断；文字主动写入可改删。私密文字保存/删除代码已编译，尚无独立文件生命周期实测 |
| 27 | 部分 | 无上传路径/网络权限；选图为系统单选、私有 cache，删除范围明确。完整个人资产成功导入/关联删除尚未模拟器验证 |
| 28 | 未验证 | 仅一个公共闭嘴男性扫描及自制四色 PHOTO 夹具。没有多肤色/年龄/性别/斑痕/白斑/胎记/青少年公平证据，不能据此泛化 |

## 发现过的失败及处置

1. 初次误设编译 SDK 字符串与 ArkTS 不支持的语法导致构建失败：按本机模板/类型修正；后续主包和 Hypium 编译成功。
2. 默认 CSP 阻止 GLB 嵌入纹理的 blob fetch：只开放 blob；没有开放外网。
3. 外部 JPG 与内嵌 glTF 纹理的 V 约定不同：曾出现倒置脸；资产制作阶段固定转换并升级资产版本。
4. 重复 pointerup 终点导致合法闭合圈选被误判自交：规范化重复点并加入回归测试。
5. 模拟器 DPR 2 下离屏 setViewport 发生重复缩放，PNG 裁切：修复为 RenderTarget 物理 viewport；旧图保存在 emulator/failed-dpr-export.png，新图及对照一致性已过。
6. 桌面 context restore 重置清屏颜色，153,112 像素不同：恢复时重设背景；最新全像素检查 0 差异。最初资源计数检查过早也失败，等待真实恢复与渲染帧后 8 次替换稳定。
7. 首轮完整 UI 测试在系统选图浮层还未关闭时点击后方控件，后续导出超时：保留 emulator-full/first-run-results.json；等待浮层消失，最新 9/9 通过。
8. Hypium 实际 6/6 通过，但脚本最初只识别另一种报告格式而返回错误：按当前实际 OHOS_REPORT_RESULT 与 TestFinished-ResultCode 校验修正。
9. 新版调试测试曾在 ArkWeb 调试 socket 就绪前创建转发，出现 ECONNRESET：先等待本次原生渲染完成，再建立本项目映射；连接失败也清理转发。
10. 真实输入触发小艺输入法首次用户协议，测试无法继续。保留 immersive/first-run-results.json 与 design-debug.png；没有自动点同意，相关项单独记为未验证，其余测试继续。
11. 新布局的“关闭”按钮已在屏幕可见范围，但旧测试用按钮底边 <2500 的条件误判不可用。依据真实布局改为点击中心的安全范围，重新通过 9/9；失败记录 design-run-before-hitbox-fix.json 保留。
12. 全局审查发现删除已重开的作品会让当前资产登记指向已删文件。改为先复制为临时工作资产，再管理保存记录；新的 Hypium 文件生命周期实测通过。
13. 移除了画布底部淡出，防止缩放/小窗口时影响面容。氛围在面容后方，模拟器前后 PNG 严格相同；减少运动运行中切换会冻结自动轻转，桌面已验证。

仍存在的质量限制：SDK 异常处理静态警告未全部消除；Hypium 自动生成资源存在 start_window_background 重复警告；未配置签名；工具链初装报告的 pnpm high 漏洞未独立审计。不存在“零错误全面保证”的结论。

## 未完成或需要外部条件的范围

自动定位/MediaPipe（模型许可与实际 ArkWeb WASM/Worker 适配尚未做）、真实个人照片成功选入全闭环、多处保护和一次专项例外、作品预览缩略图、逐项临时视觉回放、独立相册导出/分享、大图失败取消、真实产品效果标定、云模型、发布签名、真机、多样人群测试尚未完成。

严重困扰输入有基于 WHO 公开建议的短求助分流，不自动推送商品/修改；中文交互未获独立专业审阅，不能称“心理支持能力已验收”或青少年效果验证。

示例资产与自有数字效果已明确标注；它们不替代用户面容、真实功效或真实公平数据。后续工作应从本清单缺口继续，不重写已通过的核心。

