# 全体の流れ

雑誌・書籍のPDFから、読みたい記事（書籍は章）だけを切り出し、重要箇所に3色のマーカーを付けるまでの流れ。手順の細部は [workflow.md](workflow.md)。

人の作業は「PDF を置く」と「Issue にチェックを付ける」の2つだけ。残りはスクリプトと AI（Claude）が進める。

## 1. 作業の流れ（誰が何をするか）

```mermaid
flowchart TD
    subgraph H1["人"]
        A["PDF を inbox/ に置く<br/>（作業開始.bat からアップロードでもよい）"]
    end

    subgraph S1["取り込み（start.py が Claude を起動して進める）"]
        B["output/&lt;PDF名&gt;/ に PDF を移す"]
        C["分割案を作る<br/>plan_issue.py → articles.json"]
        D["対象の本文を読む（Claude）"]
        E["質問の Issue を1つ作る<br/>ask_issue.py"]
    end

    subgraph H2["人（スマホでも可）"]
        F["Issue にチェックを付ける<br/>・対象（★は初期チェック済み）<br/>・目的 / 重点 / 使う色<br/>・最後に「作業開始OK」"]
    end

    subgraph S2["回答の反映（watch.py → read_answers.py）"]
        G{"回答が揃った？<br/>2分ごとに確認"}
        H["articles.json（split.approved・target）<br/>と reading.json に写す"]
    end

    subgraph S3["重要箇所の選定と仕上げ（Claude → pipeline.py）"]
        I["重要箇所を選ぶ<br/>highlights/&lt;ID&gt;.json"]
        J["参考文献の候補を書く<br/>references/&lt;ID&gt;.json"]
        K["build_issue.py<br/>切り出し + マーカー"]
        L["check_links.py<br/>リンクを実際に取得して確認"]
        M["post_references.py<br/>確認できたものだけ Issue にコメント"]
        N{"未適用のマーカーや<br/>投稿の失敗がない？"}
        O["Issue を閉じる"]
    end

    P[("成果物<br/>分割/*.pdf<br/>マーカー付き/*.pdf")]
    Q["人が確認する<br/>未適用のマーカー・載せられなかったリンク"]

    A --> B --> C --> D --> E --> F --> G
    G -- "まだ" --> G
    G -- "「分け方を変えたい」" --> C
    G -- "揃った" --> H --> I --> J --> K --> L --> M --> N
    N -- "はい" --> O
    N -- "いいえ" --> Q
    O --> Q
    K --> P
```

## 2. データの流れ（何が正で、何が作り直せるか）

`output/<PDF名>/` の中の JSON が正。PDF は JSON から作り直せる生成物。

```mermaid
flowchart LR
    SRC["元PDF<br/>（書き換えない）"]
    ART["articles.json<br/>記事の一覧・target・split.approved"]
    READ["reading.json<br/>目的・重点・使う色"]
    HL["highlights/&lt;ID&gt;.json<br/>重要箇所の引用"]
    REF["references/&lt;ID&gt;.json<br/>参考リンク + 確認結果"]
    SPLIT["分割/&lt;名前&gt;.pdf"]
    MARK["マーカー付き/&lt;名前&gt;.pdf<br/>★ 読むのはこれ"]
    ISSUE["GitHub Issue<br/>質問 / 参考文献のコメント"]

    SRC -- "plan_issue.py" --> ART
    ART -- "ask_issue.py" --> ISSUE
    ISSUE -- "read_answers.py" --> ART
    ISSUE -- "read_answers.py" --> READ
    READ -. "選び方の前提" .-> HL
    ART -- "split_pdf.py" --> SPLIT
    SRC -- "split_pdf.py" --> SPLIT
    SPLIT -- "apply_highlights.py" --> MARK
    HL -- "apply_highlights.py" --> MARK
    REF -- "check_links.py" --> REF
    REF -- "post_references.py" --> ISSUE
```

## 3. スクリプトのつながり（`app/`）

実線は `import`（コードから呼ぶ）、点線は別のプロセスとして起動する関係。`mark_pdf.py`（PDF を開く・注釈つきコピーを書く共通部品）が土台。

```mermaid
flowchart TD
    BAT["作業開始.bat"] -.-> WEB["web.py<br/>ブラウザの画面"]
    WEB --> START["start.py<br/>取り込みを始める"]
    START -. "claude -p" .-> PLANAI["Claude<br/>分割案・本文の把握・質問の Issue"]
    PLANAI -. "実行" .-> PLAN["plan_issue.py<br/>分割案"]
    PLANAI -. "実行" .-> ASK["ask_issue.py<br/>質問の Issue"]
    START -. "別ウィンドウ" .-> WATCH["watch.py<br/>回答待ちの見張り"]
    WATCH --> READ["read_answers.py<br/>回答を写す"]
    READ --> ASK
    ASK --> PLAN
    WATCH -. "claude -p" .-> SELECT["Claude<br/>重要箇所の選定・参考文献の候補"]
    SELECT -. "実行" .-> PIPE["pipeline.py"]

    PIPE --> BUILD["build_issue.py"]
    PIPE --> CHECK["check_links.py"]
    PIPE --> POST["post_references.py"]

    BUILD --> SPLIT["split_pdf.py"]
    BUILD --> APPLY["apply_highlights.py<br/>色とラベルの唯一の定義"]

    PLAN --> MARK["mark_pdf.py<br/>共通部品"]
    SPLIT --> MARK
    APPLY --> MARK
    BUILD --> MARK
```

## 色の意味

| 色 | 意味 | ラベル |
|---|---|---|
| 青 | 知る | `definition` 定義 / `evidence` 根拠・数値 |
| 緑 | 方針・実践 | `principle` 原則・主張 / `practice` 実践 |
| 赤 | 注意 | `warning` 注意・限界 |

定義は `app/apply_highlights.py` の `GROUPS` / `CATEGORIES`。
