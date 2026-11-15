# AGENTS.md

雑誌・書籍のPDFの記事（書籍は章）を切り出し、重要箇所にマーカーを付けるツール。使い方は [docs/workflow.md](docs/workflow.md)、概要は [README.md](README.md)。

## 合図と進め方

### 標準の流れ（Issue 1回で済ませる）

人の作業は「PDF を `inbox/` に置いて『作業開始』と言う」と「Issue にチェックを付ける」の2つだけ。AI は、次のとおり進める。細かい手順は [docs/workflow.md](docs/workflow.md) の「自動で進める」。

1. `output/<PDF名>/` に PDF を移し、分割案を作る（`plan_issue.py`）。対象の本文を読んで把握する
2. `ask_issue.py --create` で、分け方の承認・対象・読み方を1つの Issue（チェックボックス）にまとめて聞く。番号とリンクを報告する
3. `read_answers.py --apply --wait` をバックグラウンドで実行して、回答が揃い、最後の「作業開始OK」が付くのを待つ（チャットでの合図は要らない）。揃うと `split.approved`・`target`・`reading.json` に写す（Issue は、作業が終わるまで閉じない）
4. 揃ったら続けて、重要箇所を選び、参考文献の候補を書き、`pipeline.py` で切り出し・ハイライト・リンク確認・コメント投稿まで進め、問題が無ければ `--close` で Issue を閉じる
5. 仕上がりと、人が見ること（未適用のマーカー、載せられなかったリンク）を報告する

「分け方を変えたい」が選ばれたとき（`read_answers.py` が終了コード 3）、回答が矛盾して揃わないときは、止めて人に聞き直す。

### チャットで進めるとき（従来の流れ）

| 人の合図 | AI がやること | 止まるところ |
|---|---|---|
| PDF を `inbox/` に置いて「作業開始」 | `output/<PDF名>/` に移し、分割案を作って一覧で見せる（ID・ページ範囲・ページ数・章名・合体箇所）。対象の提案も添える | 人の返事を待つ。ここでは `split.approved` も `target` も書かない |
| 範囲の指示（「1〜9章だけ」「全部」など） | **分け方の承認と対象の判断**として受け取る。`split.approved` と `target` に書き、確定したことを知らせる。続けて、対象の本文を読んで把握し、読み方の Issue（チェックボックス）を作る | Issue を作ったら、番号とリンクを報告して止まる。重要箇所の選定はまだ始めない |
| 「答えたよ」 | Issue の答えを `reading.json` に写し、重要箇所を選んで、`build_issue.py` で仕上げる。続けて章ごとに参考文献を集め、`check_links.py` で確認して、読み方の Issue にコメントする | 仕上がりと、投稿したコメントを報告する |

- 範囲の指示が曖昧で、分け方の変更（合体・分割・範囲の変更）を含むときは、承認として受け取らず、聞き直す
- 範囲の指示に含まれない記事は、`target` を `false` にする。これは人の指示にもとづく判断で、AI が勝手に決めるのではない
- Issue の書き方は [docs/workflow.md](docs/workflow.md) の「Issue で聞く」

## 守ること

人にも共通のルール（PDFをコミットしない、JSON が正、色とラベルの定義の置き場所、`target` と `split.approved` は人の判断、選定基準を読む）は [CONTRIBUTING.md](CONTRIBUTING.md)。ここには、AI が特に守ることを書く。

- **作業中に作る一時ファイル（本文の抜き出し、下書き、使い捨てのスクリプトなど）は、リポジトリ直下の `work-gai/` に作る**。`work-gai/` の中身は `.gitignore` 済みでコミットしない（フォルダ自体は `.gitkeep` で残してある）。成果物（`articles.json`、`highlights/`、`references/`、`reading.json`）と、ツールの本体（`app/`、`docs/`）以外を、ほかの場所に置かない
- 元PDF（作業フォルダ直下の、名前に `_` を含まないPDF。`inbox/` に置かれたPDFも）は書き換えない。出力は必ずコピーに対して行う
- `articles.json` の `target` は、ユーザーに聞かずに変えない
- **分け方（記事・章の単位とページ範囲）は、人の承認を得るまで、切り出しも重要箇所の選定も始めない**。承認は、チャット、または Issue の最後の「作業開始OK」で行う（変えたいときだけ「分け方を変えたい」を付けてもらう）。流れは [docs/workflow.md](docs/workflow.md) の「書籍を取り込む手順」。分割案はID・ページ範囲・ページ数・章名・合体箇所を一覧にして見せる
- `split.approved` は、ユーザーが承認する前に書かない・勝手に変えない。Issue の「作業開始OK」が付いたあとは `read_answers.py` が写す。`plan_issue.py` は書き換えない
- Issue でチェックを付けてよいのは、「2. 対象」の★だけ（人の指示。人が外せる）。ほかの項目（目的・重点・色・作業開始OK）は、AI が埋めない。「← 推奨」は提案で、答えにはしない
- 書籍のPDFは `inbox/` に置かれる。ユーザーに聞かずに、PDF名（拡張子なし）のフォルダを `output/` の下に作ってPDFを移し、そこで作業する。移すだけで中身は書き換えない
- 書籍の分割案を作るときは `plan_issue.py --unit book --auto-merge` で、30ページ未満の章を隣の章とまとめる（基準は [docs/workflow.md](docs/workflow.md) の「書籍を取り込む手順」）。前書き・はじめに・おわりに・索引・Appendix・奥付・部の扉など、本編の章ではないものは、省く（`target` を `false` にする）ことを提案してよい。決めるのは人で、`target` は人の返事を受けてから書く
- **重要箇所を選ぶ前に、対象の本文を読んだうえで、読み方（目的・重点にする章・使う色）を選択式でユーザーに聞く**（チャットの選択式、またはスマホで答えられる GitHub Issue のチェックボックス）。答えは `reading.json` に残す。ユーザーに代わって答えない。流れは [docs/workflow.md](docs/workflow.md) の「読み方を確認する」
- 参考文献は、`check_links.py` で `ok` になったものだけを載せる。404・ログインが必要なページ・取得できないページは載せない。ボット対策の回避（CAPTCHAなど）はしない。実ブラウザ（Claude in Chrome）で開けたものだけ、`verified_by: "browser"` を付けて `ok` にしてよい。手順は [docs/workflow.md](docs/workflow.md) の「参考文献を集める」
- 号や書籍を処理したら、`docs/records.md` の実績の表に行を足す
- コミット・プッシュは、変更がまとまったら行ってよい。`main` への直接のコミット・プッシュも、ユーザーに聞かずに行ってよい（PDF はコミットしない）

## 開発

コマンド（`app/` で実行）、テスト、コミットのルールは [CONTRIBUTING.md](CONTRIBUTING.md)。変更したら `uv run pytest` と `uv run ruff check .` を通す。

- 返答・コメント・コミットメッセージは日本語で書く

## 全体像

`app/` の各スクリプトは単体でも動くが、`build_issue.py` が次の順につなぐ。依存は `mark_pdf.py`（PDFを開く・注釈つきコピーを書く共通部品）が土台。

- `plan_issue.py`: PDFのしおりから記事（書籍は章）を割り出し、`articles.json` に一覧と判断（`target`、`split`）を残す
- `split_pdf.py`: `articles.json` の範囲でPDFを切り出す
- `apply_highlights.py`: `highlights/<ID>.json` の `text` をPDF本文から探してマーカーを付ける。`GROUPS` / `CATEGORIES`（色とラベル）の唯一の定義もここ
- `check_links.py`: 参考文献JSON（`references/<ID>.json`）のリンクを取得して確認する（404・ログイン必須・ボット扱いを除く）
- `post_references.py`: 確認できたリンクだけを、章ごとに Issue のコメントとして投稿する（`--sync` で、あれば書き換え・無ければ投稿）
- `ask_issue.py` / `read_answers.py`: 分け方の承認・対象・読み方を1つの Issue で聞き、チェックを `articles.json` と `reading.json` に写す
- `web.py`（リポジトリ直下の `作業開始.bat` から起動）: ブラウザからの PDF アップロード（`inbox/` に保存）と、状況表示のローカル画面。取り込みの開始に `start.py` を使う（127.0.0.1 のみ）
- `start.py`: `inbox/` の PDF を移し、分割案と質問の Issue まで進め、回答待ちの見張り（`watch.py`）を別ウィンドウで起動する（ローカル限定）
- `watch.py`: 「作業開始OK」を待って反映し、許可を絞った Claude（`claude -p`）を起動して続きを進める（ローカル限定）
- `pipeline.py`: `build_issue.py` → `check_links.py` → `post_references.py --sync` を続けて行う

`mark_pdf.py` を単体で動かす「Issueのコメントから付ける」使い方は、`build_issue.py` の流れには含まれない。

## 実際に詰まった点

- しおりが無いPDF（Webページを保存したブログ記事など）は `--unit book` が失敗する。`--ranges FIRST-LAST:章名` で作る。1本の記事なら `1-<最終ページ>:<名前>` の1つだけでよい
- 英語PDFの `text` は、改行をまたぐ文でも空白でつないで書けば一致する。一致しない行は `apply_highlights.py ... --dry-run` で `NG` と出る。原因はページ番号違いが多い
- `text` が別のページにあっても `build_issue.py` は止まらず「未適用 N件」と出るだけ。「N/N件」になるまで直す
