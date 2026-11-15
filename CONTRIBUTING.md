# CONTRIBUTING.md

雑誌・書籍のPDFから記事（書籍は章）を切り出し、重要箇所にマーカーを付けるツール。概要とセットアップは [README.md](README.md)、PDFを取り込む手順は [docs/workflow.md](docs/workflow.md)。

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
