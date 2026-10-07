# SELF_desktop

[简体中文](README.md) · [English](README.en.md) · **日本語** · [한국어](README.ko.md)

![HarmonyOS](https://img.shields.io/badge/HarmonyOS-API_26-0A59F7?style=flat-square) ![ArkTS](https://img.shields.io/badge/ArkTS-Native_UI-3178C6?style=flat-square) ![C++](https://img.shields.io/badge/C%2B%2B-OpenGL_ES_3-00599C?style=flat-square) ![DeepSeek](https://img.shields.io/badge/AI-DeepSeek-536DFE?style=flat-square) ![3D Gaussian Splatting](https://img.shields.io/badge/3D-Gaussian_Splatting-7C3AED?style=flat-square) ![Python](https://img.shields.io/badge/Python-FastAPI-009688?style=flat-square) ![CUDA](https://img.shields.io/badge/GPU-CUDA-76B900?style=flat-square)

> 美しさを、ひとりひとりの身近に。世界の隅々にある、その人らしさに光を。

SELF_desktop は、SELF プロジェクトのHarmonyOS タブレット向けアプリと、デスクトップでの再構成を支える開発環境です。デジタルポートレート、穏やかな AI との対話、自分らしい表現をつなぎ、自分を知り、表現する時間に寄り添います。

## 大切にしていること

美しさをどう捉えるかは、一人ひとりのものです。そばかすも、肌の色も、時とともに刻まれた変化も、その人の物語の一部になり得ます。さまざまな背景や経験、感性を持つ人が、美しさを探る道具を手にできることを目指しています。

- **個性を尊重する**：多様な美意識と表現を受け止める体験を育てます。
- **選択を本人に委ねる**：見る、話す、試す、残す。その一歩を利用者が選べます。
- **信頼を大切にする**：データの用途を伝え、プライバシー設定と同意を体験の中に組み込みます。
- **技術を身近にする**：自然な言葉、穏やかな反応、理解しやすい操作を心がけます。

## できること

- 星空をモチーフにした画面で自分の作品を眺め、デジタルポートレートについて対話する。
- 気になる部分を囲んで、選択した領域に沿った対話を進める。返信は従来のレイアウトと段階的な行表示で届きます。
- デジタルプレビューや出典のあるケア・製品情報を見ながら、次の操作を自分で選ぶ。
- デバイス間の転送機能で、モデル、保存した編集、カメラの視点を引き継ぐ。
- MatePad Edge でタブレット向けの体験を利用し、必要に応じてデスクトップサービスと GPU ワーカーで個人モデルを再構成する。

## 技術とデータの流れ

```text
HarmonyOS · ArkTS / ArkUI
  ├─ Native renderer · C++ / EGL / OpenGL ES 3
  ├─ 3D viewer · ArkWeb / PlayCanvas / Three.js
  ├─ AI clients → DeepSeek official API
  │    └─ Local credential storage · HUKS
  └─ Optional reconstruction → Windows / FastAPI → WSL / GPU worker
```

| 分野 | 実装 |
| --- | --- |
| ネイティブ UI | HarmonyOS、ArkTS、ArkUI。対象 SDK は API 26、最小互換 API は 19 |
| グラフィックス | C++、EGL / OpenGL ES 3、ArkWeb、PlayCanvas、Three.js、3D Gaussian Splatting ビューアー |
| AI 対話 | デバイスから DeepSeek の公式 API に直接接続。推論はクラウド上で行い、対話用の PC プロキシは不要 |
| 認証情報と同意 | API キーはデバイス内で HUKS により暗号化。クラウドとのやり取りは利用者の許可に基づく |
| 任意の再構成機能 | Windows 上の Python / FastAPI サービスと WSL GPU ワーカー |
| 開発・検証 | DevEco Studio、Hvigor、OHPM、Node.js、回帰テスト |

このリポジトリにはタブレットアプリとデスクトップの再構成ツールが含まれます。`desktop` は開発環境の役割を表し、デバイス上のアプリは HarmonyOS で動作します。

## 開発を始める

DevEco Studio、HarmonyOS API 26 SDK、Node.js、npm を用意してください。IDE の案内に従って OHPM の依存関係を同期し、開発用の署名情報は各自の環境で設定します。

```powershell
git clone https://github.com/yiyi-labs/SELF_desktop.git
cd SELF_desktop
npm ci
```

DevEco Studio でリポジトリのルートを開き、`entry` モジュールと対象デバイスを選んで実行します。ローカルのビルドスクリプトも利用できます。

```powershell
.\scripts\Build-Hap.ps1
```

スクリプトは Windows の DevEco インストール先を既定値としています。別の場所を使う場合は `-DevEcoHome` を指定してください。AI キーはデバイスの AI 設定で入力します。デスクトップでの再構成を使う場合は [バックエンドの説明](backend/README.md) に沿って環境を準備し、`Start-SELF.cmd` で手動起動します。

## 検証とディレクトリ構成

```powershell
node --test viewer-gs/tests/freckle-demo.test.mjs
node --test viewer-gs/tests/selection-conversation.test.mjs
npm run test:transfer
```

| ディレクトリ | 内容 |
| --- | --- |
| `entry/` | HarmonyOS アプリ、ArkTS の画面とサービス、C++ グラフィックス、同梱リソース |
| `viewer-gs/`、`renderer-web/` | 3D ビューアー、描画関連のソースとテスト |
| `backend/` | 任意の再構成サービスと GPU ワーカー |
| `shared/` | 共通のデータ契約と製品情報 |
| `scripts/` | ビルド、起動、検証ツール |
| `docs/`、`licenses/` | 技術資料、時点ごとの検証記録、第三者ライセンス |

SELF は継続して開発を進めています。デジタルプレビュー、ケア情報、実生活での結果には、それぞれ異なる役割があります。過去の検証資料は当時の状態を示すため、現在の動作は最新のコードとデバイスでの検証結果を確認してください。

関連リポジトリ：[SELF](https://github.com/yiyi-labs/SELF)。使いやすさ、多様性に配慮した設計、描画体験、プライバシーについての提案や貢献を歓迎します。第三者の素材・コンポーネントの条件は `licenses/` と各リソースの説明をご確認ください。
