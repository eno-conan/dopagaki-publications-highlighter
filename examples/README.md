# 使用例

架空の短い本（`sample-book`、6ページ・3章）で、このツールの入力と出力を確かめられる。本文は、説明用に書いた架空の文章で、実在の書籍・記事とは関係がない。

```
examples/
  make_sample.py                      ダミーPDFを作るスクリプト
  sample-book/
    sample-book.pdf                   元PDF（しおり付き）
    articles.json                     章の一覧と判断（第3章は対象外、分け方は承認済みの状態）
    reading.json                      読み方の答え（目的・重点・使う色）
    highlights/<ID>.json              重要箇所（本文の引用、色のラベル、理由）
    分割/<名前>.pdf                    章を切り出しただけのPDF
    マーカー付き/<名前>.pdf            重要箇所に色を付けたPDF（読むのはこれ）
```

## 作り直す

`app/` で実行する（[uv](https://docs.astral.sh/uv/) が必要）。

```bash
cd app
uv sync
# 分割PDFとマーカー付きPDFを、highlights/*.json から作り直す
uv run python build_issue.py --plan ../examples/sample-book/articles.json
# 重要箇所の text がPDFの本文と一致するかだけ確かめる
uv run python apply_highlights.py --pdf "../examples/sample-book/分割/第1章キャッシュの基本.pdf" \
  --highlights ../examples/sample-book/highlights/p1-2.json --dry-run
```

実際の書籍・雑誌では、元PDFを `inbox/` に置き、`output/<PDF名>/` で作業する。流れは [docs/flow.md](../docs/flow.md) と [docs/workflow.md](../docs/workflow.md)。
