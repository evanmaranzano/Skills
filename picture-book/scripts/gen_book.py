# -*- coding: utf-8 -*-
"""绘本生成器：story.json 驱动的全流程脚本（定妆照 → 构图参考 → 封面 → 逐页 → 组装）。

用法:
  python gen_book.py story.json --base http://host:port --out ./out            # 生成图片
  python gen_book.py story.json --base ... --out ./out --build book.html      # 生成 + 组装
  python gen_book.py story.json --out ./out --build-only book.html            # 只组装(图已生成)
  --force 重已存在的图; 服务地址也可用环境变量 QWEN_IMAGE_BASE 传入。

流程与 prompt 拼接规则来自实测验证的方法论（见 ../references/methodology.md）:
  anchor = anchor + "，" + style                          (quality 档, 全书形象锚点)
  cover  = cover + "，" + style                           (fast 档)
  comp   = 完整 prompt, 不拼 style                        (fast t2i 剪影示意)
  单参考页 = keep + "。新场景：" + scene + "，" + style      (fast edits, image=anchor)
  多参考页 = 固定声明 + scene + style                      (fast edits, image=anchor, image2=comp)
"""
import argparse, json, os, sys, time

# 内网直连: 本机系统代理(Clash 等)会劫持内网请求返回 502, 必须在任何网络库 import 前清掉
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MULTIREF_PREFIX = ("Picture 1 是角色定妆照，Picture 2 是构图参考。以 Picture 1 为准保持角色形象与画风完全不变，"
                   "严格按 Picture 2 的构图与景别安排画面布局。")
RETRY = 2  # 网络抖动/5xx 重试次数


def load_story(path):
    with open(path, encoding="utf-8") as f:
        s = json.load(f)
    for k in ("title", "style", "keep", "anchor", "cover", "pages"):
        assert k in s, f"story.json 缺字段: {k}"
    for p in s["pages"]:
        assert "name" in p and "scene" in p, f"page 缺 name/scene: {p}"
    return s


def post_image(base, payload):
    """文生图, 返回 (png_bytes, elapsed_header)。5xx/网络错误重试, 4xx 参数错不重试。"""
    last = None
    for i in range(RETRY + 1):
        try:
            r = requests.post(f"{base}/v1/images", json=payload, timeout=300)
            if r.status_code == 200:
                return r.content, r.headers.get("X-Elapsed-Sec", "?")
            if r.status_code < 500:
                raise SystemExit(f"[fail] /v1/images {r.status_code} (参数错误不重试): {r.text[:200]}")
            last = f"{r.status_code} {r.text[:120]}"
        except requests.RequestException as e:
            last = repr(e)
        if i < RETRY:
            print(f"  [retry {i+1}/{RETRY}] {last}", flush=True)
            time.sleep(3)
    raise SystemExit(f"[fail] /v1/images 重试耗尽: {last}")


def post_edit(base, prompt, anchor_path, comp_path, data_extra):
    """图生图编辑。anchor 永远是 image; comp 存在时作为 image2 多参考。"""
    files = [("image", ("anchor.png", open(anchor_path, "rb"), "image/png"))]
    if comp_path:
        files.append(("image2", ("comp.png", open(comp_path, "rb"), "image/png")))
    data = {"prompt": prompt, **data_extra}
    last = None
    try:
        for i in range(RETRY + 1):
            for _, (_, fobj, _) in files:  # 重试前回卷文件指针, 否则发空文件
                fobj.seek(0)
            try:
                r = requests.post(f"{base}/v1/edits", files=files, data=data, timeout=300)
                if r.status_code == 200:
                    return r.content, r.headers.get("X-Elapsed-Sec", "?")
                if r.status_code < 500:
                    raise SystemExit(f"[fail] /v1/edits {r.status_code} (参数错误不重试): {r.text[:200]}")
                last = f"{r.status_code} {r.text[:120]}"
            except requests.RequestException as e:
                last = repr(e)
            if i < RETRY:
                print(f"  [retry {i+1}/{RETRY}] {last}", flush=True)
                time.sleep(3)
        raise SystemExit(f"[fail] /v1/edits 重试耗尽: {last}")
    finally:
        for _, (_, fobj, _) in files:
            fobj.close()


def save(out, name, content, mode_hdr, elapsed, force):
    """断点续跑: 已存在且非空则跳过。"""
    path = os.path.join(out, f"{name}.png")
    if not force and os.path.exists(path) and os.path.getsize(path) > 0:
        print(f"[skip] {name} (已存在)", flush=True)
        return path
    with open(path, "wb") as f:
        f.write(content)
    print(f"[ok] {name}: {elapsed}s [{mode_hdr}]", flush=True)
    return path


def generate(story, base, out, force):
    os.makedirs(out, exist_ok=True)
    w, h = story.get("width", 1024), story.get("height", 1360)
    seed = story.get("seed", 42)
    style = story["style"]
    common = {"width": w, "height": h, "num_inference_steps": 20, "seed": seed}
    t_start = time.time()

    # 1. 定妆照: quality 档(不加速) —— 全书形象锚点, 值得多花时间
    anchor_prompt = f'{story["anchor"]}，{style}'
    content, elapsed = post_image(base, {**common, "prompt": anchor_prompt, "fast": False})
    anchor_path = save(out, "00_anchor", content, "quality", elapsed, force)

    # 2. 构图参考: fast t2i 剪影示意(不拼 style, 构图示意无需画风)
    for name, prompt in story.get("comps", {}).items():
        content, elapsed = post_image(base, {**common, "prompt": prompt, "fast": True})
        save(out, name, content, "fast", elapsed, force)

    # 3. 封面: fast t2i
    content, elapsed = post_image(base, {**common, "prompt": f'{story["cover"]}，{style}', "fast": True})
    save(out, "01_cover", content, "fast", elapsed, force)

    # 4. 逐页: fast edits, 永远从定妆照出发(不链式), 大场面页挂构图参考
    data_fast = {"num_inference_steps": "20", "seed": str(seed), "fast": "true"}
    for p in story["pages"]:
        comp = p.get("comp")
        if comp:
            prompt = f"{MULTIREF_PREFIX}新场景：{p['scene']}，{style}"
            comp_path = os.path.join(out, f"{comp}.png")
            assert os.path.exists(comp_path), f"构图参考缺失: {comp_path}"
        else:
            prompt = f'{story["keep"]}。新场景：{p["scene"]}，{style}'
            comp_path = None
        target = os.path.join(out, f'{p["name"]}.png')
        if not force and os.path.exists(target) and os.path.getsize(target) > 0:
            print(f"[skip] {p['name']} (已存在)", flush=True)
            continue
        content, elapsed = post_edit(base, prompt, anchor_path, comp_path, data_fast)
        tag = f"fast+multiref:{comp}" if comp else "fast"
        save(out, p["name"], content, tag, elapsed, force)

    print(f"[done] 全部完成, 用时 {time.time()-t_start:.0f}s -> {out}", flush=True)


def build(story, out, book_path):
    from build_book import build_book
    book_dir = os.path.dirname(os.path.abspath(book_path))
    os.makedirs(book_dir, exist_ok=True)
    pages = [{"img": os.path.join(out, f'{p["name"]}.png'), "text": p.get("caption", "")}
             for p in story["pages"]]
    cover = os.path.join(out, "01_cover.png")
    for pg in pages + [{"img": cover}]:
        assert os.path.exists(pg["img"]), f"缺图: {pg['img']} (先跑生成, 或检查 name)"
    build_book(story["title"], story.get("author", ""), story.get("date", ""),
               cover, pages, book_path)
    size_mb = os.path.getsize(book_path) / 1048576
    print(f"[book] {book_path} ({size_mb:.1f} MB) — 双击打开, 离线可用", flush=True)


def main():
    ap = argparse.ArgumentParser(description="AI 绘本全流程生成器")
    ap.add_argument("story", help="story.json 路径")
    ap.add_argument("--base", default=os.environ.get("QWEN_IMAGE_BASE"),
                    help="Qwen-Image 服务地址 (或环境变量 QWEN_IMAGE_BASE)")
    ap.add_argument("--out", required=True, help="图片输出目录")
    ap.add_argument("--build", metavar="HTML", help="生成完成后组装成书")
    ap.add_argument("--build-only", metavar="HTML", help="跳过生成, 只组装(图已存在)")
    ap.add_argument("--force", action="store_true", help="重已存在的图")
    a = ap.parse_args()

    story = load_story(a.story)
    if a.build_only:
        build(story, a.out, a.build_only)
        return
    if not a.base:
        raise SystemExit("缺服务地址: 传 --base http://host:port 或设 QWEN_IMAGE_BASE")
    generate(story, a.base.rstrip("/"), a.out, a.force)
    if a.build:
        build(story, a.out, a.build)


if __name__ == "__main__":
    main()
