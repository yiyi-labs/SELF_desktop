# 全幅模型接收合同修复

2026-10-02。用户授权接入最新建模能力并定位平板停在61%的故障。

## 原因与实际任务

任务749f4e9b4a94e755ffb5416e52d3661f已在13:41完成，state=gaussian_ready、progress=85。算法portrait-native-fullframe-20261002-research；local900、T3环境300、joint0。训练106.968秒，包含准备等的任务耗时262.1秒，allocated峰值709.475MiB。电脑没有训练进程是已完成，不是GPU失联。

输出view的reconstructionMethod是新版本。客户端downloadView只接受旧portrait-first-soft-surface-0.1-research，且新view没有旧faceTrackCount，因此必然抛出“个人模型视角内容无效”。pollReconstruction捕获后只显示统一等待，不记错误、不更新ready接收阶段进度，界面停在上一次61%。

## 修改

- ReconstructionTransportClient.ets：明确白名单新增新全幅方法标识；surfacePointCount、source/asset hash、schema、有限向量和FOV检查保持，不接受任意未知版本。
- SelfMirrorPage.ets：ready开始接收设85%，实际PLY字节接收回调更新至95%；接收异常记录SELF_RECON_RECEIVE_FAILED；保留轮询恢复、作品和现有交互。

## 验证

DevEco构建与SignHap通过，54.884秒，存在已有兼容/异常处理警告，不宣称零警告。使用entry-default-signed.hap对平板6DP0226117002287覆盖安装成功，不卸载。启动成功，保留pending自动恢复。

真实设备models/749f4e9b4a94e755ffb5416e52d3661f下已有PLY、view和预览。PLY SHA256为cd36aeddf1fd08959adaa375d6938d8ea654384ace70c48d78d7e218e85423dc，与电脑任务manifest一致。reconstruction-result.json指向本任务；reconstruction-pending.json已不存在。实际日志出现SELF_GS_VIEWER_INTERACTION。未读取或保存相机画面，没有重新拍摄或训练。

## 算法范围

当前仍是全幅执行测试版，不是所有离线研究模块的全量新视频服务。96节点共享背景场、失败衣物运动、CoTracker研究依赖和完整表面替换没有接入；不存在已验证的统一全量入口，不为完成接入而强行启用已拒绝候选。原工程签名、旧作品、AI/OLAY/上脸和生产查看器算法保持。

本轮通过实际结果接收与哈希校验；未新增画质、fps或全量算法验收。不把日志交互当作重建质量通过。未提交其他既有修改。
