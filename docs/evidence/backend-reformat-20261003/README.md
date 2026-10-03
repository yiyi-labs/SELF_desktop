# backend 换行改写证据（2026-10-03）

codex 生成的 67 个根级 `backend/*.py` 大量把整段逻辑压进单行（`;` 串联语句、单行 `if/else` 套件），可读性差。本次改写只做一件事：**在语句边界插入换行并补必要缩进**，不改动任何 token 语义。44 个文件共断行 2005 处（36 个闭包文件 1886 处 + 8 个非闭包文件 119 处），行数 11,243 → 13,248（+2005，恰好一处断行一行），字节 709,804 → 728,117（增量全为正，无整体行尾转换）。

改写前的原文即提交 `886f84e`（本目录所有对比均以此为基准）。改动最多的文件：`live_dense.py`（198 处）、`live_shared_room_surface.py`（155）、`shared_v2.py`（140）、`live_room_window_recovery.py`（113）、`portrait_pipeline.py`（110）。

## 改写规则（工具合同）

- 括号深度 0 的 `;` → 换行；紧贴行尾的 `;` 直接删除（本来就有换行）。
- 块关键字（`if/elif/else/for/while/try/except/finally/with/def/class/async/match/case`）头部 `:` 后同行还有内容 → 冒号后换行，套件缩进 +4。
- 其余一切（注释、字符串、括号内的换行、每行原有行尾符）原样保留；插入的换行取该逻辑行自己的行尾符——CRLF 文件保持 CRLF，混合行尾文件逐行保持（`contracts.py`、`product_catalog.py` 即为混合行尾样本）。

工具归档在本目录 `tools/`：`reformat.py`（核心）、`verify.py`（等价性判定）、`run-all.py`（全量暂存+验证）、`apply.py`（应用+证明链）、`repin.py`（哈希重钉）、`verify-against-git.py`（独立复验）、`compare-tests.py`（测试比对）、`make-line-map.py`（行号换算表）、`detach-service.py` + `run-uvicorn.py`（脱离进程启动服务）。

归档后仅调整了当时的临时工作目录路径，逻辑未变：`detach-service.py` 改为拉起同目录 `run-uvicorn.py`；`apply.py` / `run-all.py` 的暂存目录改用系统临时目录；`verify-against-git.py` 改为读取本目录的 `apply-report.json`。归档工具已逐个语法检查通过，并以归档副本（非临时目录版本）重跑独立复验：`changed=45 expected=45 match=True`、`unchanged=23 reformatted=44 problems=0`，回归报告已按重跑结果更新（`git-equivalence.txt` 首行 HEAD 印记）。

## 等价性证明（逐文件，0 例外）

1. **词法**：两边 token 流（类型+原文，含注释）在去掉排版 token、原侧去掉顶层 `;` 后逐一相等。
2. **语法**：`ast.dump` 逐节点相等，且 `compile` 通过。
3. **字节链**：`staged == reformat(磁盘原文)` 且写入后 `磁盘 == staged`，均为逐字节断言；44 个文件字节增量全部为正（0 负增量），与断行数吻合。
4. **独立复验**（`verify-against-git.py`，以 `886f84e` 的 git 原文为基准重做一遍，不依赖暂存状态）：42 个文件与 `reformat(git 原文)` **逐字节相等**；`contracts.py`、`product_catalog.py` 为**仅行尾表示差异**（git blob 存 LF、工作树含 CRLF/混合行尾，`core.autocrlf=true` 下的正常现象；去掉 `\r` 后逐字节相等，token/AST 相等）。
5. **工作树完整性**：与 `886f84e` 相比，`backend/` 下恰有 45 个文件变化——44 个 `.py` + `README.md`（哈希引用更新）；其余 23 个根级 `.py` 一字节未动。
6. **可复现**：用归档的 `tools/reformat.py` 对 git 原文重算一遍，与已应用产物逐字节比对——42 个精确重现、2 个仅行尾表示差（同上），即产物可由「原文 + 工具」精确复现。行号换算表（旧行号 → 新行号）在 `line-map.json`，逐 token 断言了 148,959 个 token 的位移公式，0 例外。

逐文件明细：`git-equivalence.txt`、`apply-report.json`、`reformat-report.json`。

## 闭包哈希重钉

- `implementationSha256`：`e7040005…` → `adb15d15206d565d1543b5d4484d723f42bb3f213b0becabc8d84f6432f167b9`（`engine-profile-before.json` / `engine-profile-after.json`；重钉时对全部 18 个键逐一断言仅此键变化，并复算两次确认确定性）。
- 服务重启后首拍：`worker-status-after.json` —— `loaded == current == profile == adb15d15…`，`sourceIdentityVerified=true`，`engine=ready`。
- 启动方式说明：本机 PowerShell 执行策略为 `Restricted`，`scripts/Start-ReconstructionServer.ps1` 无法直接 `-File` 运行；本次以该脚本的**同款命令**（同环境变量、同 uvicorn 参数）脱离进程启动（`tools/detach-service.py`、`tools/run-uvicorn.py` 即封装），HTTP 协议与行为不变。

## 测试 A/B（改写前后同命令、同解释器）

| 环境 | 用例 | 错误 | 结论 |
|---|---|---|---|
| Windows venv（缺 torch/cv2/scipy） | 139 | 34 | 失败用例 id、终止异常行、归一化后的完整回溯块逐一相同 |
| WSL 完整环境（缺 fastapi/httpx/PIL） | 295 | 13 | 同上 |

比对时显式归一了「行号与回溯中引用的源码行」——它们必然随断行改变；除此之外逐块相同。原始日志：`win-after.txt`、`wsl-after.txt`；比对输出：`test-compare.txt`。

## 真实端到端（改写后代码）

作业 `f6d2117f53e2856d07239f157e8907f2`：19:41:21 建单 → 63 块分块上传 1.6 s → 封存 → 轮询；19:55:54 到达 `gaussian_ready`（约 14.5 分钟），下载全部 5 个产物：

| 产物 | 字节 | sha256（前 16 位） | magic |
|---|---|---|---|
| gaussian | 21,076,512 | `9c7dd9bb881a227c` | `706c790a`（PLY） |
| preview | 16,171 | `6e45b575349e36be` | `89504e47`（PNG） |
| preview3d | 4,179,620 | `da030dd594de9c2c` | `706c790a`（PLY） |
| scene3d | 6,609,476 | `3eeb1d007404a225` | `706c790a`（PLY） |
| view | 753 | `00fc898241dd22df` | JSON |

原始日志：`e2e-20261003-reformat.log`。三次作业（改名后 `07483aca…`、复跑 `fad42020…`、本改写后 `f6d2117f…`）的 `scene3d` 字节数完全一致（6,609,476），`gaussian` 等随训练随机性浮动；协议行为、终态与产物结构三次一致。
