"""ブラウザ画面の各ページ（メニュー・新規取り込み・作業状況・成果物）と、共通の枠（ヘッダー・ハンバーガーメニュー）。

`web.py` が配信する。状況の判定やアップロードは `web.py`、見た目は、ここ。
"""

# ruff: noqa: E501  （埋め込みの HTML / CSS / JS は、行が長くなる）
from __future__ import annotations

CSS = """
:root{--bg:#f6f7f9;--fg:#1f2328;--sub:#667085;--card:#fff;--line:#e2e5ea;--accent:#2563eb;
--ask:#d97706;--busy:#2563eb;--done:#16a34a;--wait:#7c3aed;--idle:#667085;--shadow:0 1px 2px rgba(0,0,0,.06)}
@media (prefers-color-scheme:dark){:root{--bg:#121316;--fg:#e8eaed;--sub:#9aa3b2;--card:#1c1e23;--line:#2e3138;--accent:#60a5fa;
--ask:#fbbf24;--busy:#60a5fa;--done:#4ade80;--wait:#a78bfa;--idle:#9aa3b2;--shadow:none}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,"Segoe UI","Hiragino Sans","Yu Gothic UI",sans-serif}
header{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:12px;padding:10px 16px;background:var(--card);border-bottom:1px solid var(--line)}
#burger{font-size:1.25rem;line-height:1;padding:6px 10px}
.brand{font-weight:700;color:var(--fg);text-decoration:none}
.crumb{color:var(--sub);font-size:.95rem}
#scrim{position:fixed;inset:0;background:rgba(0,0,0,.35);opacity:0;pointer-events:none;transition:opacity .15s;z-index:20}
#drawer{position:fixed;top:0;left:0;bottom:0;width:260px;max-width:82vw;background:var(--card);border-right:1px solid var(--line);
transform:translateX(-100%);transition:transform .18s;z-index:30;padding:16px 12px;display:flex;flex-direction:column;gap:4px}
body.open #drawer{transform:none} body.open #scrim{opacity:1;pointer-events:auto}
#drawer .title{font-weight:700;padding:4px 12px 12px}
#drawer a{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;border-radius:8px;color:var(--fg);text-decoration:none}
#drawer a:hover{background:var(--bg)} #drawer a.active{background:color-mix(in srgb,var(--accent) 14%,transparent);color:var(--accent);font-weight:600}
main{max-width:780px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:1.25rem;margin:4px 0 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:12px 0;box-shadow:var(--shadow)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.tile{display:block;text-decoration:none;color:inherit;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;box-shadow:var(--shadow)}
.tile:hover{border-color:var(--accent)} .tile .t{font-weight:700;font-size:1.05rem} .tile .n{font-size:1.8rem;font-weight:700;margin-top:4px}
#drop{border:2px dashed var(--line);text-align:center;padding:30px 12px;border-radius:12px;cursor:pointer;color:var(--sub)}
#drop.over{border-color:var(--accent);color:var(--accent);background:color-mix(in srgb,var(--accent) 8%,transparent)}
button,.btn{font:inherit;padding:8px 14px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer;text-decoration:none;display:inline-block}
.btn.primary,button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
a{color:var(--accent)} .sub{color:var(--sub);font-size:.9rem} .name{font-weight:600}
.badge{display:inline-block;padding:1px 10px;border-radius:99px;font-size:.82rem;font-weight:600;margin-left:8px;
color:var(--tone);background:color-mix(in srgb,var(--tone) 14%,transparent);border:1px solid color-mix(in srgb,var(--tone) 35%,transparent)}
.tone-ask{--tone:var(--ask)} .tone-busy{--tone:var(--busy)} .tone-done{--tone:var(--done)} .tone-wait{--tone:var(--wait)} .tone-idle{--tone:var(--idle)}
.item{border-left:4px solid var(--tone)}
.item.ask{background:color-mix(in srgb,var(--ask) 9%,var(--card))}
#msg{min-height:1.4em;margin:8px 0}
ol.steps{margin:8px 0 0;padding-left:1.3em} ol.steps li{margin:4px 0}
.badge:empty{display:none}
.empty{color:var(--sub);text-align:center;padding:24px 0}
"""

NAV = [
    ("/", "メニュー"),
    ("/new", "新規取り込み"),
    ("/progress", "作業状況"),
    ("/library", "成果物"),
]

JS_COMMON = """
const $=s=>document.querySelector(s), esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const TONE={'取り込み待ち':'wait','分割案を作成中':'busy','回答待ち':'ask','作業中':'busy','PDF作成待ち':'wait','未着手':'idle','完了':'done'};
const GROUPS={
  new:['取り込み待ち','分割案を作成中','回答待ち'],
  progress:['取り込み待ち','分割案を作成中','回答待ち','作業中','PDF作成待ち','未着手'],
  library:['完了']};
function setOpen(o){document.body.classList.toggle('open',o);$('#burger').setAttribute('aria-expanded',o);}
$('#burger').onclick=()=>setOpen(!document.body.classList.contains('open'));
$('#scrim').onclick=()=>setOpen(false);
document.addEventListener('keydown',e=>{if(e.key==='Escape')setOpen(false)});
function card(b){
  const tone=TONE[b.label]||'idle', ask=b.label==='回答待ち'&&b.issue_url;
  const act=ask?`<div style="margin-top:10px"><a class="btn primary" href="${esc(b.issue_url)}" target="_blank" rel="noopener">Issue #${b.issue} を開いて答える</a>
    <div class="sub" style="margin-top:6px">分け方・対象・目的・色に答え、最後に「作業開始OK」を付けると、続きが自動で進みます</div></div>`
    :(b.issue_url&&b.label!=='完了'?`<div class="sub"><a href="${esc(b.issue_url)}" target="_blank" rel="noopener">Issue #${b.issue}</a>（進捗のコメントが付きます）</div>`:'');
  return `<div class="card item tone-${tone}${ask?' ask':''}"><span class="name">${esc(b.name)}</span><span class="badge tone-${tone}">${esc(b.label)}</span>
    <div class="sub">${esc(b.detail)}</div>${act}</div>`;
}
async function status(){
  const j=await (await fetch('/api/status')).json();
  const n=j.books.filter(b=>b.label==='回答待ち').length, d=$('#dot'); if(d) d.textContent=n?n+'件':'';
  const m=j.monitor, f=$('#mon');
  if(f&&m) f.textContent=`見張り中（${Math.round(m.interval/60)}分ごとに質問の Issue を確認）`+(m.last_check?` ／ 最終確認 ${m.last_check}`:'')+(m.working.length?` ／ 作業中: ${m.working.join('、')}`:'')+(m.error?` ／ 確認に失敗: ${m.error}`:'');
  return j;
}
async function renderList(group,emptyText){
  const j=await status(); const rows=j.books.filter(b=>GROUPS[group].includes(b.label));
  $('#list').innerHTML=rows.map(card).join('')||`<div class="empty">${esc(emptyText)}</div>`;
}
"""

PAGES = {
    "/": (
        "メニュー",
        """
<h1>メニュー</h1>
<div id="ask"></div>
<div class="tiles">
<a class="tile" href="/new"><div class="t">新規取り込み</div><div class="sub">PDF をアップロードして、取り込みを始める</div></a>
<a class="tile" href="/progress"><div class="t">作業状況</div><div class="n" id="n-progress">–</div><div class="sub">進行中・回答待ちの本と号</div></a>
<a class="tile" href="/library"><div class="t">成果物</div><div class="n" id="n-library">–</div><div class="sub">完了した本と号（マーカー付きPDF）</div></a>
</div>""",
        """
async function load(){
  const j=await status();
  const ask=j.books.filter(b=>b.label==='回答待ち');
  $('#ask').innerHTML=ask.map(card).join('');
  $('#n-progress').textContent=j.books.filter(b=>GROUPS.progress.includes(b.label)).length+' 件';
  $('#n-library').textContent=j.books.filter(b=>b.label==='完了').length+' 件';
}
load(); setInterval(load,5000);
""",
    ),
    "/new": (
        "新規取り込み",
        """
<h1>新規取り込み</h1>
<div class="card">
<div id="drop">ここに PDF をドロップ、またはクリックして選ぶ（複数可）</div>
<input id="file" type="file" accept="application/pdf,.pdf" multiple hidden>
<div id="msg" class="sub"></div>
<button id="run">inbox のPDFを取り込む</button>
</div>
<div class="card">
<div class="name">アップロードすると、どこまで自動で進むか</div>
<ol class="steps sub">
<li><b>すぐ自動:</b> PDF を <code>inbox/</code> に保存し、<code>output/&lt;名前&gt;/</code> に移します（中身は書き換えません）。</li>
<li><b>数分・自動:</b> Claude が分割案を作り、本文を読んで、質問の Issue を GitHub に作ります。<b>ここで止まります。</b></li>
<li><b>あなたの番:</b> Issue のチェックボックスに答え、最後の「作業開始OK」を付けます（章の分け方・対象・目的・色）。</li>
<li><b>そのあと自動（時間がかかります）:</b> Claude が重要箇所を選び、参考文献を集め、マーカー付きPDFを作って、Issue にコメントします。</li>
</ol>
<div class="sub" style="margin-top:8px">費用・時間がかかるのは 2 と 4 です。3 までは、答えるまで待つだけで、何も進めません。</div>
</div>
<h2 style="font-size:1rem;margin:20px 0 4px">いま取り込み中のもの</h2>
<div id="list"></div>""",
        """
async function upload(files){
  for(const f of files){
    $('#msg').textContent=f.name+' をアップロード中…';
    const fd=new FormData(); fd.append('file',f,f.name);
    const r=await fetch('/upload',{method:'POST',body:fd}); const j=await r.json();
    $('#msg').textContent=j.ok?f.name+' を受け取りました。取り込みを始めます。':'失敗: '+j.error;
    if(!j.ok) return;
  }
  load();
}
$('#drop').onclick=()=>$('#file').click();
$('#file').onchange=e=>upload(e.target.files);
for(const ev of ['dragover','dragenter']) $('#drop').addEventListener(ev,e=>{e.preventDefault();$('#drop').classList.add('over')});
for(const ev of ['dragleave','drop']) $('#drop').addEventListener(ev,e=>{e.preventDefault();$('#drop').classList.remove('over')});
$('#drop').addEventListener('drop',e=>upload(e.dataTransfer.files));
$('#run').onclick=async()=>{const j=await (await fetch('/run',{method:'POST'})).json();$('#msg').textContent=j.message;load();};
const load=()=>renderList('new','いま取り込み中のものはありません');
load(); setInterval(load,5000);
""",
    ),
    "/progress": (
        "作業状況",
        """
<h1>作業状況</h1>
<div class="sub">進行中・回答待ちの本と号です。完了したものは「成果物」にあります。</div>
<div id="list"></div>""",
        """
const load=()=>renderList('progress','進行中のものはありません');
load(); setInterval(load,5000);
""",
    ),
    "/library": (
        "成果物",
        """
<h1>成果物</h1>
<div class="sub">完了した本と号です。仕上がりのPDFは、エクスプローラーで <code>output/&lt;名前&gt;/マーカー付き/</code> から開きます。</div>
<div id="list"></div>""",
        """
const load=()=>renderList('library','完了したものはまだありません');
load(); setInterval(load,15000);
""",
    ),
}


def render_page(path: str) -> str | None:
    """メニュー・新規取り込み・作業状況・成果物の各ページ。共通の枠（ヘッダー・ハンバーガーメニュー）の中に、本文を入れる。"""
    if path not in PAGES:
        return None
    title, body, script = PAGES[path]
    links = "".join(
        f'<a href="{href}"{" class=active" if href == path else ""}><span>{name}</span>'
        f"{'<span class=badge id=dot style=--tone:var(--ask)></span>' if href == '/progress' else ''}</a>"
        for href, name in NAV
    )
    crumb = "" if path == "/" else f'<span class="crumb">/ {title}</span>'
    return (
        '<!doctype html>\n<html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title} - PDFハイライト</title><style>{CSS}</style></head><body>"
        '<header><button id="burger" aria-label="メニュー" aria-expanded="false">&#9776;</button>'
        f'<a class="brand" href="/">PDFハイライト</a>{crumb}</header>'
        f'<div id="scrim"></div><nav id="drawer" aria-label="メニュー"><div class="title">メニュー</div>{links}</nav>'
        f"<main>{body}</main>"
        "<footer id='mon' class='sub' style='text-align:center;padding:0 16px 28px'></footer>"
        f"<script>{JS_COMMON}{script}</script></body></html>"
    )
