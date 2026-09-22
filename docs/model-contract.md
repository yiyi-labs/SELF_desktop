# DeepSeek 候选编辑协议 v1

截至 2026-09-22 官方[模型表](https://api-docs.deepseek.com/quick_start/pricing/)将 `deepseek-flash` 对应 DeepSeek-V4.1-Flash，支持 Vision 与 Tool Calls；`deepseek-v4-pro` 没有 Vision。本项目默认使用前者，不从旧 alias 推断能力。官方[Vision 指南](https://api-docs.deepseek.com/guides/vision/)确认 Chat Completions 的 `image_url` data URL 输入。工具指南本轮复查超时，早先读取结果及生产请求结构仍需通过真实调用验证。

**2026-09-22 17:54 真实模型有限测试通过。** `evidence/deepseek/live-results.json` 的一个红圆、三个蓝方块均正确识别颜色/形状/数量并返回预期工具候选。返回 model=`deepseek-flash`，指纹 `aeb56401ca74e127821c4f9126dcb669`；两次用量分别2042、2033 tokens，耗时1453、2079ms。`live-http-results.json` 另通过实际运行的本机后端得到有效 rose 候选（2035 tokens、1953ms），重复请求返回完全相同响应。它是电脑→后端→DeepSeek 测试，不能算手机完整编辑闭环。所有输入均为原创合成图，无人像上传。此前失败及限制见下文；通过三项不保证一般语言或视觉可靠性。

## 本机启动

1. Python 3.12；执行 `scripts/Setup-Backend.ps1 -Python 'python路径'`。固定依赖在 `backend/requirements.lock.txt`。
2. 在本机从 `.env.example` 建立 `backend/.env`，填写 DEEPSEEK_API_KEY；不要发到聊天、不要放进 ArkTS/HAP。现有文件不会由脚本覆盖。`.env`、虚拟环境、签名目录已从源码交付包排除。
3. `scripts/Start-Backend.ps1` 只监听电脑 `127.0.0.1:8787`。配置或更改 `.env` 后重启本后端进程。
4. 以实际设备 ID 执行 `hdc -t 127.0.0.1:5555 rport tcp:8787 tcp:8787`，将模拟器端口转至电脑；不是假设两个 localhost 相同。无需开全局防火墙。结束可执行相应 `rport rm tcp:8787 tcp:8787`，先用 `fport ls` 核对。
5. `scripts/Test-Backend.ps1 -Live` 会使用两张原创无个人信息的图（一个红圆、三个蓝方块）实际调用；它会计入服务端 API 用量。必须同时识别形状/数量/颜色并选择预期预设才通过，不只看 HTTP200。
6. 手机在用户明确请求后打开“云端理解”，确认本次上传，再发送当前图与同快照标注图；没有确认时没有照片外发。拒绝或失败仍可本地操作。

`/v1/edit-plans`、`/health` 是 SELF 自有后端路径，不是 Huawei/DeepSeek API。真实第三方端点是 `https://api.deepseek.com/chat/completions`。公网部署必须配置 SELF_BACKEND_TOKEN 并使用受信 HTTPS 反向代理；当前没有部署公网服务或账户/支付系统。

## 数据与有限能力

客户端 NetworkKit → 自有后端 JSON `{snapshot, images:[base64]}`。后端核验真实 PNG/JPEG 文件后构造 `image_url` 内容块，Base64 不混入普通 text。每次1–2张，默认768×1024；精确蒙版、GLB、私有路径及完整聊天历史不发送。标注图解释为选择提示，不是皮肤特征。

快照包括 requestId/snapshotId、asset/texture/region 版本、sceneRevision、独立 viewRevision、实际冻结相机、区域/层 ID、保护摘要和用户本次原话。当前支持一个候选操作：set_digital_tint、set_effect_level 或 remove_effect。rose/terracotta 两个通用数字预设；none/light/medium/strong→0/.18/.32/.5 数字混合强度，不是产品剂量。无标定 SKU、无真实功效参数、无任意代码/文件路径/授权字段。

共享 JSON Schema 直接从生产 Pydantic 类导出到 `shared/contracts/`；`scripts/export-model-contract.py` 可重建。ArkTS 二次核对枚举、已有 region/layer/preset、回复与快照版本。后端拒绝额外字段、未知 IDs、非编辑夹带操作、错误删除参数、虚构产品/证据。普通工具非 Beta strict，强制 `propose_edit_plan`，显式 `thinking.disabled`、stream=false、max_tokens1536。

## 授权、取消与隐私

模型提交候选 → 客户端最新状态校验 → 用户确认（已有范围内的明确调淡可直接调整）→ Native 准备并检查 → 成功才加入有效版本与账单。模型不能自行解锁保护。例外由用户点“仅这项允许修改重叠的保护区”，绑定单项和规则，不影响长期偏好。

旋转不使候选过期；编辑/区域/规则变化会使旧候选失效。pending、错误 requestId、重复/过期回复不能提交。取消销毁客户端请求并失效 generation；后端监测断连取消上游，已发给第三方的图片不承诺可撤回。

连接10s、上游读取45s、总50s；客户端读取55s。后端最多2个并发、12请求/分钟；重复 requestId+同摘要返回原结果，不同摘要409。仅缓存最多64份已校验计划和摘要，不保存图片。关闭 access log，不记录请求 body、个人困扰原文或密钥；错误只返回类别。第三方处理/留存仍依其实际条款。

17项实际离线测试覆盖候选、真实图片内容块构造、未知/越权字段、截断/多个工具、鉴权、拒绝上传、尺寸限制、重复请求和失败清理。真实超时/断网、手机→后端→DeepSeek完整往返、复杂语言指代、低置信视觉、小唇区识别质量尚未通过真实模型测试。

## 本次真实调用发现与修正

配置原保存于 `.env.example`，已迁移至只供本机读取且被打包排除的 `.env`；分发模板已清空密钥，HAP不含密钥。

首次两项收到 `invalid_plan`。合成图片诊断响应把区域/预设/图层ID放进 explanationRefs，并给新增图层复用已有layerId；程序拒绝。工具字段增加用途说明，explanationRefs限制为空、productProfileId限制为空。随后实际HTTP请求又出现编辑与澄清同时返回，已明确互斥规则并增加回归测试。另一次HTTP响应结构合法却擅自把用户指定rose改成terracotta，语义验收失败；已明确不得擅自换预设，最终复测通过。结构校验不能证明候选符合用户全部意图，最终候选仍需用户授权；不能把一次复测当作彻底解决模型可靠性。

保留证据：`initial-live-failures.json`、`initial-diagnostic.json`、`initial-http-failure.json`、`http-diagnostic.json`、`http-semantic-failure.json`。诊断原始响应仅来自合成图片测试；生产仍不记录用户图片、原话或上游响应正文。真实调用产生API用量；最终三项用量不能当作本轮全部费用。本轮曾再次访问官方文档但网络失败，模型别名到具体版本的映射沿用此前官方资料；实际返回只证明上述model别名和指纹。

模拟器 `emulator-connectivity.log` 显示真实NetworkKit health200、modelConfigured=true；仅验证连通性，该探针未触发付费模型调用。`backend/test_live_http.py` 可复现实际后端测试（先运行test_live.py生成原创夹具，再启动后端）；会发送一次付费调用及一次缓存重放。手机上的云端授权→候选→原生检查→有效提交→账单完整链路、真机和真实人像视觉质量仍未验证。
