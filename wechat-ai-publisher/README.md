# wechat-ai-publisher

微信公众号文章自动化发布流水线。把「素材/选题/链接」变成一篇排版好的文章：压缩配图、上传微信素材库、转微信 HTML、存入公众号草稿箱并本地归档。

本 skill 面向公开仓库提供通用及活动通稿发布能力；公众号真实凭证只保存在本地 `.env`（已被 `.gitignore` 忽略），开场 PPTX 模板与本地归档产物亦不随公开仓库分发。

## 六步流水线

1. **素材** — 选题 / 链接 / 文本素材输入
2. **写文章** — 可插拔写作 skill，或按 `references/writing-quality.md` 自行撰写
3. **配图** — 封面压缩后上传为永久图片素材；正文图走微信正文图片接口
4. **转 HTML** — Markdown → 微信 HTML（7 主题，含 `salon` 技术沙龙通稿母版与显式可选的 `salon30` 亲子活动母版）
5. **建草稿** — 写入公众号草稿箱（只建草稿，不群发）
6. **归档** — 本地留存 Markdown 与元数据

福州AI技术社区技术沙龙活动回顾（`salon`）按 `references/fuzhou-ai-salon-article-template.md` 撰写；模板末段固定保留，不随每期活动改写。**亲子活动回顾**使用 `--theme salon30`（智汇对谈第 30 期版式），不自动套用技术沙龙的固定结尾、期数或往期活动事实，仅在用户明确提供或要求时加入。只提供活动主题和介绍时，也可按 `references/fuzhou-ai-event-materials-package.md` 生成社群文案、海报文案、报名介绍、主持开场词、活动提醒和活动后跟进文案。开场 PPT 使用本地的 `templates/fuzhou-ai-salon/opening-template-29.pptx`，复制后只修改首页期数和日期/时间；该 `.pptx` 模板包含现场配置信息，**不包含在公开仓库中**，需本地自行放置（已被 `.gitignore` 忽略）。

## 配置

将 `.env.example` 复制为 `.env` 并自行填写公众号凭据（`.env` 已被 `.gitignore` 忽略，切勿提交到仓库）：

```
WECHAT_APP_ID=wx你的appid
WECHAT_APP_SECRET=你的appsecret
MARKDOWN_CONVERTER=doocs
MARKDOWN_THEME=   # 可填 default/green/purple/orange/cyan/salon/salon30；留空=按内容自动选
```

## 依赖与自检

`requirements.txt` 声明 `requests>=2.28.0`、`markdown>=3.4.0`、`Pillow>=10.0.0`。缺 `markdown` 时 `run_pipeline.py` 会在导入阶段报 `ModuleNotFoundError`，先自检：

```bash
python -c "import importlib.util as u; print({m: bool(u.find_spec(m)) for m in ['requests','markdown','PIL']})"
```

三项全为 `True` 再运行；缺包时用同一解释器安装（不要裸 `pip`）：

```bash
python -m pip install -r requirements.txt
```

## 一键发布

```bash
python scripts/run_pipeline.py \
  --article article.md \
  --cover cover.png \
  --title "文章标题" \
  --author "作者名" \
  --digest "摘要（≤50字）" \
  --theme salon \
  --body-images img1.png,img2.png
```

流水线先检查文章、封面、正文图片、主题、摘要、指定的签名/CTA 文件和归档目录；本地检查未通过时不会调用微信接口。主题优先级为命令行 `--theme`、`.env MARKDOWN_THEME`、内容自动选择。签名/CTA 默认不追加，只有用户提供或明确要求时才传 `--footer-file`。建草稿后需在公众号后台人工检查，流水线不群发。同名归档会加递增后缀；若草稿成功但归档失败，只补归档，不要重建草稿。

## 图片上传

- **封面**：压缩后通过 `material/add_material?type=image` 上传，返回永久素材 `media_id`。
- **正文图**：通过 `media/uploadimg` 上传，支持 JPG/PNG，文件必须小于 1MB；超过限制或格式不支持时，一键流水线会先转成 JPG，以 900KB 为压缩目标，并在上传前确认结果仍小于 1MB。
- 通用主题若文章含本地图片，用 `--body-images` 指定并保证路径能在正文中匹配；沙龙主题从 Markdown 自动读取本地图片。流水线会先核对路径、图片可读性及压缩结果，再发起任何微信写入。
- 未上传的非微信外链图片会在预检时拒绝；先下载并作为本地正文图上传。微信图片 CDN 地址可以保留。
- 单独调用 `upload_material.py` 时，默认上传封面；正文图使用 `--purpose body`。
- 微信返回 `40164` 时，错误信息会显示微信识别到的来源 IP 和白名单配置路径。仅当微信错误没有提供 IP 时，脚本才会向 `api.ipify.org` 查询当前网络出口 IP。

## 主题

- `salon` — **技术沙龙通稿**（福州AI技术社区 21 期沙龙母版，槽位填充，版式与母版一致；沙龙类内容默认自动选用）
- `salon30` — **亲子活动**（智汇对谈第 30 期版式积木母版，需显式 `--theme salon30` 或 `.env MARKDOWN_THEME=salon30` 选用；适用于亲子活动回顾，不自动套用技术沙龙固定结尾、期数或活动事实；`#` 居中导语、`##` 自动生成 `Part.N`、`###` 自动生成 `01/02` 渐变小节、浅蓝底正文卡、按序全宽图片，不含原文视频/名片）
- `cyan` / `orange` / `green` / `purple` / `default` — doocs/md 风格通用主题

本地预览 `salon30`：

```bash
python scripts/render_fuzhou_salon30.py --input article.md --output preview.html --preview
```

## 目录结构

```
wechat-ai-publisher/
├── SKILL.md
├── requirements.txt
├── .env                            # 真实凭证（gitignore，不进库）
├── .env.example
├── references/
│   ├── writing-quality.md          # 反翻译腔终检 + 标题规范
│   ├── fuzhou-ai-salon-article-template.md # 沙龙活动回顾模板
│   └── fuzhou-ai-event-materials-package.md # 活动宣传物料文案包
├── templates/
│   └── fuzhou-ai-salon/
│       ├── master-21.html          # 技术沙龙通稿母版（第21期脱敏版）
│       ├── master-30.html          # 亲子活动积木母版（智汇对谈第30期版式）
│       └── opening-template-29.pptx # 开场PPT（不含在公开仓库，需本地自备，gitignore）
└── scripts/
    ├── config.py                   # 读凭证 + 按内容选主题
    ├── retry_util.py               # 幂等请求重试 + 凭据脱敏
    ├── wechat_errors.py            # 微信 API 错误与白名单 IP 提示
    ├── upload_material.py          # 区分封面素材和正文图片上传
    ├── markdown_to_wechat_doocs.py # MD → 微信 HTML（通用主题与沙龙/亲子分发）
    ├── render_fuzhou_salon.py      # salon 技术沙龙母版槽位渲染
    ├── render_fuzhou_salon30.py    # salon30 亲子活动积木母版渲染与本地预览
    ├── create_draft.py             # 建草稿
    ├── compress_image.py           # 图片压缩
    └── run_pipeline.py             # 一键串联发布侧
```

## 安全说明

- 脚本调用微信公众号官方 API，并在 40164 错误未返回来源 IP 时查询 `api.ipify.org`；图片处理在本地完成
- 凭证推荐放 `.env`；CLI 参数可能出现在命令历史或进程列表。脚本会对 API 异常中的 `secret` 和 `access_token` 脱敏
- 本 skill 只建草稿不群发，群发需到公众号后台人工确认
