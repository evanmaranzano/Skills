# -*- coding: utf-8 -*-
"""单文件翻页绘本构建器 v2 —— StPageFlip 拟真翻页引擎（纸页弯折，小说软件效果）。
用法: python build_book.py            -> 无图自测（纯文字页, 验证模板/引擎, 离线可跑）
     作为库: from build_book import build_book
             build_book(标题, 作者, 日期, 封面图路径或None, [{img: 路径或None, text: str}], 输出.html)
模板与引擎库 page-flip.browser.js（StPageFlip, MIT）须与本文件同目录。
"""
import base64, io, json, os, sys
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
  .bookscale{position:relative;flex:0 0 auto;width:750px;height:1000px;transform-origin:50% 50%}
  .bookwrap{position:relative;width:100%;height:100%;animation:settle .8s cubic-bezier(.2,.7,.3,1) both;
    filter:drop-shadow(0 30px 40px rgba(0,0,0,.55))}
  @keyframes settle{from{transform:translateY(14px);opacity:0}to{transform:none;opacity:1}}
  /* 书体厚度装饰（垫在翻页画布后面） */
  .bookwrap::before,.bookwrap::after{content:"";position:absolute;inset:0;border-radius:3px 9px 9px 3px;background:var(--paper2);z-index:0}
  .bookwrap::before{transform:translateX(6px);box-shadow:2px 0 0 #e7dcc4,4px 0 0 #efe6d1,6px 0 0 #e2d5ba}
  .bookwrap::after{transform:translateY(5px)}
  #flipbook{position:relative;z-index:1}
  #flipbook.fallback{width:100%;height:100%}
  #flipbook.fallback .pf-page{position:absolute;inset:0}

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
<div class="stage"><div class="bookscale" id="bookscale"><div class="bookwrap"><div id="flipbook"></div></div></div></div>
<div class="hint" id="hint">点 击 · 滑 动 · 扯 页 角 翻 页</div>
<div class="hud"><button id="prev">‹ 上一页</button><span class="cnt" id="cnt"></span><button id="next">下一页 ›</button></div>
<script>__FLIPLIB__</script>
<script>
var TITLE=__TITLE_JSON__, AUTHOR=__AUTHOR_JSON__, DATE=__DATE_JSON__;
var COVER=__COVER_JSON__, PAGES=__PAGES_JSON__;
var scaleBox=document.getElementById('bookscale'), holder=document.getElementById('flipbook');
var cnt=document.getElementById('cnt'), hint=document.getElementById('hint');
var BASE_W=750, BASE_H=1000, TOTAL=PAGES.length+2;
var flip=null, currentPage=0;
(function(){var s=document.getElementById('sky');for(var i=0;i<26;i++){var d=document.createElement('i');
  d.style.left=(Math.random()*100).toFixed(1)+'%';d.style.top=(Math.random()*62).toFixed(1)+'%';
  d.style.animationDuration=(2.4+Math.random()*3).toFixed(1)+'s';s.appendChild(d);}})();

/* 组页 */
var pagesEls=[];
{var p=document.createElement('div');p.className='pf-page cover';
 p.innerHTML=(COVER?'<img class="cimg" src="'+COVER+'">':'<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:9vh;color:#f4c95d;letter-spacing:.3em;text-align:center;padding:0 10%">'+TITLE+'</div>')
   +'<div class="author">'+AUTHOR+' 著</div>';
 pagesEls.push(p);}
PAGES.forEach(function(pg,i){
  var p=document.createElement('div');p.className='pf-page';p.setAttribute('data-density','soft');
  p.innerHTML=(pg.img?'<img class="pageimg" src="'+pg.img+'">':'')+'<div class="cap">'+pg.text+'</div><div class="pageno">'+(i+2)+' / '+TOTAL+'</div>';
  pagesEls.push(p);});
{var p=document.createElement('div');p.className='pf-page end';
 p.innerHTML='<div class="end-inner"><div class="fin">完</div><div class="star">★</div><div class="who">'+AUTHOR+' 著</div><div class="org">'+TITLE+' · '+DATE+'</div></div>';
 pagesEls.push(p);}

var reduced=window.matchMedia?window.matchMedia('(prefers-reduced-motion: reduce)').matches:false;
function fitBook(){
  var vw=window.innerWidth||document.documentElement.clientWidth;
  var vh=window.innerHeight||document.documentElement.clientHeight;
  var scale=Math.min(vh*0.84/BASE_H,vw*1.22/BASE_H);
  if(!isFinite(scale)||scale<=0)scale=1;
  var value='scale('+scale+')';
  scaleBox.style.webkitTransform=value;scaleBox.style.msTransform=value;scaleBox.style.transform=value;
}
function setCounter(index){
  currentPage=Math.max(0,Math.min(TOTAL-1,index));
  cnt.textContent=(currentPage+1)+' / '+TOTAL;
}
function showFallbackPage(index){
  setCounter(index);
  for(var i=0;i<pagesEls.length;i++)pagesEls[i].style.display=i===currentPage?'block':'none';
}
function startFallback(){
  flip=null;holder.className='fallback';holder.innerHTML='';
  pagesEls.forEach(function(p){p.style.cssText='';holder.appendChild(p);});
  hint.textContent='使 用 下 方 按 钮 翻 页';
  showFallbackPage(currentPage);
}
function patchScaledPointer(){
  /* StPageFlip 以未缩放坐标计算页角；外层 CSS 缩放后需换算回书本坐标。 */
  var ui=flip.getUI(), original=ui.getMousePos;
  ui.getMousePos=function(x,y){
    var el=this.getDistElement(), rect=el.getBoundingClientRect();
    var w=el.offsetWidth, h=el.offsetHeight;
    if(rect.width>0&&rect.height>0&&w>0&&h>0)return{
      x:(x-rect.left)*w/rect.width,y:(y-rect.top)*h/rect.height
    };
    return original.call(this,x,y);
  };
}
function init(){
  fitBook();holder.innerHTML='';
  pagesEls.forEach(function(p){holder.appendChild(p);});
  if(!window.St||!window.St.PageFlip){startFallback();return;}
  try{
    flip=new St.PageFlip(holder,{
      width:BASE_W,height:BASE_H,size:'fixed',usePortrait:true,showCover:true,
      maxShadowOpacity:0.6,showPageCorners:true,swipeDistance:25,
      flippingTime:reduced?1:1050,drawShadow:true,useMouseEvents:true,mobileScrollSupport:true
    });
    flip.loadFromHTML(holder.querySelectorAll('.pf-page'));
    patchScaledPointer();
    flip.on('flip',function(e){setCounter(e.data);hint.classList.add('off');
      var pg=pagesEls[e.data];if(pg){pg.classList.add('settle');setTimeout(function(){pg.classList.remove('settle');},260);}});
    flip.on('changeState',function(){if(flip)setCounter(flip.getCurrentPageIndex());});
    setCounter(0);
  }catch(e){startFallback();}
}
init();
/* 仅缩放外层，不销毁引擎：destroy() 会移除 #flipbook，且旧 RAF 循环不会停止。 */
window.addEventListener('resize',fitBook,false);
window.addEventListener('orientationchange',fitBook,false);
document.addEventListener('fullscreenchange',fitBook,false);
document.addEventListener('webkitfullscreenchange',fitBook,false);
function nextPage(){if(flip)flip.flipNext();else showFallbackPage(currentPage+1);}
function prevPage(){if(flip)flip.flipPrev();else showFallbackPage(currentPage-1);}
/* 深链 #3 直达第 3 页（连续翻页动画） */
(function(){var m=location.hash.match(/^#(\d+)$/);if(m){var t=parseInt(m[1],10)-1;
  if(t>0&&t<TOTAL){if(!flip){showFallbackPage(t);return;}var step=function(){if(!flip)return;var c=flip.getCurrentPageIndex();
    if(c<t){flip.flipNext();setTimeout(step,reduced?60:1150);} };setTimeout(step,400);} }})();
document.getElementById('next').onclick=nextPage;
document.getElementById('prev').onclick=prevPage;
document.addEventListener('keydown',function(e){
  if(e.key===' '&&e.target&&e.target.tagName==='BUTTON')return;
  if(e.key==='ArrowRight'||e.key===' '){e.preventDefault();nextPage();}
  if(e.key==='ArrowLeft'){e.preventDefault();prevPage();}
});
</script>
</body>
</html>
"""


def img_to_dataurl(path):
    """优先用高质量 JPEG 减小单文件体积；无 Pillow 时保留原图字节。"""
    try:
        from PIL import Image
    except ImportError:
        mime = "image/jpeg" if str(path).lower().endswith((".jpg", ".jpeg")) else "image/png"
        with open(path, "rb") as f:
            return f"data:{mime};base64," + base64.b64encode(f.read()).decode()
    with Image.open(path) as source:
        image = source.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=90, optimize=True, subsampling=0)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


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
