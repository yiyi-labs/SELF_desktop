# 模拟器重建运行库安装核验与可选路线

后续已经连接 MatePad Edge 真机，结果见 [真机验证报告](matepad-edge-3dgs-verification.md)。该设备有实际运行库且能够显示合成 GS，但当前版本的重建查询仍返回 801；不能把“已连接真机”当成个人建模完成。

核对日期：2026-09-23。此报告补充此前的设备探针，不改变用户选择的设备端重建路线。

## 安装核验结果

华为 [Spatial Recon Kit 简介](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/spatial-recon-introduction) 的“模拟器支持情况”明确写明：“本Kit暂不支持模拟器。”本次通过该页面公开、无需登录的文档接口读取正文；返回 code 0，正文元数据 updatedDate 为 2026-09-21，页面展示更新时间字段为 2026-07-28。不能将后台更新时间当成发布新兼容能力的证据。

因此，先前的“缺少重建运行库”只是观测结果，不能理解为可补装的一般依赖。当前未找到官方提供的、可独立安装到此模拟器的重建组件。

| 项目 | 实际结果 |
| --- | --- |
| 当前 API26 平板镜像 7.0.0.106 | 指定重建、GS 渲染、GS 编辑库路径不存在；此前应用能力探针也报告不可用 |
| 官方新版平板镜像 7.0.0.107 | 已由 Emulator CLI 下载并解包到独立目录；未替换原平板及数据 |
| 新版镜像静态检查 | system.img、sys_prod.img、vendor.img 均未找到三个对应库文件名的字节串；这只是静态检查，不是运行成功证明 |
| 新版镜像启动与应用运行测试 | 未完成：独立实例创建命令没有产生有效实例，本轮未启动新版系统 |
| SDK x86_64 同名库 | 导出实现为返回指令的编译占位库，不能作为重建算法部署 |
| 为模拟器安装实际重建能力 | 未完成；官方当前不支持该环境 |
| 真人重建、保真、GS 贴脸圈选 | 未验证，本轮没有采集或上传真人画面 |

证据见 [audit.json](evidence/spatial-runtime-install/audit.json)、[当前设备库检查](evidence/spatial-runtime-install/device-libraries.txt)、[SDK 占位库检查](evidence/spatial-runtime-install/sdk-stub-disassembly.txt)。原始官方响应和新版镜像留在被 Git、交付包排除的 `artifacts/spatial-runtime-check` 下，不分发 SDK 或系统镜像。

## 不需要立即租用云服务器

1. **支持能力的鸿蒙真机 + 华为端侧接口，是当前首选验证路线。** 先在具体机型和系统版本上检查库、符号、IsSupport、AR 会话以及一组真实输入；不能仅凭 API26 或“支持 Tablet”认定全部设备都支持重建。还需完成 SELF 的 AR 图像/内参/位姿采集接线、真实产物加载、质量验收及 GS 表面圈选。更换设备不等于现有代码已完成全部功能。
2. **成熟扫描应用可用来检验真实素材和质量目标，但不是可直接嵌入 SELF 的引擎。** Scaniverse 经典模式提供 iOS/Android 本地 3DGS 采集与处理；其新企业模式则使用云处理，必须分清模式。没有核实到可直接供本工程接入的 HarmonyOS 重建 SDK。第三方导出的 PLY/SPZ 必须逐项检查属性、坐标、颜色和显示；导入成功也不等于 SELF 自主建模完成。
3. **本机 GPU 重建是无需云租赁的备选，尚未采用。** 本机只读硬件查询得到 RTX 5070 Laptop GPU、8151 MiB 显存。COLMAP 可恢复相机与结构，gsplat 提供 CUDA 3DGS 训练/渲染基础，但它们需要工程整合，也不是开箱即用的高精度人脸方案。当前硬件可作为验证平台，目标数据的显存占用、质量、耗时均未实测；不能为了适配 8 GB 显存擅自降低模型质量。用户此前坚持设备端，本轮没有安装该流水线或改变处理位置。
4. **云 GPU 是部署选项，并非 3DGS 的必需条件。** Remy 的公开合作案例采用手机 AR 图像/位姿采集、云端重建、端侧预览；这是 2025-12-30 公布的方案，不证明其最新所有模式均如此，也不意味着其私有服务可供 SELF 调用。租 GPU 还需要真正的重建程序、任务管理和产品接线，不能解决模拟器原生 GS 模块缺失本身。

上述路线均需独立验证人像保真。普通静态场景重建不能直接保证转头自拍、眨眼、表情变化时的几何稳定性。界面的二维人脸锁定不等于获得真实三维位姿；模型逼真也不等于唇缘、痣、耳廓和局部圈选已准确。保持此前“不以降质换速度”的要求。

## 本次查阅的一手资料

- [华为 Spatial Recon Kit 简介](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/spatial-recon-introduction)：模拟器限制。
- [HarmonyOS SDK 团队的 Remy 案例](https://www.cnblogs.com/HarmonyOSSDK/p/19419681)：2025-12-30，AR 采集与云端重建架构。
- [Scaniverse 开发者发布的应用说明](https://play.google.com/store/apps/details?id=com.nianticlabs.scaniverse)：经典模式的端侧处理。
- [Niantic Spatial 2026 发布说明](https://www.nianticspatial.com/capture/scaniverse-release-notes)：新增企业云模式与保留个人模式。
- [COLMAP 官方教程](https://github.com/colmap/colmap/blob/main/doc/tutorial.rst)：图像、相机与结构重建流程。
- [gsplat 官方文档](https://docs.gsplat.studio/main/)：CUDA 依赖、重建示例与渲染库能力。

本轮没有修改应用功能、调用 DeepSeek、租用云资源或上传个人数据。新镜像只完成下载/解包与静态核验，不能称为模拟器重建通过。
