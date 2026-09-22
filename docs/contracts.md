# SELF 数据与执行约定

## 唯一状态与提交

ArkTS `SessionStore` 管理资产、区域、候选、授权、成功快照、历史游标和保护规则。`PlannerService` 是有限的本地文本模板，仅产出意图。Web 不写作品元数据、不审批计划、不创建长期偏好。

候选绑定 assetId、assetVersion、baseRevision、planId。原生点击“试一下”生成授权操作；已有操作的“淡一点/换一种颜色”为明确调节授权。支持 localTint / lipTint、两个自有颜色、绝对强度 0..0.65、每份作品最多八项。未知操作、区域、预设、非有限强度、旧版本和 PHOTO 未确认唇区都拒绝。

授权后产生 pending revision 与 requestId，当前成功账单不变；只有匹配的 RENDER_SUCCEEDED 才推进账单/历史。失败清 pending，并向原生请求重放最后成功快照。undo/redo 同样经过渲染确认。保存拒绝 pending 状态。授权 ID 是本地工作流记录，不是肖像核验、密码学签名或法律凭证。

## 资产与区域

`assets/manifest.json` 指定真实 SHA-256、方向、mesh/primitive/UV0、UV/贴图/管线版本、bakedAppearance、1024² 蒙版和允许操作。示例版本 lee-r186-self2；区域名不是自动识别结果。公共模型闭嘴，未包含已验收的露齿场景。

mask 是 width×height 的逐像素 Uint8 数据，0 外部、255 内部，纹理空间原点与打包后的 glTF UV 一致；GPU NearestFilter、不生成 mipmap。文件名由原生生成，Web 不可给任意系统路径。MESH 新圈选必须落在登记 editable mask 内。原扫描 UV 有重叠，整体不能编辑；允许区域的 1024 像素中心审计为零重叠，这不是解析几何证明。

MESH 在冻结手势状态下逐 UV 三角形采样，投影到画布局部闭合多边形，再以最近光线交点的 triangle index 与距离确认可见性。PHOTO 以已做 EXIF 解码的平面，屏幕光线求照片平面交点再映射图像坐标，超出图像部分由栅格裁切。无自动面部定位、无个人 3D 重建。

## 桥与边界

JSON 信封：schemaVersion=1、sessionId、assetId、assetVersion、requestId、revision、type、payload。原生接收需会话/资产/版本/当前 revision 全部匹配。原生 INIT 切资产并清理未完成接收。Web 逐消息串行执行，避免 GLB 异步加载与 mask 注册竞争。

TRANSFER_BEGIN 包含 transferId、kind、length 及重复的会话/资产/版本/revision；接着是有序 ArrayBuffer 分块，最后 TRANSFER_END。拒绝空、超限、越界、长度不完整、重复开始或未知 ID；TRANSFER_CANCEL 丢弃接收缓冲。仅结束帧通过后交给资产或保存逻辑。未接入超时自动取消 UI；32 MiB 接收上限不等于已测能力。

控制类型：INIT、ECHO（Debug 探针）、SET_TOOL、SET_ATMOSPHERE、VIEW_SET、VIEW_ORBIT、VIEW_FREEZE、RENDER_AUTHORIZED_PLAN、EXPORT_REQUEST、DISPOSE。回执还包括 VIEW_CHANGED；原有 READY、INITIALIZED、ASSET_REGISTERED、TRANSFER_ACCEPTED、RENDER_SUCCEEDED、RENDER_FAILED、RESTORE_REQUEST 保持不变。Web 页面仅接受固定本地 bootstrap MessagePort；CSP 和导航拦截阻止任意远程页面加载。渲染端只解释登记操作，不执行计划携带的代码。

SceneView 为 yaw/pitch/distance/panX/panY，有限值与边界由 renderer 核对。实际视角通过 VIEW_CHANGED 回传原生，保存到作品可选 view 字段，旧作品缺字段默认正面。MESH 不平移，PHOTO 不旋转；圈选/详情/对照/导出冻结自动轻转。氛围与音乐不属于面容编辑操作，不进入成功账单。

## 合成与保护

原始 sRGB 纹理只解码一次，在线性空间按原始亮度混合自有数字颜色，再由 Three 输出管线编码一次。无肤色评分、磨皮、结构形变、灯光/曝光差异。mask 羽化只向内，不能扩张授权区域。操作依固定顺序从基准重算，绝对强度不反复累积。

当前一次只支持一处保护。原貌保护在该 mask 内取原始采样路径；“保留当前效果”存一份独立 anchorOperations，保护区采样以该锚点重算。保护纹理最后严格覆盖编辑，存档保留锚点。两个 mask 数组分别将八项通道打包入两张 RGBA 纹理，避免超过模拟器片元 sampler 限制。

长期规则仅支持同一公共示例的原貌区域，由明确按钮保存；个人照片保护随作品保存。重开移除存档中过时的长期标记，再加载当前长期规则；若遇到本版无法合并的独立保护，会拒绝重开并说明原因。未实现“限定一次、限定操作”的专项例外，界面没有绕过保护的按钮。明确移除保护与临时例外不是同一功能。

## 文件、隐私与输出

照片由系统 PhotoViewPicker 选择并复制进应用 cache；JPEG/PNG ≤32 MiB，解码最长边 ≤4096。不要求整库权限，不上传。解码失败恢复旧会话。暂存注册另维护生命周期集合，避免保存/重开改变 ID 映射后漏删旧 cache。

保存到 `files/works/work-时间戳/`，包含必要源照片副本、mask、workspace.json（实际操作、授权 ID、版本、快照、保护锚点）。每个文件临时写入/fsync/rename，元数据最后落盘。当前没有作品缩略预览文件。重开校验资产版本、文件名、尺寸和存在性，缺失报错。公共 GLB 使用固定包内版本，个人 source.image 使用存档副本。

删除作品清理其独立私有目录；删除整份个人面容清理同 assetId 的保存作品、缓存/蒙版和当前私有导出，私密文字保留并单独提供删除。公共示例不删除；外部另存文件无法代删。相同照片再次导入产生另一个 assetId，不执行感知去重；删除范围据此展示。

重开时先将必要的存档源文件与蒙版复制为当前会话的临时资产。这样删除保存记录不会留下指向已删除目录的悬空注册；当前未保存会话仍能继续，退出时清理这些临时副本。生产文件操作已由原生 Hypium 的保存→重开→删除→读取→再次保存检查覆盖。

PNG 使用相同相机/合成、768×1024 RGBA8 sRGB RenderTarget；恢复 viewport/scissor/target、反转读回行，底部加“Digital expression · Not a product result”。比较分割、圈选线、键盘和账单不印入输出。正文完整、PNG 签名通过且原生成功原子写入 `files/self-export.png` 后才显示“私有目录已保存”。当前覆盖同名私有导出；未提供系统相册导出或外部分享。

产品资料 allowedViews 只有 brand-information，calibrationProfile 为空；PolicyEngine 拒绝 productSimulation。观察动画只是自有颜色参数色块，不修改面容快照、非剂量/修复/功效示意。支持流程由用户主动文字触发且需接受；私密文字用户主动保存，可编辑/删除，不写进商品排序。

音乐由原生 AmbientAudio 串行管理一个 AVPlayer，token 排除过时状态回调。用户主动开关、默认 off；后台关闭资源，前台仅恢复先前主动开启的状态。错误会清除开启意愿，避免后台再次启动。AmbiencePreference 只匹配有限主动文本；不会将音乐分类写入作品或产品记录。三段原始音轨由本项目生成并随 rawfile 打包。
