# uxaudit

[English](./README.md) | [日本語](./README_ja.md)

> Web アプリのリリース前 UX チェック。プロダクトの主要なユーザージャーニーを再生し、スクリーンショットだけで判定し、1枚のレポートでトリアージします。

> [!WARNING]
> **v2 alpha**：このブランチでは、v1 のマルチエージェント構成を小さな CLI に置き換えています。インターフェースは今後も変わります。

E2E テストは「フローが動くか」を確かめます。uxaudit が確かめるのはその先です。初めて使う人が、画面の目的を理解し、次の操作を選び、タスクを終え、ミスから回復できるか。初回利用、エラーからの回復、操作後のフィードバック、空データや実データ、スマホ表示など、リリースのたびに見直すべきなのに忘れがちなところを見ます。

## 仕組み

1. **ジャーニーはリポジトリに置く**：`.uxaudit/journeys.yaml` に 3〜5 本のジャーニーを平易なステップ（`click: Save`、`fill: { target: { label: Email }, value: … }`）で書きます。初回だけエージェントが下書きし、人が直します。これがそのままリリースチェックリストになり、毎回同じ基準で測れます。
2. **キャプチャは決定的**：`uxaudit run` は Playwright で各ジャーニーを再生して録画し（動画にはステップ名、操作対象の枠、カーソルとクリックを重ねて表示）、ステップごとにスクショを保存します。操作の直後にも追加でコマを撮るので、0.5秒で消えるトーストも取りこぼしません。コンソールエラー、HTTP エラー、遅いステップ、横スクロール、押しても何も変わらないクリックも機械的に記録します。1 ジャーニー数秒です。
3. **判定役はピクセルしか見ない**：判定役はコードもスクリプトも読めないので、問題を「実装上は正しい」と言い訳できません。判定は pass/fail と最大 5 件の指摘で、各指摘はスクショ、段階（理解／判断／操作／回復）、具体的な修正案に結びつきます。
4. **レポートは 1 枚、トリアージは人が行う**：`uxaudit report` は、スクショとジャーニーごとの録画を載せた HTML を 1 枚出力します。各ステップや指摘から、動画の該当箇所へジャンプできます。見る人は各指摘を「直す」「許容」「問題なし」に振り分けます。Claude の Artifact として公開すると判断はページに保存され、Claude が読み戻せます。それ以外の環境では `triage.json` を書き出してコミットします。判断は次回以降の実行にも引き継がれます。
5. **修正はエージェントに戻す**：`uxaudit fixes` が、直すべき指摘を Markdown で出力します。

### ログインとテストデータ

```yaml
setup:
  command: npm run db:reset              # 実行ごとに1回
auth:
  member:                                # 1回ログインして各ジャーニーで使い回す
    steps:
      - goto: /login
      - fill: { target: { label: Email }, value: qa@example.com }
      - fill: { target: { label: Password }, value: "${env:QA_PASSWORD}" }
      - click: { role: button, name: Sign in }
journeys:
  - id: first-project
    auth: member
    before: npm run db:seed -- empty     # このジャーニー用のデータ
    ...
```

Google などの外部ログイン（パスキー、2段階認証、マジックリンクも同様）は、一度だけ手でログインしてセッションを使い回します。

```yaml
auth:
  member:
    recorded: true
    check: [{ goto: / }, { see: My projects }]   # セッションが生きているかの確認
```

```bash
uxaudit auth record member   # ブラウザが開くのでログインし、Enter を押す
```

セッションは `.uxaudit/.auth/`（git 管理外、本人だけが読める権限）に保存されます。毎回の実行前に確認し、期限が切れていたら録り直しを促します。外部サービスのログイン画面そのものは自動操作しません。CI では認証サービスのテストモードを使い、ログインの流れ自体（同意のキャンセル、アカウント連携など）を判定したい場合はローカルに偽の OIDC プロバイダーを立てます。

秘密情報は環境変数か git 管理外の `.uxaudit/.env` から読みます。キャプション、ブリーフ、レポートには `${env:…}` のまま表示されます。セッションは一時ディレクトリに置き、実行後に削除します。

## Claude Code で使う

```bash
/plugin marketplace add gotalab/uxaudit
/plugin install uxaudit@gotalab-uxaudit
```

あとは「uxaudit を回して」と頼むか、`/uxaudit:uxaudit` を実行します。初回だけ Playwright と Chromium をプラグインのデータディレクトリに入れます。

## どこでも CLI で使う

CLI は 1 ファイルで、実行時の依存は Playwright だけです。クラウドセッション、CI、他のコーディングエージェント（Codex、Cursor、Devin）でも同じように動きます。画像を読めるエージェントなら判定役になれます。`uxaudit brief` がそのまま使えるプロンプトを出力します。

```bash
uxaudit init                      # .uxaudit/journeys.yaml を作る
uxaudit run                       # 全ジャーニーをキャプチャ
uxaudit brief --journey <id>      # 判定プロンプト → runs/<id>/verdicts/<journey>.json に書かせる
uxaudit validate                  # 判定ファイルを検証
uxaudit report --artifact         # report.html（と Artifact 版）
uxaudit triage import <file|dir>  # レビュー結果を .uxaudit/triage.json に取り込む
uxaudit fixes                     # コーディングエージェント向けの修正リスト
```

npm に公開するまでは、チェックアウトから `pnpm install && pnpm build && node dist/uxaudit.mjs` で実行してください。Chromium は `npx playwright install chromium` で入れます。

## デモ

```bash
pnpm install && pnpm build
node examples/demo-app/serve.mjs &
cd examples/demo-app && DEMO_PASSWORD=pantry-demo node ../../dist/uxaudit.mjs run
```

デモアプリ（ログインとデータ投入あり）には 6 つの問題を仕込んであります。入力エラーが無言、保存の通知が0.4秒で消える、最初の画面が空、スマホでヘッダーがはみ出す、長いタイトルが切れる、サインインに失敗しても何も表示されない、の6つです。判定役はこれらをすべて見つけるはずです。

## 開発

```bash
pnpm test         # ビルド + ユニットテスト
pnpm typecheck
```

プラグインがビルドなしで動くように `dist/uxaudit.mjs` はコミットしています。ソースを変えたらコミット前にビルドしてください。

## ライセンス

Apache-2.0
