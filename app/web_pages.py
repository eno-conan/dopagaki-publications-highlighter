"""ブラウザ画面の各ページ（メニュー・新規取り込み・作業状況・成果物）と、共通の枠（ヘッダー・メニュー）。

`web.py` が配信する。状況の判定やアップロードは `web.py`、見た目は、ここ。

- 色は `design/tokens.json` のとおり（CSS の :root にまとめた）。トークンに無い「注意（あなたの番）」「停止」の色と、
  ダークモードの色は、ここで足した（どれも WCAG AA のコントラストを満たす値）
- 色以外（文字の大きさ・余白・角丸・影・部品の作り）は、freee のデザインシステム Vibes に合わせた
  （本文 14px・行の高さ 1.5、余白 4/8/16/24px、ボタンの高さ 36px・角丸 8px、カードの角丸 12px。参考: design/references.md）
"""

# ruff: noqa: E501  （埋め込みの HTML / CSS / JS は、行が長くなる）
from __future__ import annotations

import json
from html import escape

from apply_highlights import GROUPS

PRODUCT = "dopagaki-publications-highlighter"  # プロダクト名（リポジトリ名）

CSS = """
:root{
/* 色: design/tokens.json */
--canvas:#F2F0EB;--surface:#FFFFFF;--section:#EDEBE9;--subtle:#F4F4F4;--inverse:#1E3932;--on-inverse:#FFFFFF;
--text:#1E3932;--text-2:#5F5F5F;--border:#D8D8D8;--border-subtle:#E0E0E0;
--primary:#00754A;--primary-pressed:#006241;--on-primary:#FFFFFF;--green-light:#D4E9E2;--link:#00754A;
/* トークンに無い色（AA を満たす値を足した） */
--attn:#8A5300;--attn-bg:#FCEFD9;--attn-line:#B87400;--danger:#B3261E;--danger-bg:#FBE9E7;--input-line:#767676;
/* 色以外: Vibes */
--s1:4px;--s2:8px;--s3:16px;--s4:24px;--s5:32px;--s6:48px;
--r-base:8px;--r-card:12px;--control:36px;
--shadow-card:0 0 1rem rgba(0,0,0,.1),0 .125rem .25rem rgba(0,0,0,.2);
--shadow-float:0 0 1.5rem rgba(0,0,0,.1);
--ring-gap:#FFFFFF;--hero-2:#D4E9E2;--hero-line:#2B5148;
--font:-apple-system,BlinkMacSystemFont,"Helvetica Neue","Hiragino Kaku Gothic ProN","Noto Sans JP",Meiryo,"Yu Gothic UI",sans-serif;
color-scheme:light}
@media (prefers-color-scheme:dark){:root{
--canvas:#10201C;--surface:#1E3932;--section:#2B5148;--subtle:#173029;--inverse:#D4E9E2;--on-inverse:#1E3932;
--text:#F2F0EB;--text-2:#C2CFCB;--border:#3D635A;--border-subtle:#2B5148;
--primary:#D4E9E2;--primary-pressed:#B5D6CA;--on-primary:#1E3932;--green-light:#2B5148;--link:#9ED9C0;
--attn:#FFD08A;--attn-bg:#3D3016;--attn-line:#E0A740;--danger:#FFB4AB;--danger-bg:#4A221E;--input-line:#9DB3AD;
--hero-2:#2B5148;--hero-line:#B5D6CA;--shadow-card:0 0 0 1px #2B5148;--shadow-float:0 0 1.5rem rgba(0,0,0,.4);--ring-gap:#10201C;color-scheme:dark}}

*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--canvas);color:var(--text);font:14px/1.5 var(--font);font-variant-numeric:tabular-nums}
h1,h2,h3,h4,h5,p{margin:0}
a{color:var(--link)}
/* フォーカス: Vibes と同じ三重の輪（内側に白、色の輪、外側に白） */
:focus{outline:none}
:focus-visible{box-shadow:0 0 0 1px var(--ring-gap),0 0 0 3px var(--link),0 0 0 4px var(--ring-gap);border-radius:4px}
code{font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;font-size:12px;background:var(--section);padding:1px 4px;border-radius:4px}
.sr-only{position:absolute!important;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
.skip{position:absolute;left:var(--s3);top:-60px;z-index:50;background:var(--surface);color:var(--link);padding:var(--s2) var(--s3);border-radius:var(--r-base);box-shadow:var(--shadow-float);font-weight:700}
.skip:focus{top:var(--s2)}
svg.i{width:20px;height:20px;flex:none;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}

/* ヘッダーとページのタブ */
.top{position:sticky;top:0;z-index:10;background:var(--surface);border-bottom:1px solid var(--border)}
.top-in{max-width:1120px;margin:0 auto;display:flex;align-items:stretch;gap:var(--s3);height:56px;padding:0 var(--s4)}
.brand{display:flex;align-items:center;min-width:0;font-weight:700;font-size:16px;color:var(--text);text-decoration:none;margin-right:auto}
.brand span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.iconbtn{align-self:center;display:inline-flex;align-items:center;justify-content:center;width:var(--control);height:var(--control);border-radius:var(--r-base);border:0;background:transparent;color:var(--text);cursor:pointer}
.iconbtn:hover{background:var(--section)}
.tabs{display:none;align-items:stretch}
.tabs a{display:flex;align-items:center;padding:0 var(--s3);color:var(--text-2);text-decoration:none;font-weight:700;border-bottom:3px solid transparent;margin-bottom:-1px}
.tabs a:hover{color:var(--text);background:var(--subtle)}
.tabs a[aria-current=page]{color:var(--text);border-bottom-color:var(--link)}
@media (min-width:768px){.tabs{display:flex} #burger{display:none}}
@media (max-width:767px){.top-in{padding:0 var(--s3)}}
#scrim{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:20}
#drawer{position:fixed;top:0;left:0;bottom:0;width:280px;max-width:84vw;background:var(--surface);z-index:30;padding:var(--s2) var(--s2) var(--s3);
display:flex;flex-direction:column;transform:translateX(-100%);transition:transform .2s ease;visibility:hidden;box-shadow:var(--shadow-float)}
body.open #drawer{transform:none;visibility:visible}
.dhead{display:flex;align-items:center;justify-content:space-between;height:48px;padding:0 0 0 var(--s2);border-bottom:1px solid var(--border-subtle);margin-bottom:var(--s2)}
.dhead .title{font-weight:700}
#drawer a{display:flex;align-items:center;min-height:44px;padding:0 var(--s3);color:var(--text);text-decoration:none;border-radius:var(--r-base);font-weight:700}
#drawer a:hover{background:var(--subtle)}
#drawer a[aria-current=page]{background:var(--green-light)}

/* ページの骨組み（Vibes: PageTitle 24px / SectionTitle 16px） */
main{display:block;max-width:1120px;margin:0 auto;padding:var(--s4) var(--s4) var(--s6)}
@media (max-width:767px){main{padding:var(--s3) var(--s3) var(--s5)}}
.phead{margin-bottom:var(--s4)}
.phead h1{font-size:24px;line-height:1.5}
.phead p{color:var(--text-2);margin-top:var(--s1)}
.section-title{font-size:16px;margin:var(--s5) 0 var(--s2)}
.cardbox{background:var(--surface);border-radius:var(--r-card);box-shadow:var(--shadow-card);padding:var(--s4)}
@media (max-width:767px){.cardbox,.book{padding:var(--s3)}}
.empty{color:var(--text-2);background:var(--surface);border-radius:var(--r-card);box-shadow:var(--shadow-card);padding:var(--s4);text-align:center}

/* ボタン（Vibes: 高さ 36px・角丸 8px・左右 16px） */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:var(--s1);height:var(--control);padding:0 var(--s3);border-radius:var(--r-base);
font:inherit;font-weight:700;white-space:nowrap;cursor:pointer;text-decoration:none;background:var(--surface);color:var(--text);border:1px solid var(--border);transition:background-color .2s,border-color .2s,color .2s}
.btn:hover{background:var(--green-light);border-color:var(--primary-pressed)}
.btn.primary{background:var(--primary);color:var(--on-primary);border-color:var(--primary)}
.btn.primary:hover{background:var(--primary-pressed);border-color:var(--primary-pressed)}
.btn.danger{color:var(--danger);border-color:var(--danger)}
.btn.danger:hover{background:var(--danger-bg)}
.btn.danger.armed{background:var(--danger);color:var(--surface)}
.btn.small{height:24px;padding:0 var(--s2);font-size:12px}
.btn:disabled,.btn[aria-disabled=true]{opacity:.5;cursor:not-allowed}
.row{display:flex;flex-wrap:wrap;gap:var(--s2);align-items:center;margin-top:var(--s3)}
.hint{color:var(--text-2);font-size:12px}

/* 結果の表示（role=status） */
.msg{white-space:pre-wrap;margin-top:var(--s2)}
.msg:empty{display:none}
.msg.ok{color:var(--link);font-weight:700} .msg.err{color:var(--danger);font-weight:700} .msg.info{color:var(--text-2)}

/* メッセージ欄（Vibes: MessageBlock。枠と薄い背景、角丸 8px、余白 16px） */
.mblock{display:flex;gap:var(--s2);align-items:flex-start;margin-top:var(--s3);padding:var(--s3);border-radius:var(--r-base);border:1px solid var(--border);background:var(--subtle)}
.mblock.notice{border-color:var(--attn-line);background:var(--attn-bg);color:var(--attn);font-weight:700}
.mblock.notice svg{color:var(--attn)}
.mblock .lbl{display:block;font-size:12px;color:var(--text-2)}
.mblock .v{display:block;font-weight:700;word-break:break-all}

/* メニューのカード */
.tiles{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:var(--s3)}
.tile{display:flex;flex-direction:column;gap:var(--s1);height:100%;padding:var(--s4);text-decoration:none;color:var(--text);background:var(--surface);border-radius:var(--r-card);box-shadow:var(--shadow-card);transition:background-color .2s}
.tile:hover{background:var(--green-light)}
.tile .t{font-weight:700;font-size:16px;color:var(--link)}
.tile .count{font-size:24px;font-weight:700}
.tile .count small{font-size:14px;margin-left:2px}
.tile .d{color:var(--text-2)}

/* 本・号のカード */
.book{background:var(--surface);border-radius:var(--r-card);box-shadow:var(--shadow-card);padding:var(--s4);margin:0 0 var(--s3)}
.bhead{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s2) var(--s3)}
.bname{font-size:16px;margin-right:auto;word-break:break-word}
/* 状況のタグ（Vibes: TagBox。高さ 24px） */
.tag{display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 10px;border-radius:12px;font-size:12px;font-weight:700;border:1px solid var(--tline);background:var(--tbg);color:var(--tfg)}
.tag .dot{width:8px;height:8px;border-radius:50%;background:currentColor}
.tone-busy{--tbg:var(--green-light);--tfg:var(--text);--tline:var(--green-light);--nbg:var(--primary);--nfg:var(--on-primary)}
.tone-ask{--tbg:var(--attn-bg);--tfg:var(--attn);--tline:var(--attn-line);--nbg:var(--attn);--nfg:var(--surface)}
.tone-done{--tbg:var(--inverse);--tfg:var(--on-inverse);--tline:var(--inverse);--nbg:var(--primary);--nfg:var(--on-primary)}
.tone-wait,.tone-idle{--tbg:var(--section);--tfg:var(--text-2);--tline:var(--section);--nbg:var(--text-2);--nfg:var(--surface)}
.tone-halt{--tbg:var(--danger-bg);--tfg:var(--danger);--tline:var(--danger);--nbg:var(--danger);--nfg:var(--surface)}
.detail{margin-top:var(--s3)}
.links{margin-top:var(--s3);padding-top:var(--s3);border-top:1px solid var(--border-subtle);color:var(--text-2)}

/* 工程のステッパー（Vibes: Stepper。丸い番号を線でつなぐ） */
.stepper{list-style:none;margin:var(--s3) 0 0;padding:0;display:grid;grid-template-columns:repeat(4,1fr);max-width:560px}
.stepper li{position:relative;display:flex;flex-direction:column;align-items:center;gap:var(--s1);text-align:center;font-size:12px;color:var(--text-2)}
.stepper li:not(:first-child)::before{content:"";position:absolute;top:11px;right:calc(50% + 16px);width:calc(100% - 32px);height:2px;background:var(--border)}
.stepper li.done:not(:first-child)::before,.stepper li.now:not(:first-child)::before{background:var(--link)}
.stepper .n{display:flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;font-weight:700;border:2px solid var(--border);background:var(--surface);color:var(--text-2)}
.stepper .n svg.i{width:14px;height:14px;stroke-width:3}
.stepper li.done .n{border-color:var(--link);color:var(--link)}
.stepper li.done{color:var(--text)}
.stepper li.now .n{border-color:var(--nbg);background:var(--nbg);color:var(--nfg)}
.stepper li.now{color:var(--text);font-weight:700}

/* 動き（動きを減らす設定では止める） */
.spin{display:inline-block;width:10px;height:10px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:spin .9s linear infinite}
.bar{height:2px;margin-top:var(--s3);overflow:hidden;background:var(--green-light)}
.bar::after{content:"";display:block;height:100%;width:30%;background:var(--link);animation:slide 1.4s ease-in-out infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes slide{0%{margin-left:-30%}100%{margin-left:100%}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}

/* 回答パネル（コメント → チェック → 作業開始OK → 保存） */
.pane{margin-top:var(--s4);padding-top:var(--s4);border-top:1px solid var(--border)}
.pane h3{font-size:14px;margin:0 0 var(--s2)}
.pane h3{margin-top:var(--s4)}
.pane .guide{margin-top:0}
.ghrow{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s2);margin-top:var(--s2);color:var(--text-2)}
.ask{margin-top:var(--s3);padding:var(--s3);border-radius:var(--r-base);border:1px solid var(--attn-line);background:var(--surface)}
.ask h3{margin-top:0}
.actions{margin-top:var(--s4);padding-top:var(--s3);border-top:1px solid var(--border-subtle);display:flex;flex-wrap:wrap;gap:var(--s2);align-items:center}
.actions .hint{flex-basis:100%}
.thread{list-style:none;margin:0 0 var(--s3);padding:0;display:flex;flex-direction:column;gap:var(--s2)}
.thread li{padding:var(--s2) var(--s3);border-radius:var(--r-base);white-space:pre-wrap;word-break:break-word;border:1px solid var(--border-subtle);background:var(--subtle)}
.thread li.claude{background:var(--attn-bg);border-color:var(--attn-line)}
.thread .w{display:block;font-size:12px;font-weight:700;color:var(--text-2);white-space:normal}
.thread li.claude .w{color:var(--attn)}
.thread li.none{border:0;background:none;padding:0;color:var(--text-2)}
.flabel{display:block;font-size:12px;font-weight:700;margin-top:var(--s2)}
textarea{display:block;width:100%;min-height:5em;margin-top:var(--s1);font:inherit;padding:var(--s2);border-radius:var(--r-base);border:1px solid var(--input-line);background:var(--surface);color:var(--text)}
.form{margin-top:var(--s2);border:1px solid var(--border-subtle);border-radius:var(--r-base);padding:0 var(--s3) var(--s2)}
.fgroup{font-size:14px;margin:0 calc(-1 * var(--s3)) var(--s1);padding:var(--s2) var(--s3);background:var(--subtle);border-top:1px solid var(--border-subtle)}
.form .fgroup:first-child{border-top:0;border-radius:var(--r-base) var(--r-base) 0 0}
.fsub{font-size:12px;color:var(--text-2);margin:var(--s2) 0 0}
.fchk{display:flex;gap:var(--s2);align-items:flex-start;padding:6px 0;cursor:pointer}
.fchk input{flex:none;width:16px;height:16px;margin:2px 0 0;accent-color:var(--link)}
.fchild{font-size:12px;color:var(--text-2);padding-left:24px}
.fchild::before{content:"・"}
.rec{display:inline-flex;align-items:center;height:20px;margin-left:var(--s1);padding:0 6px;border-radius:10px;font-size:12px;font-weight:700;color:var(--attn);border:1px solid var(--attn-line);background:var(--attn-bg)}

/* 新規取り込み */
.drop{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:120px;text-align:center;padding:var(--s4) var(--s3);border:1px dashed var(--input-line);border-radius:var(--r-base);cursor:pointer;background:var(--subtle);font-weight:700;color:var(--link)}
.drop:hover,.drop.over{background:var(--green-light);border-color:var(--primary-pressed)}
.drop:focus-within{box-shadow:0 0 0 1px var(--ring-gap),0 0 0 3px var(--link),0 0 0 4px var(--ring-gap)}
.drop .d{font-weight:400;color:var(--text-2);font-size:12px;margin-top:var(--s1)}
.warnbox{margin-top:var(--s3);padding:var(--s3);border-radius:var(--r-base);background:var(--attn-bg);border:1px solid var(--attn-line)}
.warnbox h2{font-size:14px;color:var(--attn)}
.warnbox p{white-space:pre-wrap;margin-top:var(--s2)}
/* 縦の手順（Vibes: VerticalSteps） */
.vsteps{list-style:none;margin:0;padding:0;counter-reset:s}
.vsteps li{counter-increment:s;display:grid;grid-template-columns:24px 1fr;column-gap:var(--s3);position:relative;padding-bottom:var(--s3)}
.vsteps li::before{content:counter(s);grid-row:1 / 3;display:flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;background:var(--section);color:var(--text);font-weight:700;font-size:12px;z-index:1}
.vsteps li:not(:last-child)::after{content:"";position:absolute;left:11px;top:24px;bottom:0;width:2px;background:var(--border)}
.vsteps .who{font-weight:700;line-height:24px}
.vsteps .d{color:var(--text)}

/* トップ（メニュー）の見出し。背景はトークンの inverse、名前の大きさはトークンの display（50px）を上限にする */
.hero{background:var(--inverse);color:var(--on-inverse);border-radius:var(--r-card);padding:var(--s5);margin-bottom:var(--s4)}
@media (max-width:767px){.hero{padding:var(--s4) var(--s3)}}
.hero .sub{color:var(--hero-2);font-weight:700}
.hero h1{font-size:clamp(28px,5.2vw,50px);line-height:1.15;letter-spacing:-0.01em;margin:var(--s2) 0 var(--s3);overflow-wrap:anywhere}
.hero .lead{font-size:16px;font-weight:700}
.hero dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:var(--s3) var(--s4);margin:var(--s4) 0 0;padding-top:var(--s4);border-top:1px solid var(--hero-line)}
.hero dt{font-size:12px;font-weight:700;color:var(--hero-2);margin-bottom:var(--s1)}
.hero dd{margin:0}
.legend{list-style:none;margin:var(--s4) 0 0;padding:0;display:flex;flex-wrap:wrap;gap:var(--s2) var(--s4)}
.legend li{display:flex;align-items:flex-start;gap:var(--s2)}
.legend mark{flex:none;white-space:nowrap;padding:0 var(--s2);border-radius:4px;color:#1E3932;font-weight:700}

/* フッター */
footer{max-width:1120px;margin:0 auto;padding:var(--s3) var(--s4) var(--s5);border-top:1px solid var(--border);color:var(--text-2);font-size:12px;display:flex;flex-wrap:wrap;gap:var(--s2) var(--s4);align-items:center;justify-content:space-between}
.nstate{display:inline-flex;align-items:center;gap:var(--s1)}
.nstate.on{color:var(--link);font-weight:700}
.nstate svg.i{width:16px;height:16px}

/* 強制カラー（Windows のハイコントラスト） */
@media (forced-colors:active){
.tag,.book,.tile,.btn,.cardbox,.mblock{border:1px solid CanvasText}
.stepper li.now .n{forced-color-adjust:none;background:Highlight;color:HighlightText}
:focus-visible{outline:2px solid Highlight}
}
"""

ICON_MENU = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>'
ICON_CLOSE = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>'

NAV = [
    ("/", "メニュー"),
    ("/new", "新規取り込み"),
    ("/progress", "作業状況"),
    ("/library", "成果物"),
]

JS_COMMON = """
const $=s=>document.querySelector(s), esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const ICON_CHECK='<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
const ICON_INFO='<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.01"/></svg>';
const ICON_ALERT='<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.5M12 17.5v.01"/></svg>';
const TONE={'取り込み待ち':'wait','分割案を作成中':'busy','回答待ち':'ask','作業中':'busy','PDF作成待ち':'wait','順番待ち':'wait','返事待ち':'ask','意図を読み取り中':'busy','未着手':'idle','中断':'halt','完了':'done'};
const GROUPS={
  new:['取り込み待ち','分割案を作成中','回答待ち','返事待ち','順番待ち','意図を読み取り中','作業中','中断'],
  progress:['取り込み待ち','分割案を作成中','回答待ち','返事待ち','順番待ち','意図を読み取り中','作業中','中断','PDF作成待ち','未着手'],
  library:['完了']};
// メニュー（狭い画面のドロワー）。閉じているあいだは操作できないようにし（inert）、開いたら中へ、閉じたらボタンへフォーカスを戻す
function setOpen(o){
  const d=$('#drawer'), b=$('#burger'), was=document.body.classList.contains('open');
  document.body.classList.toggle('open',o); b.setAttribute('aria-expanded',o);
  d.inert=!o; d.setAttribute('aria-hidden',!o); $('#scrim').hidden=!o;
  if(o) d.querySelector('a').focus(); else if(was) b.focus();
}
$('#burger').onclick=()=>setOpen(true);
$('#dclose').onclick=()=>setOpen(false);
$('#scrim').onclick=()=>setOpen(false);
document.addEventListener('keydown',e=>{
  if(!document.body.classList.contains('open')) return;
  if(e.key==='Escape') setOpen(false);
  if(e.key==='Tab'){  // 開いている間は、フォーカスをドロワーの中に閉じ込める
    const f=[...$('#drawer').querySelectorAll('a,button')], first=f[0], last=f[f.length-1];
    if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
    else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
  }
});
async function post(url,obj){  // 画面からの書き込み。合言葉（TOKEN）を付ける
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-Token':TOKEN},body:JSON.stringify(obj||{})});
  return r.json();
}
const md=t=>String(t).split('`').map((p,i)=>i%2?'<code>'+esc(p)+'</code>':esc(p)).join('').replace(' ← 推奨',' <span class="rec">推奨</span>');
const key=s=>'k'+[...String(s)].map(c=>c.codePointAt(0).toString(36)).join('-');  // 名前から、HTML の id に使える文字列
function say(el,kind,text){el.classList.remove('ok','err','info'); if(kind) el.classList.add(kind); el.textContent=text;}  // role=status の欄に、結果を出す（ほかのクラスは残す）
const ASK=['回答待ち','返事待ち','順番待ち','意図を読み取り中'];
// 工程のステッパー: 1 取り込み → 2 回答 → 3 作業 → 4 完了。いまの工程は aria-current="step"
const STEPS=['取り込み','回答','作業','完了'];
const STEP={'取り込み待ち':1,'分割案を作成中':1,'回答待ち':2,'返事待ち':2,'意図を読み取り中':2,'順番待ち':3,'作業中':3,'中断':3,'PDF作成待ち':3,'完了':4,'未着手':0};
function stepper(b){
  const cur=STEP[b.label]||0, fin=b.label==='完了';
  return `<ol class="stepper" aria-label="工程">${STEPS.map((s,i)=>{const n=i+1, st=fin||n<cur?'done':n===cur?'now':'todo';
    return `<li class="${st}"${st==='now'?' aria-current="step"':''}><span class="n" aria-hidden="true">${st==='done'?ICON_CHECK:n}</span><span>${s}${st==='done'?'<span class="sr-only">（済み）</span>':''}</span></li>`;}).join('')}</ol>`;
}
function card(b){
  const live=b.working&&b.label!=='順番待ち', tone=TONE[b.label]||'idle', ask=b.issue_url&&ASK.includes(b.label), id=key(b.name), n=esc(b.name);
  const act=ask?`<div class="answer" data-name="${n}" data-label="${esc(b.label)}" data-working="${b.working?1:''}" data-issue="${b.issue}" data-url="${esc(b.issue_url)}"></div>`
    :(b.issue_url&&b.label!=='完了'?`<p class="links"><a href="${esc(b.issue_url)}" target="_blank" rel="noopener">Issue #${b.issue}<span class="sr-only">（新しいタブ）</span></a>（進捗のコメントが付きます）</p>`:'');
  const ctl=b.stoppable?`<div class="row"><button class="btn danger" data-fk="stop:${n}" data-name="${n}" onclick="stopWork(this)">中断</button></div>`
    :(b.label==='中断'?`<div class="row"><button class="btn primary" data-fk="resume:${n}" data-name="${n}" onclick="resumeWork(this)">再開</button></div>`:'');
  const s=SMSG[b.name];
  return `<article class="book tone-${tone}" aria-labelledby="${id}">
    <div class="bhead"><h2 class="bname" id="${id}">${n}</h2><span class="tag">${live?'<span class="spin" aria-hidden="true"></span>':'<span class="dot" aria-hidden="true"></span>'}${esc(b.label)}</span></div>
    ${stepper(b)}<p class="detail">${esc(b.detail)}</p>${b.notice?`<div class="mblock notice">${ICON_ALERT}<p>${esc(b.notice)}</p></div>`:''}
    ${b.activity?`<div class="mblock">${ICON_INFO}<p><span class="lbl">Claude がいま</span><span class="v">${esc(b.activity)}</span></p></div>`:''}${live?'<div class="bar" aria-hidden="true"></div>':''}
    ${ctl}<p class="msg ${s?s.kind:''}" role="status">${s?esc(s.text):''}</p>${act}</article>`;
}
const SMSG={};  // 本・号ごとの「中断」「再開」の結果
async function stopWork(btn){  // 1回目は確認に変えるだけ。4秒以内にもう一度押すと中断する
  if(!btn.dataset.armed){btn.dataset.armed='1';btn.classList.add('armed');btn.textContent='もう一度押すと中断します';
    setTimeout(()=>{if(btn.isConnected){delete btn.dataset.armed;btn.classList.remove('armed');btn.textContent='中断';}},4000);return;}
  btn.disabled=true; btn.textContent='止めています…';
  await control('/api/stop',btn.dataset.name);
}
async function resumeWork(btn){btn.disabled=true; await control('/api/resume',btn.dataset.name);}
async function control(url,name){
  try{const j=await post(url,{name}); SMSG[name]=j.ok?{kind:'ok',text:j.message||''}:{kind:'err',text:(j.problems||[j.error||'失敗しました']).join('\\n')};}
  catch(e){SMSG[name]={kind:'err',text:'通信に失敗しました: '+e};}
  if(typeof load==='function') load();
}
// 回答パネル。5秒ごとの描き直しで入力が消えないよう、カードの外で持ち、描き直したあとに差し込む
// 並び: いまの状態の説明と GitHub の行 → （質問があるときだけ）Claude からの質問と返事 → 回答 → 補足 → 確定 / 下書き保存
const GUIDE={
  '回答待ち':'答え終わったら、いちばん下の「回答を確定して作業を始める」を押してください。押すまでは、チェックを変えても、下書きを保存しても、作業は始まりません。',
  '返事待ち':'Claude が確認したいことを書きました。返事を送ると、Claude が読み直します（作業はまだ始まりません）。回答を直したいときは、下の回答を変えてから確定してください。',
  '意図を読み取り中':'Claude が「分け方を変えたい」とコメントを読んでいます。終わるまで、回答は変えられません。',
  '順番待ち':'回答は受け取りました。ほかの本・号の作業が終わると、自動で始まります。'};
const PANELS={};
function panel(name){
  if(PANELS[name]) return PANELS[name];
  const k=key(name), el=document.createElement('section'); el.className='pane'; el.dataset.name=name; el.setAttribute('aria-label','回答');
  el.innerHTML=`<div class="mblock guide">${ICON_INFO}<p class="gtext"></p></div>
    <div class="ghrow"><span>GitHub の <a class="ghlink" target="_blank" rel="noopener"></a> で答えた場合は</span><button class="btn small gh">GitHub の回答を読み込む</button></div>
    <section class="ask" hidden aria-labelledby="${k}-q"><h3 id="${k}-q">Claude からの質問</h3><ol class="thread qthread"></ol>
      <label class="flabel" for="${k}-ans">返事</label><textarea class="ans" id="${k}-ans" rows="3" maxlength="4000"></textarea>
      <div class="row"><button class="btn primary reply">返事を送る（Claude が読み直します）</button></div></section>
    <h3>回答</h3><p class="hint">分け方と対象、読み方を選びます。</p>
    <div class="form"><p class="hint">読み込み中…</p></div>
    <div class="past" hidden><h3 id="${k}-p">これまでのコメント</h3><ol class="thread nthread" aria-labelledby="${k}-p"></ol></div>
    <label class="flabel" for="${k}-note">補足（任意）</label>
    <textarea class="note" id="${k}-note" rows="3" maxlength="4000" aria-describedby="${k}-nh"></textarea>
    <p class="hint" id="${k}-nh">例: 2章の設定例は読み飛ばす。確定か下書き保存のときに、Issue にコメントとして載り、重要箇所を選ぶときの参考になります。</p>
    <div class="actions"><button class="btn primary go">回答を確定して作業を始める</button><button class="btn draft">下書き保存（作業は始めない）</button>
      <p class="hint">確定すると、Claude が重要箇所の選定から、マーカー付きPDFの作成までを進めます（時間がかかります）。回答が足りないときは、始めずに知らせます。</p></div>
    <p class="msg pmsg" role="status"></p>`;
  el.querySelector('.go').onclick=()=>saveForm(el,true);
  el.querySelector('.draft').onclick=()=>saveForm(el,false);
  el.querySelector('.reply').onclick=()=>sendReply(el);
  el.querySelector('.gh').onclick=()=>syncGitHub(el);
  PANELS[name]=el; return el;
}
const pmsg=(el,kind,text)=>say(el.querySelector('.pmsg'),kind,text);
const comment=c=>`<li class="${c.who}"><span class="w">${c.who==='claude'?'Claude':'あなた'}・<time>${esc(c.created_at.replace('T',' ').slice(0,16))}</time></span>${esc(c.body)}</li>`;
async function loadPanel(el){
  try{
    const j=await (await fetch('/api/issue?name='+encodeURIComponent(el.dataset.name))).json();
    if(!j.ok){pmsg(el,'err',j.error||'Issue を読めませんでした');return;}
    el.dataset.version=j.version; el.dataset.started=j.started?'1':'';
    el.querySelector('.form').innerHTML=j.form.map(it=>it.kind==='check'
      ?`<label class="fchk"><input type="checkbox" data-line="${it.line}" data-orig="${it.checked?1:''}"${it.checked?' checked':''}><span>${md(it.text)}</span></label>`
      :it.kind==='h2'?`<h4 class="fgroup">${md(it.text)}</h4>`:it.kind==='h3'?`<h5 class="fsub">${md(it.text)}</h5>`
      :`<div class="fchild">${md(it.text)}</div>`).join('')||'<p class="hint">チェックボックスが見つかりません</p>';
    el.querySelectorAll('.form input').forEach((cb,i)=>cb.dataset.text=j.form.filter(x=>x.kind==='check')[i].text);
    el.querySelector('.qthread').innerHTML=j.thread.map(comment).join('');
    el.querySelector('.nthread').innerHTML=j.thread.map(comment).join('');
    el.querySelector('.past').dataset.has=j.thread.length?'1':'';
    arrange(el);
  }catch(e){pmsg(el,'err','Issue を読めませんでした: '+e);}
}
function arrange(el){  // 状態に合わせて、説明・質問の欄・ボタンの使える・使えないを切り替える
  const label=el.dataset.label, busy=el.dataset.working==='1', asking=label==='返事待ち';
  el.querySelector('.gtext').textContent=(GUIDE[label]||'')+(el.dataset.started&&!busy?' GitHub で「作業開始OK」が付いているので、回答が揃えば、作業が始まります。':'');
  el.querySelector('.ask').hidden=!asking;
  el.querySelector('.past').hidden=asking||!el.querySelector('.past').dataset.has;
  el.querySelectorAll('.go,.draft,.reply,.gh').forEach(b=>b.disabled=busy);
  el.querySelectorAll('.form input').forEach(cb=>cb.disabled=busy);
}
function showResult(el,j,okText){
  if(j.ok) pmsg(el,'ok',j.message||okText);
  else pmsg(el,'err',(j.problems||[j.error||'失敗しました']).map((p,i)=>i||j.conflict?'・'+p:p).join('\\n'));
}
async function postNote(el,ta){  // 書きかけの補足や返事を、Issue にコメントする。失敗したら false
  if(!ta.value.trim()) return true;
  pmsg(el,'info','コメントを Issue に送っています…');
  const c=await post('/api/comment',{name:el.dataset.name,body:ta.value});
  if(!c.posted){showResult(el,c,''); return false;}
  ta.value=''; return c;
}
async function saveForm(el,go){
  const btns=el.querySelectorAll('.go,.draft'); btns.forEach(b=>b.disabled=true);
  try{
    if(!await postNote(el,el.querySelector('.note'))) return;
    pmsg(el,'info',go?'回答を確かめています…':'下書きを保存しています…');
    const changes=[...el.querySelectorAll('.form input')].filter(cb=>cb.checked!==!!cb.dataset.orig).map(cb=>({line:+cb.dataset.line,text:cb.dataset.text,checked:cb.checked}));
    const j=await post('/api/answers',{name:el.dataset.name,version:el.dataset.version,changes,start:go});
    await loadPanel(el); showResult(el,j,go?'作業を始めました':'下書きを保存しました'); if(typeof load==='function') load();
  }catch(e){pmsg(el,'err','通信に失敗しました: '+e);}
  finally{arrange(el);}
}
async function sendReply(el){
  const ta=el.querySelector('.ans');
  if(!ta.value.trim()){pmsg(el,'err','返事が空です');ta.focus();return;}
  el.querySelector('.reply').disabled=true;
  try{const j=await postNote(el,ta); if(j){await loadPanel(el); showResult(el,j,'返事を送りました'); if(typeof load==='function') load();}}
  catch(e){pmsg(el,'err','通信に失敗しました: '+e);}
  finally{arrange(el);}
}
async function syncGitHub(el){  // GitHub の Issue で答えたとき: 読み込み直して、揃っていれば作業を始める
  el.querySelector('.gh').disabled=true; pmsg(el,'info','GitHub の回答を読み込んでいます…');
  try{const j=await post('/answered',{name:el.dataset.name}); await loadPanel(el);
    if(j.ok) pmsg(el,'ok',j.message); else pmsg(el,'err','GitHub の回答を読み込みました。まだ足りないところがあります。\\n'+(j.problems||[j.error||'失敗しました']).map(p=>'・'+p).join('\\n'));
    if(typeof load==='function') load();
  }catch(e){pmsg(el,'err','通信に失敗しました: '+e);}
  finally{arrange(el);}
}
function mount(root){  // 描き直したカードに、回答パネルを差し込む
  root.querySelectorAll('.answer').forEach(slot=>{
    const el=panel(slot.dataset.name), fresh=!el.dataset.label, changed=el.dataset.label!==slot.dataset.label;
    el.dataset.working=slot.dataset.working; el.dataset.label=slot.dataset.label;
    const a=el.querySelector('.ghlink'); a.href=slot.dataset.url; a.textContent='Issue #'+slot.dataset.issue;
    slot.appendChild(el); arrange(el);
    if(fresh||changed) loadPanel(el);
  });
}
function paint(box,html){  // 変わったときだけ描き直す。描き直しても、押そうとしていたボタンのフォーカスは保つ
  if(box.dataset.html===html) return;
  const f=document.activeElement, fk=f&&box.contains(f)&&f.dataset?f.dataset.fk:null, inPanel=f&&f.closest&&f.closest('.pane');
  box.dataset.html=html; box.innerHTML=html; mount(box);
  if(fk){const t=[...box.querySelectorAll('[data-fk]')].find(x=>x.dataset.fk===fk); if(t) t.focus();}
  else if(inPanel&&document.body.contains(f)) f.focus();
}
// 通知: 状況が「回答待ち」「返事待ち」「完了」に変わったら、ブラウザの通知と音で知らせる。画面の読み上げ欄にも出す
const NOTIFY={'回答待ち':'質問の Issue ができました。画面で答えてください','返事待ち':'Claude が確認したいことを書きました。返事をしてください','完了':'マーカー付きPDFができました'};
let PREV=null, ACTX=null; const TITLE=document.title;
document.addEventListener('click',()=>{try{ACTX=ACTX||new AudioContext();ACTX.resume();}catch(e){}});
function beep(){try{if(!ACTX)return;const o=ACTX.createOscillator(),g=ACTX.createGain();o.frequency.value=880;g.gain.setValueAtTime(.15,ACTX.currentTime);g.gain.exponentialRampToValueAtTime(.001,ACTX.currentTime+.5);o.connect(g).connect(ACTX.destination);o.start();o.stop(ACTX.currentTime+.5);}catch(e){}}
function notifyChanges(books){
  const now={}, said=[]; books.forEach(b=>now[b.name]=b.label);
  if(PREV) books.forEach(b=>{const old=PREV[b.name];
    if(old!==b.label&&NOTIFY[b.label]&&!(old===undefined&&b.label==='完了')){
      said.push(b.name+': '+b.label);
      beep(); if('Notification' in window&&Notification.permission==='granted') new Notification(b.name+': '+b.label,{body:NOTIFY[b.label]});}});
  if(said.length) $('#sr-status').textContent=said.join('。');
  PREV=now;
  const n=books.filter(b=>b.label==='回答待ち'||b.label==='返事待ち').length;
  document.title=(n?`(${n}) 答えを待っています - `:'')+TITLE;
  notifState();
}
function notifState(){  // 通知の許可の状態を、画面の一番下に出す（未設定のときだけボタン）
  const box=$('#notif'); if(!box) return;
  const p='Notification' in window?Notification.permission:'none';
  const html=p==='default'?'<button class="btn small" onclick="enableNotify()">通知を有効にする</button>'
    :p==='granted'?`<span class="nstate on">${ICON_CHECK}通知は有効です</span>`
    :p==='denied'?'<span class="nstate">通知はブロックされています（アドレスバーの左のアイコンから、通知を許可できます）</span>'
    :'<span class="nstate">このブラウザは通知に対応していません</span>';
  if(box.dataset.p!==p){box.dataset.p=p;box.innerHTML=html;}
}
async function enableNotify(){try{await Notification.requestPermission();}catch(e){} notifState();}
notifState();
async function status(){
  const j=await (await fetch('/api/status')).json();
  notifyChanges(j.books);
  const m=j.monitor, f=$('#mon');
  if(f&&m) f.textContent=`見張り中（${Math.round(m.interval/60)}分ごとに質問の Issue を確認）`+(m.last_check?` ／ 最終確認 ${m.last_check}`:'')+(m.working.length?` ／ 作業中: ${m.working.join('、')}`:'')+(m.error?` ／ 確認に失敗: ${m.error}`:'');
  return j;
}
async function renderList(group,emptyText){
  const j=await status(); const rows=j.books.filter(b=>GROUPS[group].includes(b.label));
  paint($('#list'),rows.map(card).join('')||`<p class="empty">${esc(emptyText)}</p>`);
}
"""

PAGES = {
    "/": (
        "メニュー",
        """
HERO
<div id="ask"></div>
<ul class="tiles">
<li><a class="tile" href="/new"><span class="t">新規取り込み</span><span class="d">PDF をアップロードして、取り込みを始める</span></a></li>
<li><a class="tile" href="/progress"><span class="t">作業状況</span><span class="count"><span id="n-progress">–</span><small>件</small></span><span class="d">進行中・回答待ちの本と号</span></a></li>
<li><a class="tile" href="/library"><span class="t">成果物</span><span class="count"><span id="n-library">–</span><small>件</small></span><span class="d">完了した本と号（マーカー付きPDF）</span></a></li>
</ul>""",
        """
async function load(){
  const j=await status();
  const ask=j.books.filter(b=>b.label==='回答待ち'||b.label==='返事待ち');
  paint($('#ask'),ask.length?'<h2 class="section-title" style="margin-top:0">答えを待っているもの</h2>'+ask.map(card).join('')+'<h2 class="section-title">ページ</h2>':'');
  $('#n-progress').textContent=j.books.filter(b=>GROUPS.progress.includes(b.label)).length;
  $('#n-library').textContent=j.books.filter(b=>b.label==='完了').length;
}
load(); setInterval(load,5000);
""",
    ),
    "/new": (
        "新規取り込み",
        """
<div class="phead"><h1>新規取り込み</h1><p>PDF をアップロードすると、分割案と質問の Issue まで自動で進みます。</p></div>
<div class="cardbox">
<label id="drop" class="drop" for="file">ここに PDF をドロップ、またはクリックして選ぶ（複数可）
<input id="file" class="sr-only" type="file" accept="application/pdf,.pdf" multiple></label>
<p id="msg" class="msg" role="status"></p>
<section id="confirm" class="warnbox" hidden tabindex="-1" aria-labelledby="confirm-title"></section>
<div class="row"><button id="run" class="btn">inbox のPDFを取り込む</button></div>
</div>
<h2 class="section-title">アップロードすると、どこまで自動で進むか</h2>
<div class="cardbox">
<ol class="vsteps">
<li><span class="who">すぐ自動</span><span class="d">PDF を <code>inbox/</code> に保存し、<code>output/&lt;名前&gt;/</code> に移します（中身は書き換えません）。</span></li>
<li><span class="who">数分・自動</span><span class="d">Claude が分割案を作り、本文を読んで、質問の Issue を GitHub に作ります。<b>ここで止まります。</b></span></li>
<li><span class="who">あなたの番</span><span class="d">この画面で、章の分け方・対象・目的・色に答え、「回答を確定して作業を始める」を押します（補足は任意。GitHub の Issue で答えても構いません）。押すまでは、作業は始まりません。</span></li>
<li><span class="who">そのあと自動（時間がかかります）</span><span class="d">Claude が重要箇所を選び、参考文献を集め、マーカー付きPDFを作って、Issue にコメントします。</span></li>
</ol>
<p class="hint">費用・時間がかかるのは 2 と 4 です。3 までは、答えるまで待つだけで、何も進めません。</p>
</div>
<h2 class="section-title">いま取り込み中のもの</h2>
<div id="list"></div>""",
        """
function askReplace(name,warning){  // 同じ名前の PDF があるとき、警告を読んでもらって、取り込み直すかを聞く
  return new Promise(done=>{
    const box=$('#confirm'); box.hidden=false;
    box.innerHTML=`<h2 id="confirm-title">同じ名前の PDF があります: ${esc(name)}</h2><p>${esc(warning)}</p>
      <div class="row"><button class="btn danger armed" id="rep-yes">上書きして取り込み直す</button><button class="btn" id="rep-no">やめる</button></div>`;
    box.focus();
    const end=v=>{box.hidden=true;box.innerHTML='';$('#file').focus();done(v);};
    $('#rep-yes').onclick=()=>end(true); $('#rep-no').onclick=()=>end(false);
  });
}
async function upload(files){
  const msg=$('#msg');
  for(const f of files){
    const c=await (await fetch('/api/upload-check?name='+encodeURIComponent(f.name))).json();
    if(!c.ok){say(msg,'err','失敗: '+c.error); return;}
    let replace=false;
    if(c.exists){
      say(msg,'info','');
      if(!await askReplace(f.name,c.warning)){say(msg,'info',f.name+' は取り込み直しませんでした。'); continue;}
      replace=true;
    }
    say(msg,'info',f.name+' をアップロード中…');
    const fd=new FormData(); fd.append('file',f,f.name);
    const headers={'X-Token':TOKEN}; if(replace) headers['X-Replace']='1';
    const r=await fetch('/upload',{method:'POST',headers,body:fd}); const j=await r.json();
    if(j.ok) say(msg,'ok',f.name+(replace?' で取り込み直します。':' を受け取りました。取り込みを始めます。'));
    else {say(msg,'err','失敗: '+j.error); return;}
  }
  load();
}
$('#file').onchange=e=>{upload(e.target.files); e.target.value='';};
for(const ev of ['dragover','dragenter']) $('#drop').addEventListener(ev,e=>{e.preventDefault();$('#drop').classList.add('over')});
for(const ev of ['dragleave','drop']) $('#drop').addEventListener(ev,e=>{e.preventDefault();$('#drop').classList.remove('over')});
$('#drop').addEventListener('drop',e=>upload(e.dataTransfer.files));
$('#run').onclick=async()=>{const j=await post('/run');say($('#msg'),j.ok===false?'err':'info',j.message||j.error||'');load();};
const load=()=>renderList('new','いま取り込み中のものはありません');
load(); setInterval(load,5000);
""",
    ),
    "/progress": (
        "作業状況",
        """
<div class="phead"><h1>作業状況</h1><p>進行中・回答待ちの本と号です。完了したものは「成果物」にあります。</p></div>
<div id="list"></div>""",
        """
const load=()=>renderList('progress','進行中のものはありません');
load(); setInterval(load,5000);
""",
    ),
    "/library": (
        "成果物",
        """
<div class="phead"><h1>成果物</h1><p>完了した本と号です。仕上がりのPDFは、エクスプローラーで <code>output/&lt;名前&gt;/マーカー付き/</code> から開きます。</p></div>
<div id="list"></div>""",
        """
const load=()=>renderList('library','完了したものはまだありません');
load(); setInterval(load,15000);
""",
    ),
}


# トップの見出し。マーカーの色は apply_highlights.GROUPS（唯一の定義）から作る
LEGEND = "".join(
    f'<li><mark style="background:#{"".join(f"{round(c * 255):02X}" for c in g.color)}">{escape(g.label)}</mark>'
    f"<span>{escape(g.description)}</span></li>"
    for g in GROUPS.values()
)
HERO = f"""<section class="hero" aria-labelledby="hero-title">
<p class="sub">どぱがきのための、雑誌・技術書のマーカー係</p>
<h1 id="hero-title">{PRODUCT.replace("-", "-<wbr>")}</h1>
<p class="lead">分厚い本も、読むところだけ。大事なところには、先にマーカーを。</p>
<dl>
<div><dt>どぱがき とは</dt><dd>「ドーパミン」と「ガキ」を合わせたネットスラング。ショート動画や通知のように、すぐ手に入る刺激に慣れて、長い文章に集中しにくい状態を、自虐を込めて言う（医学用語ではない）。</dd></div>
<div><dt>なぜ作ったか</dt><dd>雑誌や技術書は厚く、どこが大事かも分からないまま、数ページで手が止まる。だから、読みたい記事・章だけを切り出し、Claude が重要な箇所に色分けのマーカーを先に引いておく。マーカーをたどれば要点がつかめ、気になったところだけ前後を読めばいい。</dd></div>
</dl>
<ul class="legend" aria-label="マーカーの色">{LEGEND}</ul>
</section>"""


def render_page(path: str, token: str = "") -> str | None:
    """メニュー・新規取り込み・作業状況・成果物の各ページ。共通の枠（ヘッダー・メニュー）の中に、本文を入れる。"""
    if path not in PAGES:
        return None
    title, body, script = PAGES[path]
    body = body.replace("HERO", HERO)

    def links() -> str:
        return "".join(
            f'<a href="{href}"{" aria-current=page" if href == path else ""}>{name}</a>' for href, name in NAV
        )

    return (
        '<!doctype html>\n<html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        f"<title>{title} - {PRODUCT}</title><style>{CSS}</style></head><body>"
        '<a class="skip" href="#main">本文へ移動</a>'
        '<header class="top"><div class="top-in">'
        f'<button id="burger" class="iconbtn" aria-label="メニューを開く" aria-expanded="false" aria-controls="drawer">{ICON_MENU}</button>'
        f'<a class="brand" href="/"><span>{PRODUCT}</span></a>'
        f'<nav class="tabs" aria-label="ページ">{links()}</nav></div></header>'
        '<div id="scrim" hidden></div>'
        '<nav id="drawer" aria-label="メニュー" inert aria-hidden="true">'
        f'<div class="dhead"><span class="title">メニュー</span><button id="dclose" class="iconbtn" aria-label="メニューを閉じる">{ICON_CLOSE}</button></div>'
        f"{links()}</nav>"
        f'<main id="main" tabindex="-1">{body}</main>'
        "<footer><div id='mon'></div><div id='notif'></div></footer>"
        '<div id="sr-status" class="sr-only" role="status" aria-live="polite"></div>'
        f"<script>const TOKEN={json.dumps(token)};{JS_COMMON}{script}</script></body></html>"
    )
