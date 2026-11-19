# 画面デザインの参考リンク

画面（`app/web.py` / `app/web_pages.py`）の見た目を考えるときに参照するもの。**色は [tokens.json](tokens.json) に沿う**。ここにあるのは、配色以外（レイアウト・余白・文字・部品の作り）の参考。

読めるかどうかは、2026-11-18 に確かめた結果。JavaScript で描くページは、ページを取得するだけでは中身が取れないので、実ブラウザ（Claude in Chrome）で開くか、公開されているソースを読む。

## 主に参照する（どちらかを土台にする）

| 名前 | URL | 読み方 | 参考にするところ |
|---|---|---|---|
| freee Vibes（freee のデザインシステム） | https://vibes.freee.co.jp/?path=/docs/doc-readme--docs | ページは Storybook（JavaScript）で、取得だけでは読めない。**ソースが公開されている**: [freee/vibes](https://github.com/freee/vibes)（Apache-2.0）。`src/constants/`（`Color.ts`・`Font.ts`・`Size.ts`）、`src/lv1/`（ボタン・フォーム・メッセージ・リストなどの部品） | 日本語の業務画面向け。情報が多い画面の余白・文字の大きさ・角丸・部品の作り、a11y の考え方。値をソースから直接読める |
| PayPay App Style Guide | https://developer.paypay.ne.jp/app-styleguide | 取得だけでは読めない。実ブラウザで開けば読める。Global Rule（色・アイコン・レイアウト・影・形・文字など）と Component（ボタン・カード・フォーム・タブ・トーストなど）のページに分かれる | スマホアプリ向け。方針は「共感・シンプル・一貫性・ハッピー」。部品の使い分け |
| PayPay for Developers（ドキュメント） | https://developer.paypay.ne.jp/products/docs | 取得だけでは読めない。実ブラウザで開けば読める | 左側にアイコン付きのメニューを常に出し、薄い灰色の背景に白いカードを並べるレイアウト |

## 補助的に参照する

| 名前 | URL | 読み方 | 参考にするところ |
|---|---|---|---|
| Visa Product Design System | https://design.visa.com/welcome/ | 取得だけでは読めない。実ブラウザで開けば読める | 部品の振る舞いや a11y の書き方を、個別のページから拾う |
| Stitch（Google Labs の紹介記事） | https://developers.googleblog.com/ja/stitch-a-new-way-to-design-uis/ | 読める。ただし資料ではなく、プロンプトやスクリーンショットから UI とコードを作る道具の紹介 | 人が Stitch で見本を作り、そのスクリーンショットやコードを渡せば、それに合わせて実装できる（Google へのログインが要るので、AI は操作しない） |
| Google Design の UI の記事 | https://design.google/tags/ui | 読める。記事の一覧で、具体的な数値は無い | 考え方の読み物。数値が要るときは Material Design 3 の仕様を見る |
