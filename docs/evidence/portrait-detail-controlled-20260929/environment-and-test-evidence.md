# 本轮实际环境与测试

Windows NVIDIA RTX 5070 Laptop GPU / driver617.14 /8151 MiB；WSL torch2.8.0+cu128、gsplat1.5.3；真实CUDA tensor计算2.0通过。未改驱动、显卡模式或重启。

执行 `python -B -m unittest test_detail_controlled test_portrait_priority_training test_reconstruction_portrait_model`：21项，1.745s，OK。测试包括有效像素差分、绝对梯度配置、真实上游split及Adam/谱系同步，继承完整状态与拓扑恢复合同。没有把测试数量当画质通过。

pycolmap4.2.0；has_cuda=False。patch_match_stereo、stereo_fusion、undistort_images符号存在；patch_match_stereo文档明确requires CUDA。已核对/opt/self-reconstruction、/usr/local/bin、/usr/bin未找到独立colmap程序。不能以API符号存在冒称dense可用，本轮C未执行；不是RTX失效。

新投影审计a曾因int16索引类型失败，保留原目录和projection-a.log。改为long后b完成；c补相对足迹/被剔除点检查，全部零训练。最终审计源码保存在evaluation/audit-source-final，a/b未单独保存完整源文件，仅有修改前hash和日志，不能冒称这些衍生审计版本已独立完整归档。两项真正训练的初始化、中期、终态、Adam、策略、RNG、采样状态和源码快照均保存。
