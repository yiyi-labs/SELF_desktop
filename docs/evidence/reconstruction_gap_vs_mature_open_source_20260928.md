# SELF 与成熟研究的边界对照

2026-09-28；官方来源查阅，不下载/并入新研究代码或权重。本表是方法边界，不能当作复现这些论文已成功。

| 来源 | 当前做对 | 缺口/做错 | v3采用与不采用 |
|---|---|---|---|
| [FLAME官方](https://flame.is.tuebingen.mpg.de/) | 已用Open的共享形状、表情/头姿、三角绑定 | 头部模板解释不了头发、眼镜、服装；拟合关键点不等于本人细节真值 | 保留粗脸和绑定；独立附件、头发、躯干表示，普通版仅既有研究对照 |
| [GaussianAvatars官方仓库](https://github.com/ShenhanQian/GaussianAvatars)、[论文](https://arxiv.org/abs/2312.02069) | 局部绑定、来源继承、真实反传已有 | 细致可驱动网格、多视图约束、训练协议/预算与手持单目不同；不能用900步等同论文条件 | 借鉴绑定和阶段边界，不照搬其代码；论文不是8GB/2分钟成品保证 |
| [MonoHair官方](https://github.com/KeyuWu-CS/MonoHair)、[项目](https://keyuwu-cs.github.io/MonoHair/) | hair有独立语义和局部坐标雏形 | 缺专用外表面方向/深度支撑，2D掩膜壳不足；内部不可见发型不能称测得 | 借鉴外表面与内部未知分开；本轮不迁移其InstantNGP/PMVO/内部推断全链，不以生成发丝冒充原片测量 |
| [gsplat1.5.3](https://github.com/nerfstudio-project/gsplat/blob/v1.5.3/gsplat/strategy/ops.py) | 实际Adam、共同alpha和来源贡献、split事务已存在 | 标准库同步optimizer并不理解自定义绑定/来源；split通过不等于覆盖保持 | 锁定1.5.3；所有逐点字段采用同一重排映射，图像退化就回滚，不盲目加点 |
| [COLMAP官方FAQ](https://colmap.github.io/faq.html) | 静态人物排除mask、按文件名绑定相机、局部F和世界C分开 | 注册最多/默认preset不能证明几何真值；估计内参不等于独立标定 | 固定相机证据与mask，坏C不得训练房间，局部人像不被缺C阻塞 |
| PlayCanvas2.22.4实际安装源码 | PLY可解析、精确SH与可撤销编辑存在 | parser默认Morton存储重排破坏前缀和sidecar索引 | 隔离viewer保留源点序，并校验精确PLY哈希+逐点整数映射；不按坐标猜索引 |

## 许可与依赖

FLAME2023Open官方页面标明CC-BY-4.0，当前模型SHA e75a0990728ba038c7da2a420ae4396f7ddd7781366c13026066c5b24f127623。普通版许可不同，继续隔离。[FLAME模型许可](https://flame.is.tuebingen.mpg.de/modellicense.html)。

GaussianAvatars为[CC-BY-NC-SA及附加条款](https://github.com/ShenhanQian/GaussianAvatars/blob/main/LICENSE.md)，还继承GS相关许可；MonoHair的[许可](https://raw.githubusercontent.com/KeyuWu-CS/MonoHair/master/LICENSE.txt)为CC-BY-NC-4.0。两者本轮仅参考方法，**没有复制源代码、模型或训练数据**。没有“比赛所以版权忽略”的交付假设。

gsplat1.5.3为[Apache2.0](https://raw.githubusercontent.com/nerfstudio-project/gsplat/v1.5.3/LICENSE)，COLMAP4.2.0为[BSD](https://raw.githubusercontent.com/colmap/colmap/4.2.0/COPYING.txt)。使用现有安装版本，没有升级到main。MonoHair官方测试栈为3090Ti、torch1.11/CUDA11.3，不据此宣称在当前5070/8GB直接顺利执行。PlayCanvas沿用锁定依赖，无引擎替换。

## 顺序需要纠正

先局部可信人物，再静态场景，最后组合。人物不是只有脸：发、镜框、颈肩服装分别拥有表示、可信度和质量状态；无支持部件应明确阻断交接，不能以房间透明度补偿。场景阶段用人物排除监督；最终组合阶段共同前向，不能隐藏另一组。让RGB平均值替代这些边界，就是此前错误顺序反复发生的原因。

不强绑：眼镜≠五官表面，头发≠头皮，衣领≠颈部FLAME，静态房间≠衣物。可共享的是源时间、相机约定、部件身份、参考尺度和共同合成，不是全部自由参数从第一步起一起优化。
