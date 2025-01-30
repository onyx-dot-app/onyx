<!-- DANSWER_METADATA={"link": "https://github.com/onyx-dot-app/onyx/blob/main/README_ja.md"} -->

<a name="readme-top"></a>

<p align="right">
<a href="https://github.com/onyx-dot-app/onyx/blob/main/README.md">English</a> | 日本語
</p>

<h2 align="center">
<a href="https://www.onyx.app/"> <img width="50%" src="https://github.com/onyx-dot-app/onyx/blob/logo/OnyxLogoCropped.jpg?raw=true)" /></a>
</h2>

<p align="center">
<p align="center">オープンソースの生成AI + エンタープライズ検索</p>

<p align="center">
<a href="https://docs.onyx.app/" target="_blank">
    <img src="https://img.shields.io/badge/docs-view-blue" alt="ドキュメント">
</a>
<a href="https://join.slack.com/t/onyx-dot-app/shared_invite/zt-2twesxdr6-5iQitKZQpgq~hYIZ~dv3KA" target="_blank">
    <img src="https://img.shields.io/badge/slack-join-blue.svg?logo=slack" alt="Slack">
</a>
<a href="https://discord.gg/TDJ59cGV2X" target="_blank">
    <img src="https://img.shields.io/badge/discord-join-blue.svg?logo=discord&logoColor=white" alt="Discord">
</a>
<a href="https://github.com/onyx-dot-app/onyx/blob/main/README.md" target="_blank">
    <img src="https://img.shields.io/static/v1?label=license&message=MIT&color=blue" alt="ライセンス">
</a>
</p>

<strong>[Onyx](https://www.onyx.app/)</strong>（旧Danswer）は、企業のドキュメント、アプリケーション、そして人々をつなぐAIアシスタントです。
Onyxはチャットインターフェースを提供し、お好みのLLMと連携することができます。Onyxはノートパソコン、オンプレミス、クラウドなど、
あらゆる場所とスケールでデプロイ可能です。デプロイメントは自己管理型のため、ユーザーデータとチャットは完全にあなたの管理下に
置かれます。Onyxはデュアルライセンスで、その大部分がMITライセンスの下で提供され、モジュール式で拡張が容易な設計となっています。
また、ユーザー認証、ロール管理（管理者/一般ユーザー）、チャット永続化、AIアシスタント設定用UIなど、本番環境での使用に
必要な機能を完備しています。

Onyxは、Slack、Google Drive、Confluenceなど、一般的な職場ツール全般にわたるエンタープライズ検索としても機能します。
LLMとチーム固有の知識を組み合わせることで、Onyxはチームの専門家となります。チームの独自の知識にアクセスできるChatGPTを
想像してみてください！「顧客が機能Xを求めているが、これは既にサポートされているか？」や「機能Yのプルリクエストはどこにあるか？」
といった質問に答えることができます。

<h3>使用例</h3>

Onyx Webアプリケーション：

https://github.com/onyx-dot-app/onyx/assets/32520769/563be14c-9304-47b5-bf0a-9049c2b6f410

または、既存のSlackワークフローにOnyxを組み込むことも可能です（さらなる連携機能も近日公開予定:grin:）：

https://github.com/onyx-dot-app/onyx/assets/25087905/3e19739b-d178-4371-9a38-011430bdec1b

コネクターやユーザーを管理するための管理者UIの詳細については、
<strong><a href="https://www.youtube.com/watch?v=geNzY1nbCnU">完全なビデオデモ</a></strong>をご覧ください！

## デプロイメント

Onyxは単一の`docker compose`コマンドで、ローカル（ノートパソコンでも可能）または仮想マシン上に簡単に
実行できます。詳細は[ドキュメント](https://docs.onyx.app/quickstart)をご覧ください。

また、Kubernetes上でのデプロイメントも組み込みでサポートしています。関連ファイルは[こちら](https://github.com/onyx-dot-app/onyx/tree/main/deployment/kubernetes)で確認できます。

## 💃 主な機能

- ドキュメントを選択してチャットできるチャットUI
- 異なるプロンプトと知識ベースを持つカスタムAIアシスタントの作成
- お好みのLLMとの連携（完全なエアギャップソリューションのための自己ホスティング可能）
- 自然言語クエリに対するドキュメント検索 + AI回答
- Google Drive、Confluence、Slackなど一般的な職場ツールとの連携
- Slack上で直接回答や検索結果を取得できる統合機能

## 🚧 ロードマップ

- 特定のチームメイトやユーザーグループとのチャット/プロンプト共有
- マルチモーダルモデルのサポート、画像や動画とのチャット
- チャットセッション中のLLMとパラメータの選択
- ツール呼び出しとエージェント設定オプション
- 組織の理解とチームからの専門家の特定・推薦機能

## Onyxのその他の注目すべき利点

- ドキュメントレベルのアクセス管理を備えたユーザー認証
- 全ソースにわたる最高クラスのハイブリッド検索（BM-25 + プレフィックス対応埋め込みモデル）
- コネクター、ドキュメントセット、アクセス等を設定する管理者ダッシュボード
- カスタム深層学習モデル + ユーザーフィードバックからの学習
- 簡単なデプロイメントと任意の場所でのホスティング可能

## 🔌 コネクター

以下のサービスから最新の変更を効率的に取得：

- Slack
- GitHub
- Google Drive
- Confluence
- Jira
- Zendesk
- Gmail
- Notion
- Gong
- Slab
- Linear
- Productboard
- Guru
- Bookstack
- Document360
- Sharepoint
- Hubspot
- ローカルファイル
- Webサイト
- その他多数...

## 📚 エディション

Onyxには2つのエディションがあります：

- Onyx Community Edition (CE)は、MITエクスパットライセンスの下で無料で利用可能です。このバージョンには上記の主要機能が全て含まれています。上記のデプロイメントガイドに従うと、このバージョンのOnyxが入手できます。
- Onyx Enterprise Edition (EE)には、主に大規模組織向けの追加機能が含まれています。具体的には以下の機能が含まれます：
  - シングルサインオン（SSO）、SAMLとOIDCの両方をサポート
  - ロールベースのアクセス制御
  - 接続されたソースからのドキュメント権限の継承
  - 管理者がアクセス可能な使用状況分析とクエリ履歴
  - ホワイトラベリング
  - APIキー認証
  - シークレットの暗号化
  - その他多数！最新情報は[ウェブサイト](https://www.onyx.app/)をご確認ください。

Onyx Enterprise Editionを試すには：

1. [クラウド製品](https://cloud.onyx.app/signup)をご確認ください。
2. セルフホスティングについては、[founders@onyx.app](mailto:founders@onyx.app)までご連絡いただくか、[Cal](https://cal.com/team/danswer/founders)で通話予約をお願いします。

## 💡 コントリビューション

コントリビューションをお考えですか？詳細については[コントリビューションガイド](CONTRIBUTING.md)をご確認ください。

## ⭐スター履歴

[![Star History Chart](https://api.star-history.com/svg?repos=onyx-dot-app/onyx&type=Date)](https://star-history.com/#onyx-dot-app/onyx&Date)