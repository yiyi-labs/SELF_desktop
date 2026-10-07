# SELF_desktop

[简体中文](README.md) · **English** · [日本語](README.ja.md) · [한국어](README.ko.md)

![HarmonyOS](https://img.shields.io/badge/HarmonyOS-API_26-0A59F7?style=flat-square) ![ArkTS](https://img.shields.io/badge/ArkTS-Native_UI-3178C6?style=flat-square) ![C++](https://img.shields.io/badge/C%2B%2B-OpenGL_ES_3-00599C?style=flat-square) ![DeepSeek](https://img.shields.io/badge/AI-DeepSeek-536DFE?style=flat-square) ![3D Gaussian Splatting](https://img.shields.io/badge/3D-Gaussian_Splatting-7C3AED?style=flat-square) ![Python](https://img.shields.io/badge/Python-FastAPI-009688?style=flat-square) ![CUDA](https://img.shields.io/badge/GPU-CUDA-76B900?style=flat-square)

> Beauty, closer to everyone. A world where every corner has a story worth seeing.

SELF_desktop is the HarmonyOS tablet experience and desktop reconstruction workspace in the SELF project. It brings digital portraits, thoughtful AI conversations and personal expression together, making technology a companion in discovering and expressing who we are.

## What we believe

Beauty belongs to the person defining it. Freckles, skin tones and the traces of time can all be part of someone's story. We want more people to have access to tools for exploring beauty, with room for different identities, experiences and tastes.

- **Respect individuality.** Make space for many ways of seeing and expressing beauty.
- **Keep people in control.** Let the user decide what to observe, discuss, try and keep.
- **Earn trust.** Explain how data is used and make privacy choices and consent part of the experience.
- **Make technology approachable.** Use natural language, gentle feedback and understandable interactions.

## The experience

- Browse personal creations in a star-filled interface and explore a digital portrait through conversation.
- Select an area to focus the conversation, with the existing reply layout and gradual line reveal.
- Explore digital previews and sourced care or product information, choosing each next step yourself.
- Carry models, saved edits and camera views between devices through the transfer workflow.
- Use the tablet experience on MatePad Edge; optionally reconstruct personal models with the desktop service and GPU worker.

## Technology and data flow

```text
HarmonyOS · ArkTS / ArkUI
  ├─ Native renderer · C++ / EGL / OpenGL ES 3
  ├─ 3D viewer · ArkWeb / PlayCanvas / Three.js
  ├─ AI clients → DeepSeek official API
  │    └─ Local credential storage · HUKS
  └─ Optional reconstruction → Windows / FastAPI → WSL / GPU worker
```

| Layer | Implementation |
| --- | --- |
| Native interaction | HarmonyOS, ArkTS and ArkUI; target SDK API 26, minimum compatibility API 19 |
| Graphics and portraits | C++, EGL / OpenGL ES 3; ArkWeb, PlayCanvas, Three.js and a 3D Gaussian Splatting viewer |
| AI conversations | Direct device requests to the official DeepSeek API; cloud inference without a desktop conversation proxy |
| Credentials and consent | Local HUKS encryption for API keys; user-controlled authorization for cloud interactions |
| Optional reconstruction | Python / FastAPI on Windows with a WSL GPU worker |
| Development and validation | DevEco Studio, Hvigor, OHPM, Node.js and regression tests |

This repository includes the tablet application and desktop reconstruction tools. The `desktop` name describes that workspace; the device application runs on HarmonyOS.

## Getting started

Prepare DevEco Studio, the HarmonyOS API 26 SDK, Node.js and npm. Sync OHPM dependencies when prompted by the IDE and configure your own local development signing credentials.

```powershell
git clone https://github.com/yiyi-labs/SELF_desktop.git
cd SELF_desktop
npm ci
```

Open the repository root in DevEco Studio, select the `entry` module and run on your target device. A local build script is also provided:

```powershell
New-Item -ItemType Directory -Force artifacts | Out-Null
.\scripts\Build-Hap.ps1
```

The build script uses a Windows DevEco installation by default; set `-DevEcoHome` for a different location. Configure the AI key in the device's AI settings. For optional desktop reconstruction, follow the [backend documentation](backend/README.md), prepare the environment and start the service manually with `Start-SELF.cmd`.

## Validation and repository layout

```powershell
node --test viewer-gs/tests/freckle-demo.test.mjs
node --test viewer-gs/tests/selection-conversation.test.mjs
npm run test:transfer
```

| Directory | Contents |
| --- | --- |
| `entry/` | HarmonyOS app, ArkTS pages and services, native C++ graphics and packaged resources |
| `viewer-gs/`, `renderer-web/` | 3D viewer, rendering sources and tests |
| `backend/` | Optional reconstruction service and GPU worker |
| `shared/` | Shared data contracts and product information |
| `scripts/` | Build, startup and validation tools |
| `docs/`, `licenses/` | Technical documentation, dated validation records and third-party licenses |

SELF continues to evolve. Digital previews, care information and real-world outcomes have distinct roles in the experience. Historical validation documents describe their own stage of development; consult current code and device tests for current behavior.

Related repository: [SELF](https://github.com/yiyi-labs/SELF). Contributions to usability, inclusive design, graphics and privacy are welcome. See `licenses/` and the notices accompanying assets for third-party terms.
