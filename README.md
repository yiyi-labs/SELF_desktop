# SELF_desktop

**简体中文** · [English](README.en.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

![HarmonyOS](https://img.shields.io/badge/HarmonyOS-API_26-0A59F7?style=flat-square) ![ArkTS](https://img.shields.io/badge/ArkTS-Native_UI-3178C6?style=flat-square) ![C++](https://img.shields.io/badge/C%2B%2B-OpenGL_ES_3-00599C?style=flat-square) ![DeepSeek](https://img.shields.io/badge/AI-DeepSeek-536DFE?style=flat-square) ![3D Gaussian Splatting](https://img.shields.io/badge/3D-Gaussian_Splatting-7C3AED?style=flat-square) ![Python](https://img.shields.io/badge/Python-FastAPI-009688?style=flat-square) ![CUDA](https://img.shields.io/badge/GPU-CUDA-76B900?style=flat-square)

> 让美走近每一个人，让世界每一处角落的独特都被看见。

SELF_desktop 是 SELF 项目面向平板的 HarmonyOS 体验与桌面重建工作区。我们把数字肖像、温和的 AI 对话与自主表达连接起来，希望技术成为认识自己、表达自己的一束光。

## 我们相信

美的定义属于每个人。一处雀斑、一种肤色、一道岁月留下的痕迹，都可以成为个人故事的一部分。SELF 希望把探索美的工具带到更多人身边，让不同的身份、经历与审美都有表达的空间。

- **尊重差异**：珍视每个人的独特，设计能够容纳多种审美的体验。
- **选择在你**：观察、对话、尝试与保留，由使用者决定。
- **保护信任**：清楚说明数据如何使用，让隐私选择与操作授权成为体验的一部分。
- **让技术亲近人**：用自然的语言、柔和的反馈和可理解的交互，降低探索的门槛。

## 在这里可以做什么

- 在星空式界面中浏览个人作品，围绕数字肖像进行观察与交流。
- 圈选想了解的局部，让对话围绕当前区域展开；通过原有排版与逐行显示呈现回复。
- 探索数字预览与有来源的护理、产品资料，保留对每一步操作的选择权。
- 通过模型流转机制在设备之间衔接作品、已保存的编辑和视角。
- 在 MatePad Edge 上使用平板体验；按需通过桌面服务与 GPU 工作器进行个人模型重建。

## 技术与数据路径

```text
HarmonyOS · ArkTS / ArkUI
  ├─ Native renderer · C++ / EGL / OpenGL ES 3
  ├─ 3D viewer · ArkWeb / PlayCanvas / Three.js
  ├─ AI clients → DeepSeek official API
  │    └─ Local credential storage · HUKS
  └─ Optional reconstruction → Windows / FastAPI → WSL / GPU worker
```

| 层次 | 实现 |
| --- | --- |
| 原生交互 | HarmonyOS、ArkTS、ArkUI；目标 SDK API 26，最低兼容 API 19 |
| 图形与肖像 | C++、EGL / OpenGL ES 3；ArkWeb、PlayCanvas、Three.js 与 3D Gaussian Splatting 查看器 |
| AI 对话 | 设备直接连接 DeepSeek 官方 API；对话无需经由电脑代理，模型推理在云端完成 |
| 凭据与授权 | 设备本地 HUKS 加密保存密钥；云端交互由用户授权控制 |
| 可选重建服务 | Windows 上的 Python / FastAPI 服务与 WSL GPU 工作器 |
| 开发与验证 | DevEco Studio、Hvigor、OHPM、Node.js 与回归测试 |

本仓库同时包含平板应用与桌面重建工具；`desktop` 表示这套工作区的定位，设备端应用仍运行在 HarmonyOS。

## 开始开发

准备 DevEco Studio、HarmonyOS API 26 SDK、Node.js 与 npm。首次打开项目时，按 IDE 提示同步 OHPM 依赖；在本机配置自己的开发签名。

```powershell
git clone https://github.com/yiyi-labs/SELF_desktop.git
cd SELF_desktop
npm ci
```

在 DevEco Studio 中打开仓库根目录，选择 `entry` 模块与目标设备运行。项目也提供本机构建脚本：

```powershell
New-Item -ItemType Directory -Force artifacts | Out-Null
.\scripts\Build-Hap.ps1
```

构建脚本默认使用 Windows 上的 DevEco 安装路径，可通过 `-DevEcoHome` 指定自己的位置。AI 密钥在设备的 AI 设置中配置。需要桌面重建时，先阅读 [后端说明](backend/README.md)，完成环境配置后使用 `Start-SELF.cmd` 手动启动服务。

## 验证与项目结构

```powershell
node --test viewer-gs/tests/freckle-demo.test.mjs
node --test viewer-gs/tests/selection-conversation.test.mjs
npm run test:transfer
```

| 目录 | 内容 |
| --- | --- |
| `entry/` | HarmonyOS 应用、ArkTS 页面与服务、原生 C++ 图形模块和随包资源 |
| `viewer-gs/`、`renderer-web/` | 3D 查看器、渲染相关源码与测试 |
| `backend/` | 可选重建服务与 GPU 工作器 |
| `shared/` | 共享数据契约与产品资料 |
| `scripts/` | 构建、启动和验证工具 |
| `docs/`、`licenses/` | 技术文档、阶段验证记录与第三方许可 |

项目持续演进中。数字预览、护理资料和真实世界的使用结果在交互中保留各自的边界。历史验证文档记录对应阶段的状态，当前运行方式请结合源码与设备测试查看。

相关工程：[SELF](https://github.com/yiyi-labs/SELF)。欢迎围绕易用性、包容性、图形体验与隐私保护提出建议和贡献。第三方资产与组件的许可请查阅 `licenses/` 及资源附带的说明。
