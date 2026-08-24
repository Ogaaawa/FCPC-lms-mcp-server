# FCPC LMS MCP server

FCPC (First City Providential College) の Moodle LMS を、AI アシスタントから
操作するための MCP サーバです。

A simple MCP server which can support your Moodle manipulation.
You can use LLM models which are "OpenAI" and localLLM(ollama).

this MCP server can assist following thing,
- show the due date of your assignments
- show the unread messages from your moodle
- show the uncompleted quizes
- show all courses you take


## かんたんセットアップ（推奨）

**開発者ツールを開いてトークンを探す必要はありません。**
Moodle のユーザー名とパスワードから自動で取得します。

> **パソコンが必要です。** MCP サーバは手元のパソコンで動くため、
> スマートフォン・タブレットだけでは利用できません。

### macOS
`セットアップ.command` を **ダブルクリック**してください。

### Windows
`セットアップ.bat` を **ダブルクリック**してください。

どちらも初回は仮想環境の作成とライブラリのインストールが自動で走ります
（数分かかることがあります）。事前に必要なのは次の2つだけです。

- [Python](https://www.python.org/downloads/) … Windows では
  インストール時に **「Add Python to PATH」に必ずチェック**を入れてください
- [Node.js](https://nodejs.org/) … Gemini から使う場合のみ必要

### うまく開けないとき（手動）
```
1. $ python -m venv venv
2. $ source venv/bin/activate      # macOS/Linux
   $ .\venv\Scripts\activate       # Windows PowerShell
3. $ pip install -r requirements.txt
4. $ python setup_gui.py
```

セットアップ画面が開くので、

1. **サイト URL** … 例) `https://lms.fcpc.edu.ph`（貼り付けは `/login/index.php` 付きでも OK）
2. **ユーザー名 / パスワード** … Moodle にブラウザでログインするときと同じもの
3. **「接続してセットアップ」** を押す

これだけでトークンの取得・確認・`.env` への保存まで終わります。
パスワードはトークン取得に使うだけで、保存されません。

「AI に質問する機能」（`client.py`）まで使う場合は、同じ画面で
**OpenAI API キー**と**モデル**（例 `gpt-4o`）も入力してください。省略しても Moodle 連携は動きます。

うまくいかないときは、原因（パスワード間違い・URL 間違い・サイト側の設定など）が
画面に日本語で表示されます。

> 画面を使わずコマンドラインで済ませたい場合: `python get_token.py`


## 実行方法
```
$ source venv/bin/activate
$ python client.py server.py            # OpenAI を使う場合
$ python client_localLLM.py server.py   # ollama を使う場合
```

設定が有効かどうかは、セットアップ画面の
**「保存済み設定で接続テスト」** ボタンでいつでも確認できます。


## Claude から使う（スマホ対応・登録は URL 1本だけ）

学生は **URL を1つ登録するだけ**です。パソコンは要りません。
Claude は無料プランで使えます。

### 先生（サーバーを動かす人）

`サーバー起動.command` を **ダブルクリック**すると URL が表示されます。

```
https://xxxx.trycloudflare.com/mcp
```

これを学生全員に伝えてください。**この画面を閉じるとサーバも止まります。**
事前に `brew install cloudflared` が必要です。

### 学生（スマホだけで完結）

1. ブラウザで [claude.ai](https://claude.ai) を開く（無料登録でよい）
2. 設定 → コネクタ → **カスタムコネクタを追加**
3. 名前は自由、URL に先生から聞いた **`https://.../mcp`** を貼る
4. Moodle のログイン画面が自動で開くので、いつもの ID とパスワードでログイン

以上です。あとは Claude アプリ（iPhone / Android）からも使えます。

```
「新着メッセージある？」
「今週締切の課題を教えて」
```

> コネクタを**追加**できるのは claude.ai（Web）だけですが、
> **スマホのブラウザからでも追加できます**。追加後はアプリに同期されます。

### 仕組み

```
学生の Claude ──HTTPS──▶ MCP サーバー ──▶ Moodle
              (OAuth で本人確認)
```

学生ごとの区別は **OAuth** で行います。ログインすると、その人の Moodle
トークンを**暗号化して埋め込んだ**アクセストークンが発行されます。

- サーバーは Moodle のトークンも学生のパスワードも**保存しません**
- パスワードはトークン取得に1度使うだけです
- 他人のデータが見えることはありません

`.oauth_key`（暗号鍵）と `.oauth_clients.json` は秘密情報です。
Git には含まれません。


## File architecture
- .env : your environment settings（セットアップ画面が自動生成します）
- setup_gui.py : セットアップ画面（トークン取得〜.env 保存）
- セットアップ.command : macOS 用のダブルクリック起動
- セットアップ.bat : Windows 用のダブルクリック起動
- moodle_auth.py : トークン取得・検証と .env 読み書きの共通処理
- get_token.py : トークン取得のコマンドライン版
- remote_server.py : Claude コネクタ用のリモート MCP サーバ（OAuth 付き）
- oauth_provider.py : OAuth 認可サーバ（トークンを保存しない方式）
- login_page.py : Claude から開かれる Moodle ログイン画面
- サーバー起動.command : サーバ公開（macOS）
- gemini_setup.py : Gemini CLI への登録処理（現在は未使用）
- list_tools.py : 登録済みツールの一覧表示（確認・デモ用）
- decode_token.py : SSO ログイン利用者向けのトークン取り出し
- client.py   : process user's query, create a answer via LLM
- client_localLLM.py   : when using a local LLM(ollama)
- moodle_client.py : Moodle API クライアント（ユーザーごとにトークンを持つ）
- server.py : run tools
- requirements.txt
- README.md


## Credits

このプロジェクトの MCP サーバ本体（`server.py` / `client.py` / `client_localLLM.py`）は
**Jiseong JEONG ([@jeongjisung690](https://github.com/jeongjisung690))** によって作成されました。
オリジナルのリポジトリ: https://github.com/jeongjisung690/Moodle---MCP-server

本リポジトリでは、上記をベースに以下を追加しています。

- Cloudflare 保護下の Moodle に対応（TLS フィンガープリント偽装）
- ユーザー名・パスワードからのトークン自動取得（`moodle_auth.py` / `get_token.py`）
- SSO ログイン利用者向けのトークン取り出し（`decode_token.py`）
- 非エンジニア向けのセットアップ画面（`setup_gui.py` / `セットアップ.command`）

## License

ライセンス未設定です。利用・再配布をご希望の場合は作者にお問い合わせください。
