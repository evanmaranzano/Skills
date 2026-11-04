# -*- coding: utf-8 -*-
"""单文件翻页绘本构建器 v2 —— StPageFlip 拟真翻页引擎（纸页弯折，小说软件效果）。
用法: python build_book.py            -> 无图自测（纯文字页, 验证模板/引擎, 离线可跑）
     作为库: from build_book import build_book
             build_book(标题, 作者, 日期, 封面图路径或None, [{img: 路径或None, text: str}], 输出.html)
模板与引擎库 page-flip.browser.js（StPageFlip, MIT）须与本文件同目录。
"""
import base64, json, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "page-flip.browser.js")
with open(LIB_PATH, "r", encoding="utf-8") as _f:
    FLIP_LIB = _f.read()

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__TITLE__</title>
<style>
  :root{
    --night1:#101d3d; --night2:#0a1329;
    --paper:#fbf5e9; --paper2:#f3ead8; --ink:#3a352d; --ink2:#8a8072;
    --fox:#e8833a; --gold:#f4c95d;
  }
  *{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  html,body{height:100%}
  body{
    font-family:"Kaiti SC","STKaiti","KaiTi","DFKai-SB",serif;
    background:radial-gradient(120% 90% at 50% -10%, #23407a 0%, var(--night1) 46%, var(--night2) 100%);
    color:var(--ink); overflow:hidden; user-select:none;
  }
  .sky{position:fixed;inset:0;pointer-events:none}
  .sky i{position:absolute;width:3px;height:3px;border-radius:50%;background:#cfe0ff;opacity:.7;
    box-shadow:0 0 6px 1px rgba(207,224,255,.8);animation:tw 3.4s ease-in-out infinite}
  .sky i:nth-child(2n){width:2px;height:2px;animation-delay:1.2s}
  .sky i:nth-child(3n){animation-delay:2.1s}
  @keyframes tw{0%,100%{opacity:.75}50%{opacity:.25}}

  .stage{position:fixed;inset:0;display:flex;align-items:center;justify-content:center}
  .bookwrap{position:relative;animation:settle .8s cubic-bezier(.2,.7,.3,1) both;
    filter:drop-shadow(0 30px 40px rgba(0,0,0,.55))}
  @keyframes settle{from{transform:translateY(14px);opacity:0}to{transform:none;opacity:1}}
  /* 书体厚度装饰（垫在翻页画布后面） */
  .bookwrap::before,.bookwrap::after{content:"";position:absolute;inset:0;border-radius:3px 9px 9px 3px;background:var(--paper2);z-index:0}
  .bookwrap::before{transform:translateX(6px);box-shadow:2px 0 0 #e7dcc4,4px 0 0 #efe6d1,6px 0 0 #e2d5ba}
  .bookwrap::after{transform:translateY(5px)}
  #flipbook{position:relative;z-index:1}

  .pf-page{width:100%;height:100%;background:
      repeating-linear-gradient(93deg, rgba(190,170,120,.05) 0 2px, transparent 2px 5px),
      linear-gradient(90deg, var(--paper) 0%, #f6efdf 80%, #efe5cf 100%);
    overflow:hidden;border-radius:2px 7px 7px 2px}
  @keyframes settleIn{from{filter:brightness(1.10) saturate(1.05)}to{filter:none}}
  .pf-page.settle{animation:settleIn .22s ease-out}
  .pf-page .pageimg{position:absolute;inset:5.5% 6% 13%;width:88%;height:81.5%;object-fit:cover;
    border-radius:3px;box-shadow:0 2px 10px rgba(90,70,30,.14)}
  .pf-page .cap{position:absolute;left:9%;right:9%;bottom:4.6%;font-size:15.5px;line-height:1.75;
    text-align:center;color:var(--ink);letter-spacing:.06em}
  .pf-page .pageno{position:absolute;bottom:1.6%;right:5%;font-family:system-ui,sans-serif;font-size:10px;color:var(--ink2);letter-spacing:.14em}
  .pf-page.cover{background:#0e1a38}
  .pf-page.cover img.cimg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
  .pf-page.cover .author{position:absolute;right:5.5%;bottom:3.2%;font-size:12px;color:#f7ecd4;opacity:.92;letter-spacing:.1em;
    text-shadow:0 1px 3px rgba(0,0,0,.5);z-index:2}
  .pf-page.end{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2.4vh}
  .pf-page.end .fin{font-size:30px;letter-spacing:.5em;text-indent:.5em;color:var(--ink)}
  .pf-page.end .star{color:var(--gold);font-size:20px}
  .pf-page.end .who{font-size:16px;color:var(--ink);letter-spacing:.12em}
  .pf-page.end .org{font-family:system-ui,sans-serif;font-size:11px;color:var(--ink2);letter-spacing:.2em}

  .hud{position:fixed;left:0;right:0;bottom:max(10px,env(safe-area-inset-bottom));display:flex;
    justify-content:center;align-items:center;gap:14px;font-family:system-ui,sans-serif;z-index:60}
  .hud .cnt{font-size:12px;letter-spacing:.24em;color:#9db4e6}
  .hud button{background:none;border:1px solid rgba(157,180,230,.35);color:#cdd9f5;border-radius:999px;
    padding:6px 16px;font-size:13px;cursor:pointer;font-family:inherit;transition:.25s}
  .hud button:hover{border-color:var(--gold);color:var(--gold)}
  .hint{position:fixed;top:max(12px,env(safe-area-inset-top));left:50%;transform:translateX(-50%);
    font-family:system-ui,sans-serif;font-size:11px;letter-spacing:.3em;color:#7f95c9;opacity:.85;
    transition:opacity 1s;pointer-events:none;z-index:60}
  .hint.off{opacity:0}
  @media (prefers-reduced-motion:reduce){.bookwrap{animation:none}.sky i{animation:none}}
</style>
</head>
<body>
<div class="sky" id="sky"></div>
<div class="stage"><div class="bookwrap"><div id="flipbook"></div></div></div>
<div class="hint" id="hint">点 击 · 滑 动 · 扯 页 角 翻 页</div>
<div class="hud"><button id="prev">‹ 上一页</button><span class="cnt" id="cnt"></span><button id="next">下一页 ›</button></div>
<script>__FLIPLIB__</script>
<script>
const TITLE=__TITLE_JSON__, AUTHOR=__AUTHOR_JSON__, DATE=__DATE_JSON__;
const COVER=__COVER_JSON__, PAGES=__PAGES_JSON__;
const wrap=document.querySelector('.bookwrap'), holder=document.getElementById('flipbook');
const cnt=document.getElementById('cnt'), hint=document.getElementById('hint');
const TOTAL=PAGES.length+2;
(function(){const s=document.getElementById('sky');for(let i=0;i<26;i++){const d=document.createElement('i');
  d.style.left=(Math.random()*100).toFixed(1)+'%';d.style.top=(Math.random()*62).toFixed(1)+'%';
  d.style.animationDuration=(2.4+Math.random()*3).toFixed(1)+'s';s.appendChild(d);}})();

/* 组页 */
function el(cls, html){const d=document.createElement('div');d.className=cls;d.innerHTML=html;return d;}
const pagesEls=[];
{const p=document.createElement('div');p.className='pf-page cover';
 p.innerHTML=(COVER?'<img class="cimg" src="'+COVER+'">':'<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:9vh;color:#f4c95d;letter-spacing:.3em;text-align:center;padding:0 10%">'+TITLE+'</div>')
   +'<div class="author">'+AUTHOR+' 著</div>';
 pagesEls.push(p);}
PAGES.forEach(function(pg,i){
  const p=document.createElement('div');p.className='pf-page';p.setAttribute('data-density','soft');
  p.innerHTML=(pg.img?'<img class="pageimg" src="'+pg.img+'">':'')+'<div class="cap">'+pg.text+'</div><div class="pageno">'+(i+2)+' / '+TOTAL+'</div>';
  pagesEls.push(p);});
{const p=document.createElement('div');p.className='pf-page end';
 p.innerHTML='<div class="fin">完</div><div class="star">★</div><div class="who">'+AUTHOR+' 著</div><div class="org">'+TITLE+' · '+DATE+'</div>';
 pagesEls.push(p);}

const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function pageSize(){
  const h=Math.min(window.innerHeight*0.84, window.innerWidth*1.22);
  return {w:Math.round(h*0.75), h:Math.round(h)};
}
let flip=null;
function init(){
  const s=pageSize();
  wrap.style.width=s.w+'px'; wrap.style.height=s.h+'px';
  holder.innerHTML='';
  pagesEls.forEach(function(p){holder.appendChild(p);});
  flip=new St.PageFlip(holder,{
    width:s.w, height:s.h, size:'fixed', usePortrait:true, showCover:true,
    maxShadowOpacity:0.6, showPageCorners:true, swipeDistance:25,
    flippingTime: reduced?1:1050, drawShadow:true, useMouseEvents:true, mobileScrollSupport:true
  });
  flip.loadFromHTML(holder.querySelectorAll('.pf-page'));
  flip.on('flip',function(e){cnt.textContent=(e.data+1)+' / '+flip.getPageCount();hint.classList.add('off');
    var pg=pagesEls[e.data];if(pg){pg.classList.add('settle');setTimeout(function(){pg.classList.remove('settle');},260);}});
  flip.on('changeState',function(e){cnt.textContent=(flip.getCurrentPageIndex()+1)+' / '+flip.getPageCount();});
  cnt.textContent='1 / '+flip.getPageCount();
}
init();
let rz=null;
window.addEventListener('resize',function(){clearTimeout(rz);rz=setTimeout(function(){
  if(!flip)return;
  var cur=flip.getCurrentPageIndex();
  flip.destroy(); init();
  if(cur>0){try{flip.turnToPage(cur);}catch(e){}}
},250);});
/* 深链 #3 直达第 3 页（连续翻页动画） */
(function(){const m=location.hash.match(/^#(\d+)$/);if(m){var t=parseInt(m[1],10)-1;
  if(t>0&&t<TOTAL){var step=function(){if(!flip)return;var c=flip.getCurrentPageIndex();
    if(c<t){flip.flipNext();setTimeout(step,reduced?60:1150);} };setTimeout(step,400);} }})();
document.getElementById('next').onclick=function(){flip&&flip.flipNext();};
document.getElementById('prev').onclick=function(){flip&&flip.flipPrev();};
document.addEventListener('keydown',function(e){if(!flip)return;
  if(e.key==='ArrowRight'||e.key===' ')flip.flipNext();if(e.key==='ArrowLeft')flip.flipPrev();});
</script>
</body>
</html>
"""


def img_to_dataurl(path):
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


def build_book(title, author, date, cover_img, pages, out_path):
    """pages: [{"img": 路径或None, "text": str}, ...]"""
    html = (TEMPLATE
            .replace("__FLIPLIB__", FLIP_LIB)
            .replace("__TITLE_JSON__", json.dumps(title, ensure_ascii=False))
            .replace("__AUTHOR_JSON__", json.dumps(author, ensure_ascii=False))
            .replace("__DATE_JSON__", json.dumps(date, ensure_ascii=False))
            .replace("__COVER_JSON__", json.dumps(img_to_dataurl(cover_img) if cover_img else "", ensure_ascii=False))
            .replace("__PAGES_JSON__", json.dumps(
                [{"img": img_to_dataurl(p["img"]) if p.get("img") else "", "text": p["text"]} for p in pages],
                ensure_ascii=False))
            .replace("__TITLE__", title))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[ok] {out_path}  {os.path.getsize(out_path)/1048576:.1f} MB, {len(pages)} 内页+封面封底")


if __name__ == "__main__":
    # 无图自测: 纯文字页 + 无封面, 验证模板与翻页引擎本身; 有真实图片时走 gen_book.py --build
    build_book(
        title="模板自测",
        author="picture-book skill",
        date="",
        cover_img=None,
        pages=[{"img": None, "text": f"自测页 {i+1}：模板与 StPageFlip 引擎离线冒烟测试。"} for i in range(4)],
        out_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "_smoke_test.html"),
    )
