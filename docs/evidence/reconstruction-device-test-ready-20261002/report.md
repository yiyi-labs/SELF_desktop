# 鸿蒙建模测试通道恢复

2026-10-02，约22:19（Asia/Shanghai）。用户请求确认接入并自行测试。平板已重新连接，本轮没有提交个人视频、操作相机、替换作品或安装HAP。

## 实际结果

当前鸿蒙应用可以通过USB访问电脑重建服务，不需要重新安装。GPU工作器已重新加载，经新鲜心跳与入口校验确认ready。设备本机通过toybox nc访问受认证的 `/v1/reconstruction/health` 返回ready，2,048字节随机非私人数据往返一致。

本轮发现并修复了配置阻塞：engine-profile仍保存旧版reconstruction_live_fullframe.py哈希，实际pipeline_entry会抛出test_source_hash_changed，而原常驻工作器仍刷新旧能力的ready心跳。已保存旧配置，将启用配置绑定到实际28个文件的依赖闭包，空闲时重启工作器。重启前重新确认queued/running/cancel_requested均为0；没有中断用户训练。

## 测试运行的算法范围

- 入口：reconstruction_live_fullframe.py，调用现有reconstruction_portrait_pipeline.py。
- 兼容协议版本标识：portrait-native-fullframe-20261002-research。
- 实际实现SHA-256：f12f8677f485404aa313904e8040241066a5442f47ab0e4ad98fea1d997e5798。
- 本地900步、环境300步；joint=0；surfaceRefine=false。
- 原生全幅投影后切ROI、现有FLAME Open与head-local SH1、现有PLY/来源/取消协议。
- 只有原片hash相同才复用准备缓存，不向新视频返回历史模型。

**这不是最新完整研究路线的全量新视频接入。**50,095点完整资产恢复用于保留与离线对照；完整状态恢复器不是通用新视频初始化器。上一轮被拒的宽核细分/去雾候选没有启用。当前可调用算法仍有头发、衣物、颈部及背景的已知局限，不能据此称其画质已通过。

原生测试入口、pipeline和若干依赖仍有先前未提交修改。本轮记录真实文件哈希，未将这些修改顺带提交；记录中的Git提交不能独自代表全部运行源码。source-identity.json记录了实际28文件哈希。生产健康接口仍主要依据心跳，后续修改源码时仍需重新校验配置与实际入口，不能单凭旧ready判断可运行。

## 本轮验证

- 13项真实回归通过，3.606秒：4项原生绘制/入口、4项运行路由、5项取消及输入清理。
- CUDA12.8，RTX5070 Laptop，设备显存8,123MiB；工作器真实启动自检完成。
- HDC设备6DP0226117002287，tcp:8787→tcp:8787 Reverse。
- 从平板请求受认证重建health成功；echo SHA-256为707f1f1442fead5a44537b9eb701cadfea8a43485bbd87d5d9234a005a35b993。
- 首次尝试向hdc shell标准输入直接发送HTTP未获得响应，未计为通过；改用设备shell内构造请求后通过。认证数据仅用于本机已配置后端，不写入报告或输出。
- 当前新视频的完整训练、回传后画质与帧率尚未在本轮验证，交由用户点按测试。上述网络测试不等于人像模型验收。

同目录保存启用前后profile、源码身份、工作器重启与设备访问记录。没有启用失败候选，没有改应用、签名、AI、OLAY、上脸、故事或已有作品。
