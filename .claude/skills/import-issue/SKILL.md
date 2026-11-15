---
name: import-issue
description: 雑誌PDFの新しい号を取り込む。記事を一覧にして対象を決め、重要箇所を選んで、切り出し・ハイライトまで作る。「新しい号を取り込む」「<yyyyMM>号を処理する」と頼まれたときに使う。
argument-hint: <yyyyMM> 例 202611
---

# 新しい号を取り込む

引数 `$ARGUMENTS` は号（例 `202611`）。作業フォルダは、元PDFの名前から拡張子を除いたもの（`202611` → `output/Sample-Magazine-2026年11月号/`。以下の `<PDF名>`）。手順と各コマンドの詳細は `docs/workflow.md` が正。ここは進め方だけを書く。コマンドは `app/` で実行する。

## 手順

1. **確認**: `output/<PDF名>/` に元PDF（名前に `_` を含まないPDF）があるか見る。なければユーザーに置いてもらう。
2. **一覧**: `uv run python plan_issue.py --pdf ../output/<PDF名>/<号>.pdf` で記事を一覧にする。
3. **対象の判断はユーザーに聞く**: 一覧（ID・タイトル・ページ数）を見せて、対象にする記事を選んでもらう。`target` は人の判断なので、勝手に決めない。決まったら `--include` / `--exclude` で記録する。
4. **（標準）分け方・対象・読み方をまとめて聞く**: `docs/workflow.md` の「自動で進める」の `ask_issue.py` で1つの Issue にし、`read_answers.py --apply --wait` で回答を待つ。以下は、チャットで聞くときの手順。
4. **読み方を聞く**: 対象の本文を読んで把握したあと、`docs/workflow.md` の「読み方を確認する」の3項目（目的・重点にする章や見出し・使う色）を、AskUserQuestion で選択式に聞く（スマホなどで答えたいときは、`docs/workflow.md` の「Issue で聞く」で Issue のチェックボックスにする）。本文から推測した目的や、見出しから挙げた重点の候補を選択肢に入れる。マーカーの集まりが書籍の要約になる前提で選ぶ。答えは人の判断で、代わりに答えない。`output/<PDF名>/reading.json` に残す。
5. **重要箇所を選ぶ**: `reading.json` の答えを踏まえて、対象の記事ごとに本文を読み、`docs/workflow.md` の「重要箇所の選び方」に沿って `output/<PDF名>/highlights/<ID>.json` を作る。
   - 参考リンクは公式ページや論文の要旨で確認し、裏づけが取れた箇所にだけ照合の印を付ける。
   - 確認用の切り出しPDFがまだなければ、`split_pdf.py --plan ... --only <ID>` で先に切り出して（`分割/<name>.pdf`）、`apply_highlights.py ... --dry-run` で `text` が一致するか確認する。
6. **一括で仕上げる**: `uv run python build_issue.py --plan ../output/<PDF名>/articles.json`。
7. **確認**: `uv run pytest` と `uv run ruff check .` を通す。`docs/records.md` の実績の表に行を足す。
8. コミット・プッシュはユーザーに頼まれたときだけ行う。

## 注意

- 元PDFは書き換えない。PDFはコミットしない。
- 記事が多いときは、1記事ずつ進めて途中経過を報告する。まとめて黙って進めない。
