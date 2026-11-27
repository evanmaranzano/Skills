---
name: wechat-article-publisher
version: 1.1.0
user-invocable: true
description: 微信公众号文章自动化发布流水线 skill。把素材/选题/链接变成一篇排版好的文章，压缩配图、上传微信素材库、转微信 HTML、存入指定公众号草稿箱并归档。适用于「自动写公众号文章」「文章发到公众号草稿箱」「公众号发布流水线」「做一张图发文」、福州AI技术社区技术沙龙活动回顾（salon）、亲子活动回顾（salon30），以及根据活动主题和介绍生成社群文案、海报文案、报名介绍、主持词和提醒等场景；开场PPT使用指定模板且只更新首页期数和日期时间。写作步骤可插拔（通用版 wechat-article-writer 或人设版 laoluo-article-writer），已内置反翻译腔与标题质量规范。不用于：纯图片/海报设计（用图像生成 skill）、多源深度调研（先走 deep-research）、带引用的研究报告。
---

# 微信公众号文章自动化发布流水线

一句话：素材/选题 → 写文章 → 配图处理 → 转微信 HTML → 存草稿箱 → 归档。

本 skill 只管**发布流水线**，写作交给可插拔的写作 skill。所有账号配置（AppID/AppSecret）**参数化**，不绑定任何特定公众号。

## 配置（两种方式，任选）

### 方式 A：.env 文件（推荐，避免泄露密钥到命令历史）
在 skill 目录放 `.env`：
```
WECHAT_APP_ID=wx你的appid
WECHAT_APP_SECRET=你的appsecret
MARKDOWN_CONVERTER=doocs
MARKDOWN_THEME=   # 留空=按内容自动选；或填 default/green/purple/orange/cyan/salon/salon30
```
脚本会自动读取（`scripts/config.py`）。

### 方式 B：命令行传参
每个脚本都接受 `--app_id` / `--app_secret`，优先级高于 .env。

> ⚠️ **变量名对照**（容易混淆，注意区分）：
> - `.env` 文件用：`WECHAT_APP_ID` / `WECHAT_APP_SECRET`
> - 命令行参数用：`--app_id` / `--app_secret`（**没有 WECHAT_ 前缀**）
> - `run_pipeline.py` 同样支持 `--app_id/--app_secret` 覆盖 .env
>
> ⚠️ AppSecret 是高危凭证，不要写进可被分享的 prompt / 文章 / 日志。建议用 .env 或环境变量。

## 依赖

需要 `requests`（微信 API）、`markdown`（MD→HTML）、`Pillow`（图片压缩），最低版本见 `requirements.txt`。缺 `markdown` 时 `run_pipeline.py` 会在导入阶段直接报 `ModuleNotFoundError`，运行前先自检：
```bash
python -c "import importlib.util as u; print({m: bool(u.find_spec(m)) for m in ['requests','markdown','PIL']})"
```

三项须全为 `True`。缺包时用与运行脚本相同的解释器安装（不要裸 `pip`，以免装到另一个 Python）：
```bash
python -m pip install -r requirements.txt
```

> 若用 `python3` 或下文 `$PYTHON` 跑脚本，自检与安装也换成同一解释器。安装依赖属于环境改动，执行前需取得授权。

## 工作流（六步）

### Step 1 判断任务类型并收集素材
先判断用户要原创、改写、仅排版，还是继续已有草稿：
- **原创**：明确读者、文章目的和可用素材；缺少非关键偏好时采用通用号默认风格，不为小选择反复追问。
- **改写**：保留原文立场、结论、数据、证据、重点顺序和图片。只按用户要求改变表达或结构，不擅自改成热点稿或套用新人设。
- **仅排版/发布**：保留正文内容，只处理图片、主题、HTML 和草稿流程。

整理素材：链接先提取正文；文档提取文字；图片挑选 2–4 张。只在用户要求调研或关键事实需要核验时搜索外部资料。区分已知事实、推断和未知信息，不补造数据、引语或来源。

撰写福州AI技术社区技术沙龙活动回顾（`salon`）时，按 `references/fuzhou-ai-salon-article-template.md` 组织文章。只替换有素材依据的活动信息，不沿用往期的期数、日期、地点、主办方、讲者或数据；缺少的信息删去对应句子或使用职务称谓，不编造、不在成稿中保留占位符。文末固定段必须逐字保留。

撰写**亲子活动**回顾（`--theme salon30`，智汇对谈第 30 期版式）时，按亲子活动真实素材与本页 Step 4 的 Markdown 槽位约定组织内容；**不得自动套用福州AI技术社区技术沙龙的固定结尾、期数或往期活动事实**，仅在用户明确提供或要求时才加入对应信息或署名。

用户提供活动主题和介绍并要求准备物料时，按 `references/fuzhou-ai-event-materials-package.md` 生成社群文案、海报文案、报名页介绍、开场词、提醒和活动后跟进文案；信息缺失时用待补标记并继续。开场 PPT 使用该参考文件指定的第 29 期模板副本，只修改首页期数和日期/时间，其他页面不动；缺少日期/时间时标记待补，不沿用上一期时间。

### Step 2 先列结构，再写文章
动笔前列出开场、核心观点、支撑事实/案例、主要段落和结尾。逐项确认文章能回答读者的问题，事实与素材相符，段落各自表达一个重点。重要或时效性陈述须有可靠来源；无法核验时删去或明确标为待确认。

仅调用当前环境实际可用、且有明确写作指引的中文写作 skill，并按账号风格选择；不要把其他 Harness 中的目录当作已安装能力。没有合适 skill 时按 `references/writing-quality.md` 撰写。未指定标题时给出 3 个备选：主旨型、态度型、钩子型；标题必须由正文支撑，不虚构事实。用户已给标题时保留其意图，只在发现明显不符时提出修改建议。

产出 `article.md`（Markdown）。交付前完成反翻译腔检查、标题检查和事实检查。技术、合规等准确性优先的内容使用保守改写；观点文可调整表达，但不得改变证据和结论。

### Step 3 配图处理
封面图 **必须**（公众号草稿强制要求）。每 500 字左右配 1 张图作为排版参考，不是硬性配额。上传前确认素材已获授权、图片路径有效，且图片表达与所在段落相符。

```bash
PYTHON=python3
SCRIPTS=<本skill目录>/scripts

# 压缩封面（建议 ≤800KB）
$PYTHON $SCRIPTS/compress_image.py --input cover.png --output cover.jpg --max-size 800

# 上传封面永久素材，拿到草稿所需的 thumb_media_id
$PYTHON $SCRIPTS/upload_material.py --purpose cover --image_path cover.jpg

# 上传正文图，拿到正文可用的 URL
$PYTHON $SCRIPTS/upload_material.py --purpose body --image_path body.jpg
```
封面使用永久素材 `media_id`；正文图必须使用 `media/uploadimg` 返回的 `url`。正文图压缩以 900KB 为目标，上传前检查实际结果必须小于 1MB；压缩后仍超限时先报错，不上传。通用主题的 Markdown 若含本地图片，须用 `--body-images` 指定并确保路径确实出现在正文中；沙龙主题从 Markdown 读取本地图片。流水线会先检查文章、封面、正文图、摘要、主题和归档目录，并验证图片能读取、路径能替换；检查通过后才会请求微信接口。不要把本地文件路径当作微信图片 URL。

### Step 4 排版并检查 HTML
通用主题使用 doocs 风格转换器：

```bash
$PYTHON $SCRIPTS/markdown_to_wechat_doocs.py \
  --input article.md --output article.html --theme cyan
```
主题选择顺序：命令行 `--theme` → `.env` 的 `MARKDOWN_THEME` → 按内容自动选择。可选 `cyan`（科技/商务）、`orange`（温暖）、`green`（清新）、`purple`（高端）、`default`（通用）、`salon`（技术沙龙通稿，21 期母版，自动匹配沙龙/技术社区默认主题）和 `salon30`（亲子活动，智汇对谈第 30 期版式，需显式指定）。

转换前检查手机阅读结构：段落是否过长、标题层级是否清楚、列表/表格是否必要、图片是否出现在对应内容附近。长段落和图片间距仅作人工复核提示，按文章体裁调整，不机械套用字数阈值。

`salon` 与 `salon30` 不是 CSS 主题：
- `salon`（**技术沙龙通稿**，默认沙龙模板）：以第 21 期通稿清理后的 HTML 为母版（`templates/fuzhou-ai-salon/master-21.html`），由 `scripts/render_fuzhou_salon.py` 替换段落文字与配图 URL，其余结构保持不变。母版有 7 个文字段落槽、5 个内容图片槽和可选文末二维码；槽位不足时按整块删减，多余段落追加至末卡。`qr_url` 缺省或仅为空白时，二维码图片、扫码文案及专属间隔整块省略；显式提供时会去首尾空白、转义后填入 `src` 与 `data-src`，`markdown_to_html_doocs(..., theme_name="salon", qr_url=...)` 可透传。引用块文字会去掉 Markdown 引用符号后保留为普通段落；没有可用正文段落时，流水线在上传前报错。
- `salon30`（**亲子活动**，智汇对谈第 30 期版式，显式 `--theme salon30` 或 `MARKDOWN_THEME=salon30` 选用，不改变 `salon` 默认自动选择）：以第 30 期公开版式提取的积木母版（`templates/fuzhou-ai-salon/master-30.html`）为基础，由 `scripts/render_fuzhou_salon30.py` 按 Markdown 结构动态组装，适用于亲子活动回顾；不自动套用福州AI技术社区技术沙龙的固定结尾、期数或活动事实（仅用户明确提供或要求时加入），支持任意数量章节与图片：
  - 首个 `# 标题` 及紧随的连续导语行 → 居中开篇导语块（`# 标题` 渲染为浅蓝白字徽标，行内 `**加粗**` 为浅蓝加粗，亦可用 `==标签==`）
  - `## 章节名` → 自动生成 `Part.1`、`Part.2`、… 桃色角标 + 蓝色圆角标题横幅（不限 4 个）
  - `### 小节名` → 当前 Part 内自动递增 `01`、`02`、… 圆形编号 + 渐变胶囊子标题
  - 普通段落 / 引用 / 列表 → 合并入浅蓝底正文卡（`rgba(96, 160, 246, 0.18)`，段落首行缩进 2em）
  - `![alt](path)` → 按出现顺序渲染为全宽图片卡（省略未用图片槽；不保留原文视频播放器、往期文字、图片或机构名片/二维码，如需文末署名请用 `--footer-file`）
  - 本地离线预览命令：`$PYTHON $SCRIPTS/render_fuzhou_salon30.py --input article.md --output preview.html --preview`

转成 HTML 后核对：正文与 Markdown 一致；本地图片路径已替换成微信 URL；标题、摘要和封面相互匹配。品牌签名或 CTA 仅在用户提供或明确要求时加入，不自动插入预设营销语。手动转换时用 `--footer-file footer.md` 显式追加指定文件；默认不追加 footer。老罗等特定排版风格只在用户选定相应风格时应用。

### Step 5 创建草稿并人工复核
创建前确认最终标题、摘要（不超过 50 字）、封面和正文图片。CTA、作者信息和签名只使用用户提供的内容。

```bash
$PYTHON $SCRIPTS/create_draft.py \
  --title "文章标题" \
  --content article.html \
  --thumb_media_id "封面thumb_media_id" \
  --author "作者名" \
  --digest "摘要（≤50字）"
# 成功输出 {"media_id":"..."}
```
默认只建**草稿**，不自动群发。建稿成功后到公众号后台检查标题、摘要、封面、图片位置和手机端排版，再由用户决定是否群发。若无凭据或 API 不可用，可保留本地 Markdown/HTML，并提供人工粘贴到公众号编辑器的步骤；如写入结果不明，先检查后台草稿，确认状态前不要重跑写入请求。

### Step 6 归档并报告状态
- 文章 → `articles/published/YYYYMMDD_标题.md`
- 元数据 → `articles/published/YYYYMMDD_标题_meta.json`（含 `media_id`、`thumb_media_id`、主题和时间）
- 同名归档自动加递增后缀，不覆盖旧文件。
- 汇报草稿状态、`media_id`、实际主题和归档路径。若草稿已建但归档失败，只补做本地归档，不要再次创建草稿。

### 一键串联（run_pipeline，推荐）
最终文章和素材确认后，用 `run_pipeline.py` 执行发布侧流程：

```bash
$PYTHON $SCRIPTS/run_pipeline.py \
  --article article.md \
  --cover cover.png \
  --title "文章标题" \
  --author "作者名" \
  --digest "摘要（≤50字）" \
  --theme cyan \
  --body-images img1.png,img2.png
```
`--theme`、`--author` 和 `--digest` 可省略；没有正文图时可省略 `--body-images`，salon 会从 Markdown 读取图片。通用主题含本地正文图时必须提供对应路径。仅在用户提供或明确要求签名/CTA 时才传 `--footer-file footer.md`。主题按命令行 → `.env MARKDOWN_THEME` → 内容自动选择。CLI 可用 `--app_id/--app_secret` 覆盖 `.env`。

流水线先验证文章、封面、正文图片、主题、摘要和归档目录；任何本地检查失败都会在调用微信接口前退出。通过后依次压缩并上传封面、上传正文图并替换图片地址、转 HTML、创建草稿和归档。成功时输出 `media_id`、实际主题和归档路径；完整流程不包含群发。

## 能力边界与限制

- **封面图**：通过永久素材接口以 `type=image` 上传，官方限制为 ≤10MB；流水线建议先压到 ≤800KB。不要使用 `type=thumb`，该类型只支持 JPG 且上限为 64KB。
- **正文图**：通过 `media/uploadimg` 上传，支持 JPG/PNG 且必须小于 1MB；通用主题用 `--body-images` 指定正文中的本地图片，沙龙主题从 Markdown 读取。流水线以 900KB 为压缩目标，并在任何微信写入前检查压缩结果小于 1MB；压缩失败或图片路径无法替换时停止。
- **正文图外链**：微信草稿可能过滤未上传的外部图片 URL；流水线会在上传前拒绝非微信 CDN 的外链图片。请先下载到本地并通过 `--body-images` 上传；微信图片 CDN URL 可直接保留。
- **正文图数量**：单篇建议 ≤20 张，过多影响 App 端加载。
- **文章长度**：当前官方新增草稿文档标注正文少于 2 万字符且小于 1MB；同页另有 2KB 限制描述与前述数值冲突。避免超长内容，并以目标账号接口实际校验为准。
- **网络**：需稳定访问 `api.weixin.qq.com`。幂等请求会自动重试；上传和建草稿等 POST 写入请求只发送一次，避免响应丢失时重复创建。若结果不明，先检查公众号后台再重试。
- **API 配额**：公众号按等级有每日 API 调用额度（素材上传、草稿创建等），超限返回对应 errcode，请稍后或次日再试。
- **群发**：本 skill 只建草稿**不群发**（安全设计），群发需到公众号后台人工确认。

## 重试与故障排查

脚本已内置网络自动重试（`scripts/retry_util.py`，3 次指数退避），仅重试网络异常/5xx，不重试 4xx 业务错误。常见失败对照：

| errcode / 现象 | 原因 | 处理 |
|---|---|---|
| 40001 / 40125 | access_token 或 app_id / app_secret 无效 | 检查 `.env` 配置 |
| 40006 | 封面图片格式或大小不符合要求 | 封面使用 JPG/PNG 等支持格式并控制在 10MB 内 |
| 40009 | 正文图过大或格式不支持 | 使用 JPG/PNG 并确保小于 1MB；流水线会在上传前压缩和检查，仍超限时先报错 |
| 40007 | thumb_media_id 无效 | 确认封面通过永久图片素材接口上传成功 |
| 40164 | 当前请求出口 IP 不在公众号白名单 | 错误信息会显示微信返回的来源 IP，并提示配置路径；将该 IP 加入公众号后台白名单后重试 |
| 网络超时 / ConnectionError | 网络不稳/代理 | GET 等幂等请求自动重试；写入请求只尝试一次，先检查公众号后台状态再决定是否重跑 |
| no_cover | 未传封面 | 公众号草稿强制要求封面，先上传封面拿 media_id |

> AppSecret 不会由诊断输出打印；API 请求异常中的 `secret` 和 `access_token` 会脱敏。

## 铁律
- 封面图 **必须有**，否则微信拒收草稿。
- 封面必须上传为永久图片素材；正文图必须使用 `media/uploadimg` 返回的 URL。
- 正文图仅 JPG/PNG 且小于 1MB；封面永久图片素材不超过 10MB。
- AppSecret 不进日志/文章/prompt；命令行传参可能暴露在命令历史或进程列表中，优先用 `.env`。
- 默认只存草稿，群发需人工确认。

## 资源
- `scripts/config.py` — .env 配置读取 + 按内容自动选主题（含 salon）
- `scripts/retry_util.py` — 幂等请求指数退避、写入请求不自动重试、异常凭据脱敏
- `scripts/wechat_errors.py` — 微信 API 错误格式化与 40164 白名单 IP 指引
- `scripts/upload_material.py` — 分别上传封面永久素材与正文图片
- `scripts/markdown_to_wechat_doocs.py` — MD→微信 HTML（通用主题）
- `scripts/render_fuzhou_salon.py` — `salon` 技术沙龙通稿母版槽位渲染（21期原文逆向）
- `scripts/render_fuzhou_salon30.py` — `salon30` 亲子活动积木母版渲染（智汇对谈第30期版式，支持可变 Part/小节/图片）
- `scripts/create_draft.py` — 建草稿（支持可选 footer 追加，带重试）
- `templates/fuzhou-ai-salon/master-21.html` — 技术沙龙通稿母版
- `templates/fuzhou-ai-salon/master-30.html` — 亲子活动积木母版（智汇对谈第30期版式）
- `templates/fuzhou-ai-salon/opening-template-29.pptx` — 开场 PPT 模板（不含在公开仓库，需本地自备），只修改首页期数和日期/时间
- `references/writing-quality.md` — 反翻译腔 L4 终检 + 标题规范（通用版）
- `references/fuzhou-ai-salon-article-template.md` — 福州AI技术社区技术沙龙活动推文结构与固定结尾
- `references/fuzhou-ai-event-materials-package.md` — 活动主题宣传物料文案包和开场 PPT 模板规则
- `.env.example` — 配置模板
