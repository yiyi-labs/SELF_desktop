# SELF_desktop

[简体中文](README.md) · [English](README.en.md) · [日本語](README.ja.md) · **한국어**

![HarmonyOS](https://img.shields.io/badge/HarmonyOS-API_26-0A59F7?style=flat-square) ![ArkTS](https://img.shields.io/badge/ArkTS-Native_UI-3178C6?style=flat-square) ![C++](https://img.shields.io/badge/C%2B%2B-OpenGL_ES_3-00599C?style=flat-square) ![DeepSeek](https://img.shields.io/badge/AI-DeepSeek-536DFE?style=flat-square) ![3D Gaussian Splatting](https://img.shields.io/badge/3D-Gaussian_Splatting-7C3AED?style=flat-square) ![Python](https://img.shields.io/badge/Python-FastAPI-009688?style=flat-square) ![CUDA](https://img.shields.io/badge/GPU-CUDA-76B900?style=flat-square)

> 아름다움을 누구에게나 더 가까이. 세상 곳곳의 저마다 다른 아름다움이 빛날 수 있도록.

SELF_desktop은 SELF 프로젝트의 HarmonyOS 태블릿 앱과 데스크톱 재구성 작업 환경입니다. 디지털 초상, 편안한 AI 대화, 나다운 표현을 연결해 자신을 알아가고 표현하는 시간을 함께합니다.

## 우리가 중요하게 생각하는 것

아름다움의 의미는 각자의 몫입니다. 주근깨, 피부색, 시간이 남긴 흔적도 한 사람의 이야기가 될 수 있습니다. 다양한 정체성과 경험, 취향을 가진 사람들이 아름다움을 탐색할 도구를 더 쉽게 만날 수 있기를 바랍니다.

- **개성을 존중합니다.** 여러 미적 감각과 표현을 담을 수 있는 경험을 만듭니다.
- **선택은 사용자에게 있습니다.** 무엇을 보고, 이야기하고, 시도하고, 남길지 직접 결정합니다.
- **신뢰를 지킵니다.** 데이터 사용 방식을 설명하고 개인정보 설정과 동의를 경험 안에 담습니다.
- **기술을 친근하게 만듭니다.** 자연스러운 언어, 부드러운 반응, 이해하기 쉬운 조작을 지향합니다.

## 주요 경험

- 별을 모티브로 한 화면에서 자신의 작품을 둘러보고 디지털 초상에 관해 대화합니다.
- 궁금한 부분을 둘러 선택하면 해당 영역을 중심으로 대화할 수 있습니다. 기존 답변 배치와 한 줄씩 나타나는 표현을 유지합니다.
- 디지털 미리보기와 출처가 있는 관리·제품 정보를 살펴보며 다음 단계를 직접 선택합니다.
- 기기 간 전송으로 모델, 저장한 편집 내용, 카메라 시점을 이어갑니다.
- MatePad Edge에서 태블릿 경험을 이용하고, 필요에 따라 데스크톱 서비스와 GPU 워커로 개인 모델을 재구성합니다.

## 기술과 데이터 흐름

```text
HarmonyOS · ArkTS / ArkUI
  ├─ Native renderer · C++ / EGL / OpenGL ES 3
  ├─ 3D viewer · ArkWeb / PlayCanvas / Three.js
  ├─ AI clients → DeepSeek official API
  │    └─ Local credential storage · HUKS
  └─ Optional reconstruction → Windows / FastAPI → WSL / GPU worker
```

| 영역 | 구현 |
| --- | --- |
| 네이티브 UI | HarmonyOS, ArkTS, ArkUI. 대상 SDK API 26, 최소 호환 API 19 |
| 그래픽과 초상 | C++, EGL / OpenGL ES 3, ArkWeb, PlayCanvas, Three.js, 3D Gaussian Splatting 뷰어 |
| AI 대화 | 기기에서 DeepSeek 공식 API로 직접 요청합니다. 추론은 클라우드에서 이루어지며 PC 대화 프록시가 필요하지 않습니다 |
| 키 저장과 동의 | API 키를 기기 내 HUKS로 암호화하며, 클라우드 상호작용은 사용자 승인에 따라 진행합니다 |
| 선택적 재구성 | Windows의 Python / FastAPI 서비스와 WSL GPU 워커 |
| 개발과 검증 | DevEco Studio, Hvigor, OHPM, Node.js, 회귀 테스트 |

이 저장소는 태블릿 앱과 데스크톱 재구성 도구를 함께 포함합니다. `desktop`은 작업 환경의 역할을 뜻하며, 기기 앱은 HarmonyOS에서 실행됩니다.

## 개발 시작하기

DevEco Studio, HarmonyOS API 26 SDK, Node.js, npm을 준비해 주세요. IDE 안내에 따라 OHPM 의존성을 동기화하고, 개발 서명 정보는 각자의 로컬 환경에 설정합니다.

```powershell
git clone https://github.com/yiyi-labs/SELF_desktop.git
cd SELF_desktop
npm ci
```

DevEco Studio에서 저장소 루트를 열고 `entry` 모듈과 대상 기기를 선택해 실행합니다. 로컬 빌드 스크립트도 제공됩니다.

```powershell
New-Item -ItemType Directory -Force artifacts | Out-Null
.\scripts\Build-Hap.ps1
```

스크립트는 Windows의 기본 DevEco 설치 경로를 사용합니다. 다른 위치를 사용한다면 `-DevEcoHome`을 지정해 주세요. AI 키는 기기의 AI 설정에서 입력합니다. 데스크톱 재구성을 사용하려면 [백엔드 문서](backend/README.md)에 따라 환경을 준비한 뒤 `Start-SELF.cmd`로 서비스를 수동 실행합니다.

## 검증과 저장소 구성

```powershell
node --test viewer-gs/tests/freckle-demo.test.mjs
node --test viewer-gs/tests/selection-conversation.test.mjs
npm run test:transfer
```

| 디렉터리 | 내용 |
| --- | --- |
| `entry/` | HarmonyOS 앱, ArkTS 화면과 서비스, 네이티브 C++ 그래픽, 패키지 리소스 |
| `viewer-gs/`, `renderer-web/` | 3D 뷰어, 렌더링 소스와 테스트 |
| `backend/` | 선택적 재구성 서비스와 GPU 워커 |
| `shared/` | 공통 데이터 계약과 제품 자료 |
| `scripts/` | 빌드, 시작, 검증 도구 |
| `docs/`, `licenses/` | 기술 문서, 시점별 검증 기록, 제3자 라이선스 |

SELF는 계속 발전하고 있습니다. 디지털 미리보기, 관리 정보, 실제 사용 결과는 경험 안에서 각기 다른 역할을 갖습니다. 과거 검증 문서는 당시의 상태를 담고 있으므로 현재 동작은 최신 코드와 기기 테스트를 함께 확인해 주세요.

관련 저장소: [SELF](https://github.com/yiyi-labs/SELF). 사용성, 포용적인 설계, 그래픽 경험, 개인정보 보호에 관한 제안과 기여를 환영합니다. 제3자 자료와 구성 요소의 조건은 `licenses/` 및 리소스에 포함된 안내를 확인해 주세요.
