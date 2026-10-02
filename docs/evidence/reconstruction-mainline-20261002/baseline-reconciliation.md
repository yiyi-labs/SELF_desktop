# 本轮基线身份纠正

2026-10-02。用户指出既有绕看视频中的环境已更完整。本次只核对模型身份与已有证据；本次核对没有训练、部署、回传或修改平板作品。

## 结论

用户的提醒成立。此前本轮 mainline 对照从 P 的旧 prepared 重新初始化，没有恢复 W 中已形成的完整人物、身体和房间状态。因此这些对照中出现的大片背景缺失，不能证明最新完整研究模型发生同样退化。那些运行及失败证据保留，但不作为继承已有成就的质量对照。

点数仅用于身份核对，不作为质量放行标准。两份资产来自不同视频，不能直接进行同条件画质比较。

| 身份 | 来源 | 资产 SHA-256 | 点数 | 当前用途 |
|---|---|---|---:|---|
| 可恢复完整研究起点 body-transition-sh | capture-1790410633104.mp4，source 7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf | a343ccf05292ce1e174c7fd63795122347a8d03bd0202a19395a9a414b691f41 | 50095 | 保留完整内容的研究起点；不是整体发布通过 |
| shared-scene-geometry 连续绕看候选 | 同上 | fd21c779eaa77d709705ff34e5118075523b3b2a5b9314458f66ad4f692355d6 | 50095 | 最新共享几何研究对照，仍未采用 |
| 平板 reconstruction-result 当前指向 | job 749f4e9b4a94e755ffb5416e52d3661f，source 24ef48a588804ccc9b52fa63f3bfdb9732b63ef9a2bc8ddc275a3c581fcec219 | cd36aeddf1fd08959adaa375d6938d8ea654384ace70c48d78d7e218e85423dc | 28802 | 实际设备保存作品；不是上述完整研究候选 |

平板 28802 点来自 view 中 editableSplats/surfacePointCount=6826 与 recordedEnvironmentSplats=21976。本次在设备文件系统实际读取 view 和 reconstruction-result，并用 sha256sum 校验 PLY；没有操作相机。作品指针不单独证明前台当前正显示哪份作品，本次没有截图或点按确认前台。

## 实物与证据核对

- P HEAD：664c8cb9b27074b3dc3745cbf7f7d794b7c2227b，原有 dirty 状态保留。
- W HEAD：e443a5a32a6a0413e052f8300e67110297e33620。未 checkout/reset/clean 或修改 W。
- 完整起点 PLY 与检查点均存在，实际文件 SHA 与旧报告一致。检查点 SHA：c3425ba01892940353909dbf3f95d5058ef507e023357ef864d4cb1460cac344。
- 用 PyTorch weights_only=True 和固定标准 NumPy 数据类型白名单安全读取完整检查点；67 个模型字段，含 model/optimizers/bindings/samplers/rng/strategy/scheduler/extra。未执行任意 pickle，也未声称本次完成了数值模型重放或精确 Adam resume。
- 最新绕看视频：C:/Users/30243/.codex/worktrees/reconstruction-bottom-up-20260928/olay/backend/.sources/shared-scene-geometry-20261002-b/quality-orbit/frozen-ply/frozen-ply-orbit.mp4。
- 视频实际 SHA：c756829955b0131a64e46937ef1627f74055484edac43e16e12cf788130e5c09；邻接 result/display 将其关联到 fd21c779...、原生 1080×1920、reference frame_0010.png。视频由 gsplat1.5.3 绘制，不是 HarmonyOS 验收。
- 实际查看 orbit-000.png：柜体与天花板保持连续，衣物存在；仍有柔化、薄雾与颈部接缝，不能从单张图推断全部角度无孔洞。

## 纠正此前结论

1. 撤回将本轮旧初值对照描述为“最新完整模型仍有同样大片空洞”的结论。
2. 完整研究状态并未丢失，也没有被这些实验覆盖；失败对照未回传平板。
3. 算法字符串 portrait-native-fullframe-20261002-research 不等于完整研究阶段已经进入服务。旧 live 接入报告也明确说明其仍使用旧场景初始化，完整表面替换与身体表示未全量接入。
4. 新代码已写入与实际服务已调用必须分别验证，不能仅凭新文件、相同版本字符串或 health ready 宣称全量接入。

本次实际验证现存 profile 与工作区入口时，得到 `test_source_hash_changed:reconstruction_live_fullframe.py`：开发中的改动尚未重新冻结到运行合同。本次没有为绕过保护而重写 hash 或启用失败修复。HTTP health 的 ready 不能替代这项逐任务检查；新的完整算法接入仍未完成，也不能报告可直接开始新算法测试。

## 继续实施的入口约束

后续首先承接可恢复的完整研究状态和有效部件生成能力，确认关闭新增修复时能保住该起点的点、绑定、SH、协方差、身体与背景。不得再回到稀疏身体初值作为用户认可质量的比较基线。

服务接入必须是面向新采集的可复用阶段，不能把这份旧个人 PLY 直接返回给新视频冒充新建模。当前共享几何候选仍未采用，其小幅数值变化不构成整体通过。完整内容保留、去雾、颈肩连接与双端绘制仍需独立真实验收。

本次通过：文件/来源身份校验、平板落盘资产校验、安全检查点元数据读取、已有绕看画面复核。

本次未做：新训练、完整状态数值重放、新算法服务切换、新资产 HarmonyOS 绘制与帧率测试。
