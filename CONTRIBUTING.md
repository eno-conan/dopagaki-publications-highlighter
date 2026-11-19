# CONTRIBUTING.md

雑誌・書籍のPDFから記事（書籍は章）を切り出し、重要箇所にマーカーを付けるツール。概要は [README.md](README.md)、PDFを取り込む手順の詳細は [docs/workflow.md](docs/workflow.md)。コマンドの実行方法は、このファイルの「動かし方」。

## 開発の始め方

[uv](https://docs.astral.sh/uv/) と Python 3.11 以上が必要。コマンドは `app/` で実行する。

```bash
cd app
uv sync
```

変更したら、次を通す。

```bash
uv run pytest
uv run ruff check .
```

- コミット前に、`ruff` と `pytest` が全件通るかを自動で確認する。clone したら、次を一度だけ実行する（`app/` を変更するコミットのときだけ動く）

  ```bash
  git config core.hooksPath .githooks
  ```

- GitHub Actions でも、PRを開いたとき（と開き直したとき）に同じ確認が走る。追加のpushでは走らないので、コミット前のフックを有効にしておく。手動で走らせたいときは、Actions の「Run workflow」から。通らないPRはマージしない
- 1ファイル・1テストだけ実行する: `uv run pytest tests/test_plan_issue.py -k <名前>`
- テストはダミーPDFを生成するので、実PDFがなくても動く。実PDFを使うテストは書かない
- Windows では日本語の出力で文字化けすることがあるため、必要なら `PYTHONIOENCODING=utf-8` を付ける
- コメント・コミットメッセージは日本語で書く

## 動かし方（コマンド）

コマンドは `app/` で実行する（セットアップは、上の「開発の始め方」の `uv sync`）。

**画面から**: リポジトリ直下の `作業開始.bat` をダブルクリックする（Windows）。PDF をアップロードすると、取り込みから、回答待ち（Issue）までを自動で行う（[docs/workflow.md](docs/workflow.md) の「ダブルクリックで始める」）。

**手で**: **PDF 1つ（雑誌は1号、書籍は1冊）ごとに**、PDF と同じ名前（拡張子なし）のフォルダ `output/<PDF名>/` を作り、その中に PDF を置く。そのあと、次の順に実行する。

```bash
cd app
# 1. 記事（書籍は章）を一覧にする。結果は output/<PDF名>/articles.json に残る
uv run python plan_issue.py --pdf ../output/<PDF名>/<PDF名>.pdf
# 2. 対象にする記事を記録する（ID は一覧に出るページ範囲。例: p100-105）
uv run python plan_issue.py --pdf ../output/<PDF名>/<PDF名>.pdf --include p100-105 p120-126
# 3. 本文を読み、重要箇所を output/<PDF名>/highlights/<ID>.json に書く
# 4. 切り出したPDF（分割/<記事名>.pdf）と、マーカー付きPDF（マーカー付き/<記事名>.pdf）を一括で作る
uv run python build_issue.py --plan ../output/<PDF名>/articles.json
```

- 書籍は、章に分ける案を作り、人が分け方を承認してから切り出す（PDF は `inbox/` に置く）。コマンドは [docs/workflow.md](docs/workflow.md) の「書籍を取り込む手順」
- 質問の Issue、回答の反映、参考文献の投稿までを続けて行うコマンドは、[docs/workflow.md](docs/workflow.md) の「自動で進める」
- 実際に動かした例は [examples/](examples/README.md)（架空の本。`uv run python build_issue.py --plan ../examples/sample-book/articles.json`）
- **画面の見た目を確かめる**: `uv run python ui_tour.py`（`--open` で、作ったあと開く）。Playwright が画面を一通り操作し（アップロード → 回答 → 返事待ち → 作業中 → 中断・再開 → 完了 → 再アップロードの警告、ダークモード、スマホの幅）、スクリーンショットを `work-gai/ui-tour/ui-tour.pdf` にまとめる。サンプルの PDF（`examples/sample-book/`）を使い、GitHub にも Claude にもつながない。初回だけ `uv run playwright install chromium` でブラウザを入れる
- Issue への書き込み（`ask_issue.py --create`、`post_references.py --post`、`pipeline.py --issue` など）は、git の `origin` が公開リポジトリのとき、止まる。意図して書くときだけ `--allow-public`（または環境変数 `BOOK_MARKER_ALLOW_PUBLIC=1`）を付ける

## コミットするもの・しないもの

- PDF（元・切り出し・ハイライト付き）はコミットしない。著作物なので `.gitignore` で除外している
- 正は `highlights/*.json`・`references/*.json`・`articles.json`。切り出したPDFは `app/build_issue.py` で作り直せる生成物なので、直接編集しない
- 色とラベルの定義は `app/apply_highlights.py` の `GROUPS` / `CATEGORIES` だけに置く。他に複製しない

## 人が判断すること

次は人の判断で、コードや AI が勝手に決めない。

- `articles.json` の `target`（対象にするか）
- 書籍の分け方（記事・章の単位とページ範囲）と、その承認の記録 `split.approved`。承認するまで、切り出しも重要箇所の選定も始めない（流れは [docs/workflow.md](docs/workflow.md) の「書籍を取り込む手順」）
- 読み方（目的・重点にする章・使う色）。重要箇所を選ぶ前に選択式で聞き、`reading.json` に残す（[docs/workflow.md](docs/workflow.md) の「読み方を確認する」）

## 重要箇所を選ぶとき

選ぶ前に [docs/highlight-criteria.md](docs/highlight-criteria.md) を読み、`reading.json`（あれば）の答えを確かめる。号や書籍を処理したら、[docs/records.md](docs/records.md) の実績の表に行を足す。実績にないことは推測で補わず、「分かっていないこと」に足す。
