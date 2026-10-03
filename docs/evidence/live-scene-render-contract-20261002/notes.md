# 当前显示合同与成熟方法取舍

2026-10-02。本项只添加通用离线检查，不修改生产查看器、应用或资产；没有运行训练或鸿蒙测试。用户截图本身不能确定job/资产身份，须由主任务另行核对。

## 实际锁定实现

生产 `viewer-gs/main.js` 使用 PlayCanvas 2.22.4，默认 unified=true；WebGL2使用CPU中心深度排序，普通PLY不是LOD资产。默认COMPACT、minPixelSize=2、antialias=false，未启用额外雾或后处理。静止canvas为CSS像素（maxPixelRatio=1），移动时根据220万像素预算下降至0.55—1；它可能影响清晰度，不能独自解释大片环境缺失。

实际 `gsplatCorner.js` 的投影轴受 `min(1024, viewport短边)` 限制。`gsplat.js` 将核尾重归一化为 `(exp(-4r²)-exp(-4))/(1-exp(-4))`，r²>1丢弃，forward alpha阈值1/255。中心深度分桶排序不是逐像素正确遮挡。这些是源码事实，不能据此把所有白雾责任归于同一公式。

COMPACT使用8bit log尺度和8bit alpha；LARGE仍存在半精度/打包。W的 `surface-evidence-face-clothing-20260929/report.md` 已实际证明：COMPACT→LARGE不改善，minPixelSize2→0.2像素不变；正常控制资产跨端RGB差0.004665，极宽核控制0.209422。本轮不重复阴性设置扫描。

完整50,095点资产已有跨端明显差异的实际证据。训练器依赖巨大核得到的覆盖，不能当作用户看到的背景；取消查看器限制会将更厚雾层带到终端。新候选必须固定同一PLY并实际目标端绘制。

本机源码位于node_modules/playcanvas/build/playcanvas/src/scene，SHA256：

- gsplatCorner.js：7319092bffae7a619bc06bb0cb395dabe38cb345f48ff53c494c5c7a6f77290c
- gsplat.js：00d18b3e8e2a33e71bae9d9dd9282e239fdbbd7e570808a2efe5d548d8a9399d
- gsplat-params.js：9e1b330b15e47832b026758fe39558af765f4bdcb3f7d2716e0bc788f555ef7f

## 已查阅的官方来源

| 原始来源 | 当前合理借鉴 | 兼容边界 |
|---|---|---|
| [StopThePop官方实现](https://github.com/r4dl/StopThePop)、[论文项目](https://r4dl.github.io/StopThePop/) | 对有限疑点像素比较中心顺序与射线贡献峰值顺序，量化旋转混合错误；优先避免单个宽体积横跨不相容表面 | radialSorting不等于层次逐像素排序；CUDA端换排序不等于WebGL显示已匹配 |
| [Mip-Splatting官方实现](https://github.com/autonomousvision/mip-splatting)、[融合PLY导出](https://github.com/autonomousvision/mip-splatting/blob/main/create_fused_ply.py) | 新表面采样的协方差结合有效观察分辨率和局部切向尺度，检查同资产缩放与多尺寸稳定性 | 3D平滑和2D滤波需训练/导出/显示成套对齐，不能补出未建模墙面或用平滑代替真实几何 |
| [PGSR官方项目](https://zju3dv.github.io/pgsr/)、[官方代码](https://github.com/zju3dv/PGSR) | 真实支持的静态片区用边界和多视图恢复连续有限表面，再输出标准3DGS；低纹理仍接受完整影像监督 | gsplat ED不是其平面距离/法线得到的无偏表面深度；加一个loss不等于复现PGSR |
| [2DGS官方项目](https://surfsplatting.github.io/)、[官方代码](https://github.com/hbb1/2d-gaussian-splatting) | 借鉴定向面元、厚度、法线和多视图一致性，先验证单个背景/衣物片区 | 全局压薄核不等于透视正确2DGS；特殊资产不能未经适配投入旧PLY链路 |

这些项目的效果与速度不构成SELF的质量、8GB或分钟级保证。这里只查阅思想，未安装或并入源码。StopThePop主体继承Gaussian-Splatting许可，部分header与popping metric为MIT；Mip-Splatting也要求遵循原3DGS许可。以后实际引代码必须另锁提交和逐文件许可。

本轮建议先接通真实完整观察/可靠几何/密度流程，并在目标引擎检查有效背景足迹和脸前污染。低纹理内容不能被特征支持mask删除，也不能通过无限放大核来补色。上一轮14→126的原错误体积细分没有产生独立新几何，不应继续作为主要修复。

## 可运行通用入口

新增 `backend/audit_live_scene_display.py`，复用现有 `scripts/probe-complete-baseline-display.mjs`：

- prepare：显式PLY、原生C/K、观察mask和可选原图；新私有目录保存逐字节PLY副本及hash。朝向由实测C确定，不重新lookAt面部中心。room强制使用observed_room，不偷换SIFT覆盖域。
- render：同PLY、C/K、near/far、W/H的gsplat1.5.3单次CUDA前向；无optimizer。GPU不可用直接报未执行。
- Node probe：实际PlayCanvas2.22.4 Chrome SwiftShader，本地拦截全部请求，不切格式或gamma。
- compare：核对资产hash、实际canvas、实际世界/投影矩阵、点数；固定face/room等完整区域，报告RGB/alpha均值/P90、低alpha代理及原图误差，生成原片/gsplat/PlayCanvas图。GL原始预乘RGBA只翻行，不二次乘alpha。

Python在WSL的P/backend，Node在Windows的P：

```text
python -B audit_live_scene_display.py prepare --asset <export/portrait.gaussian.ply> --camera <camera.json> --masks <masks.npz> --rgb <rectified-frame.png> --out .sources/<fresh-display>
python -B audit_live_scene_display.py render --out .sources/<fresh-display>
node scripts/probe-complete-baseline-display.mjs D:/STUDY/College/mine/olay/backend/.sources/<fresh-display>/display.json D:/STUDY/College/mine/olay/backend/.sources/<fresh-display>/playcanvas
python -B audit_live_scene_display.py compare --out .sources/<fresh-display>
```

camera JSON：sourceHash、reference、width、height、K、C、near、far。mask NPZ：face或face_core+face_boundary，以及observed_room，其他部件可选。调用者依据同一导出参考状态传入，不猜历史帧号，不从point ID推时间。fresh目录必须不存在，失败证据不覆盖。

5项CPU合同实际通过（0.013秒）：实测朝向、画幅/刚性拒绝、完整观察mask、缺失像素保留、GL行序与预乘alpha。新增入口尚未进行真实资产GPU/PlayCanvas整链，由主任务对新候选调用；旧绘制不能冒充新入口验证。此项未测HarmonyOS或设备fps。
