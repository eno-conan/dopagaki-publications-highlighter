# dopagaki-publications-highlighter

雑誌PDFや書籍PDFから、読みたい記事（書籍は章）だけを切り出し、重要な箇所に3色のマーカーを付けるツール。
章・記事ごとの参考文献・関連リンク（取得して確認済みのものだけ）は、GitHub Issue のコメントにまとめる。

| 色 | 意味 |
|---|---|
| 青 | 知る（定義・根拠・数値） |
| 緑 | 方針・実践（原則・具体的にやること） |
| 赤 | 注意（やってはいけないこと・限界） |

- 元PDFは書き換えず、コピーに注釈を追記する。再実行しても重複しない
- PDF はコミットしない（著作物のため `.gitignore` で除外）

## このリポジトリについて

自分が雑誌・技術書を効率よく読むために作った、個人用のツールです。商業利用は想定していません。同じように読みたい人が、自分の読書のために使ったり、改造したりするのは自由です。

- **ライセンス**: [PolyForm Noncommercial 1.0.0](LICENSE)。非商業目的（個人の学習・趣味・研究など）なら、使う・改造する・配るのは自由です。商業目的での利用はできません。OSI が定める「オープンソース」ではなく、ソース公開のライセンスです
- **著作物は含みません**: 雑誌・書籍のPDFは置いていません（`.gitignore` で除外）。各自で入手したPDFを使ってください。`output/`（作業フォルダ）の中身も、コミットしないようにしてあります。`examples/` の本は、説明用に書いた架空の内容です。実在の書籍・雑誌の本文の著作権は、各出版社・著者にあります
- **依存ライブラリ**: PDFの処理に [PyMuPDF](https://pymupdf.readthedocs.io/)（AGPL-3.0 / 商用ライセンスの二重ライセンス）を使います。同梱はせず、`uv sync` で各自の環境に入れます。PyMuPDF 自身の条件は、そちらに従ってください
- **無保証**: 動作や結果は保証しません
- **前提**: 本文を読んで重要箇所を選ぶ部分は、AI エージェント（[Claude Code](https://claude.com/claude-code)）が行う想定で、質問と参考文献の投稿に GitHub Issue（[GitHub CLI](https://cli.github.com/)）を使います。PDF の切り出し・マーカー付け・リンク確認のスクリプト単体でも使えます

Required Notice: Copyright (c) 2026 Enomoto Kota

## 使用例

架空の短い本で、入力（元PDF・`articles.json`・`highlights/*.json`）と出力（切り出し・マーカー付きPDF）を確かめられる。[examples/](examples/README.md)

## セットアップ

[uv](https://docs.astral.sh/uv/) と Python 3.11 以上が必要。

```bash
cd app
uv sync
```

## 使い方（概要）

**`作業開始.bat` をダブルクリック**すると、ブラウザで画面が開く。PDF をアップロードすると、取り込みから、回答待ち（Issue）までを自動で行う（[docs/workflow.md](docs/workflow.md) の「ダブルクリックで始める」）。

手で行うときは、号ごとに、元PDFと同じ名前（拡張子なし）の `output/<PDF名>/` フォルダを作り、元PDFを置いてから `app/` で実行する。

```bash
# 1. 記事を一覧にする（articles.json に残る）
uv run python plan_issue.py --pdf ../output/Sample-Magazine-2026年11月号/<号>.pdf
# 2. 対象にする記事を記録する
uv run python plan_issue.py --pdf ../output/Sample-Magazine-2026年11月号/<号>.pdf --include p100-105 p120-126
# 3. 本文を読み、重要箇所を output/Sample-Magazine-2026年11月号/highlights/<ID>.json に書く
# 4. 分割PDF（分割/<記事名>.pdf）、ハイライト付きPDF（マーカー付き/<記事名>.pdf）を一括で作る
uv run python build_issue.py --plan ../output/Sample-Magazine-2026年11月号/articles.json
```

書籍は、PDFを `inbox/` に置く。章単位に分ける案を作り、人（チャット）が承認してから切り出す。流れは [docs/workflow.md](docs/workflow.md) の「書籍を取り込む手順」。

全体の流れの図は [docs/flow.md](docs/flow.md)。

手順の詳細、重要箇所の選び方、JSON の形式、各スクリプトの個別の使い方、制約は [docs/workflow.md](docs/workflow.md) を参照。

開発に参加するとき（テスト、コミットのルール、人が判断すること）は [CONTRIBUTING.md](CONTRIBUTING.md) を参照。

## 構成

```
app/          スクリプト（PyMuPDF）とテスト
inbox/        書籍PDFの受け取りフォルダ（PDFを置く。`.gitkeep` だけ git に入る）
output/       作業フォルダ（元PDF・articles.json・highlights/*.json・成果物。中身はコミットしない）
  <PDF名>/    PDFごとのフォルダ（雑誌も書籍も同じ形）
examples/     架空の本の使用例（入力と出力）
docs/         全体の流れの図（flow.md）、運用の手順（workflow.md）、重要箇所の選定基準（highlight-criteria.md）、実績の記録（records.md）
```

## 開発

```bash
cd app
uv run pytest          # ダミーPDFを生成して検証（実PDF不要）
uv run ruff check .    # Lint
```
