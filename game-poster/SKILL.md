---
name: game-poster
description: "为 HTML 游戏生成宣传海报。当用户已完成一个 HTML/JS 游戏并需要配套海报、宣传图、主视觉图、封面图时使用：先读游戏代码提取题材与视觉语言，再用妙搭生图后端（gpt-image-2）生成海报。触发词包括：游戏海报、给我的游戏做海报、HTML 游戏宣传图、游戏主视觉、game poster、小游戏封面。即使用户只说“帮这个游戏配张图/做个宣传海报”且上下文是 HTML 游戏，也应触发。不用于通用海报设计（活动海报、公众号封面等请走 image2-gen），也不用于生成游戏本体（那是 frontend-skill / 妙搭的活）。"
---

# Game Poster

为已完成的 HTML 游戏生成宣传海报。核心价值是**从游戏代码中提取视觉语言**，让海报和游戏气质一致，而不是凭空做一张通用海报。

生图走妙搭后端（gpt-image-2），由 `scripts/miaoda_generate.py` 封装，仅依赖 Python 标准库。

## 工作流

### 1. 读游戏，提取海报要素

如果用户没有明确给出游戏信息，先定位并读取 HTML 游戏文件（用 Glob 找 `*.html`，或用户直接给了路径）。单文件游戏直接读；多文件项目读主 HTML 和关键 JS/CSS。

从代码中提取以下要素，这一步决定了海报质量——AI 生图模型不了解这个游戏，全靠你把这些信息翻译成画面描述：

| 要素 | 从哪看 | 用在 prompt 哪里 |
|------|--------|------------------|
| 游戏标题 | `<title>`、界面 H1、开始界面文字 | 海报主标题（必须用中文原样保留） |
| 题材与玩法 | 游戏对象名、角色、敌人、场景描述 | 主视觉画面内容 |
| 美术风格 | CSS 配色、渲染方式（像素/扁平/3D/手绘）、canvas 绘制风格 | Style 部分 |
| 主色调 | CSS 背景色、主题色、高频色值 | Color scheme 部分 |
| 情绪氛围 | 玩法节奏（紧张弹幕/休闲合成/恐怖解谜） | Mood 描述 |

提取不出来时（比如代码里没有明确风格），根据题材合理推断，不要停下来追问。

### 2. 确认海报要素

游戏代码已给出题材、标题、风格时**直接生成**，不要重复确认。只有以下情况才问用户，且一次最多问 2 个：

- 海报上要显示的文字（标题/副标题/标语）——默认用游戏内标题
- 特殊需求：指定尺寸、多版本、指定画面元素（如"要主角在画面中央"）

### 3. 构造提示词

用下面的核心模板，把提取的要素填进占位符。**prompt 用英文写结构和风格指令，需要显示的中文文字原样嵌入**——gpt-image-2 可以直接渲染中文，但英文框架下的文字遵循度更稳。

核心提示词模板（已针对 fast/low 质量模式优化，原则见下文）：

```
Design a vertical promotional poster for an HTML web game.

Game title: "{标题}" — the title text MUST be exactly this, do not change,
rephrase, or translate it. Render it large and prominent, in Simplified Chinese,
{标题字体描述：颜色、发光/描边效果，尽量带色值}.

Main visual: {从玩法/题材翻译出的画面描述，写一个最具代表性的瞬间：
主角 + 核心冲突/场景。例如贪吃蛇写"一条霓虹光蛇穿过网格竞技场"，
塔防写"一座发光的核心塔被成群的敌人围攻"}.
The composition is bold and uncluttered: one dominant focal subject,
strong silhouette, generous negative space, no scattered small elements.

Style: {与游戏一致的美术风格，如 pixel art / flat vector / neon cyberpunk /
hand-drawn cartoon / 3D low-poly}, rendered with rich detail, dramatic
volumetric lighting, crisp edges, vibrant saturated colors, high contrast.
Color scheme: {游戏主色调，尽量带色值或颜色名，如 deep purple + cyan neon},
bold contrast between subject and background.
Mood: {情绪氛围，如 energetic and playful / tense and epic / cozy and relaxing}.

Layout: clear visual hierarchy — title at top or center, main visual as focal
point. Optional small subtitle: "{副标题/标语，可留空}".
Professional game key art, poster-grade quality, sharp focus on the main
subject, no watermarks, no logos, no QR code, no UI screenshots.
```

写提示词的五个要点（前三点决定内容，后两点专门补 fast 模式质感）：

1. **写瞬间，不写清单**。挑一个最有辨识度的画面：主角 + 核心冲突/场景。堆砌 10 个元素只会让画面糊掉。
2. **忠于游戏本身**。海报是游戏的门面，像素游戏就写 pixel art，不要擅自升级成 3D 写实。
3. **给大方向，让模型发挥**。背景和装饰元素不需要过度指定，模型自主发挥的效果通常更好（实测中它自行加的小宇航员、火把都很加分）。
4. **构图上做减法（质感关键）**。`one dominant focal subject / strong silhouette / generous negative space` 这一句强制模型把预算花在一个大主体上。low 质量模式的短板是细节精度——主体越大越聚焦，短板越不显眼；细碎元素越多，越容易露怯。
5. **光影和色彩上做加法（质感关键）**。`dramatic volumetric lighting / rich detail / vibrant saturated colors / high contrast` 这组词不改变画面内容，只提高渲染密度和对比度，让 fast 成图看起来不像"草图"。实测对比：没有这组词的火箭海报偏"素材感"，有这组词的迷宫海报光影层次明显更像正式 key art。

### 4. 生成

脚本路径：`C:/Users/Administrator/.agents/skills/game-poster/scripts/miaoda_generate.py`

**默认用 fast 模式一次出图并交付**。实测数据（见交接文档）：fast 综合画质约 8.4/10，比 final 快约 4.7 倍（~45 秒 vs ~3-4 分钟），中文标题文字实测全对，绝大多数场景够用。每次调用都是真实付费请求，没必要默认烧两遍钱。

```bash
python "C:/Users/Administrator/.agents/skills/game-poster/scripts/miaoda_generate.py" \
  --prompt "<构造好的提示词>" \
  --mode fast --size 1024x1536 \
  --output "<输出目录>" --no-open-output
```

**final 模式（medium 质量 + PNG）只在以下情况使用**：用户明确要求高质量/印刷用途，或 fast 成图在复杂材质、人物特写上明显翻车。final 单次预期 3-5 分钟，存在后端超时风险（见「常见问题」）。注意：在升 final 之前，先尝试用「构造提示词」第 4、5 点的质感词优化 prompt 重跑一次 fast——多数质感问题在 fast 档内就能解决，成本只有 final 的五分之一。

参数要点：

- `--size`：竖版海报 `1024x1536`（默认选这个）；方形分享图 `1024x1024`；横版横幅 `1536x1024`。用户没指定就用竖版。
- `--output`：默认保存到游戏文件同级的 `poster/` 目录，或用户指定的目录。
- 多版本：用多个 `--prompt` 或 `--tasks-json` 批量生成，同一批保持同一套 Style/Color scheme 描述以维持风格一致。
- `--dry-run`：只打印配置不发请求，调 prompt 时可先用它检查。

脚本单次生成可能需要 1-3 分钟（后端排队+生成），设置 Bash timeout ≥ 300000ms，或在后台运行。

### 5. 校验与交付

生成后必须执行：

1. **用 Read 工具打开生成的图**，检查：标题文字是否准确（有无错别字/乱码）、风格是否贴合游戏、构图是否完整。
2. 文字出错时，在 prompt 里加强调后重新生成：`The title text MUST be exactly "XXX" in Simplified Chinese, no typos, no garbled characters.` 不要尝试后期 PS 盖字。
3. 告知用户图片路径和模式（fast 预览质量 / final 正式质量），并问是否需要调整（换构图/换配色/改标语/出 final 高清版）。

## 安全与成本控制

- 妙搭后端无需本机持有上游 API Key，也不要在任何地方写入或提及密钥。
- 每个非 dry-run 任务都是真实付费调用。**不要盲目自动重试**：超时不代表上游没生成成功，无脑重试会产生重复费用。只有确认任务确已失败（后端返回 failed 或明确的网络错误）才重试一次；连续两次失败如实报告错误并停下。
- 批量生成时并发保持 ≤5。
- 交付时区分两件事：**图片生成成功**（接口层面）和**指令完全遵循**（标题文字、数量约束等语义层面）。后者必须经 Read 校验后才算数。
- 妙搭公开端点和上游模型可用性是外部依赖；脚本输出已分别报告会话初始化、任务创建、后端生成、图片下载各阶段结果，失败时按阶段定位。

## 常见问题

- **生成失败/超时**：脚本报错会直接打印原因（网络、后端失败、超时）。final 模式实测出现过等待 300 秒后超时、重试一次即成功（约 186 秒）的情况；fast 模式通常 40 秒左右。重试上限见「安全与成本控制」。
- **fast 与 final 不是同构图高清化**：两种模式是模型两次独立演绎，构图、标题排版、配角元素可能明显不同。如果用户对 fast 成图的某个具体构图元素很满意（比如"就要这个小宇航员"），把它写进 final 的 prompt 里，否则 final 可能不保留。
- **文字渲染偏差**：gpt-image-2 会按语义自主微调文字。对标题有强要求时务必用 `MUST be exactly` 强调措辞。
- **不要在海报里放二维码**：模板已排除。需要二维码时后期用 image2-gen skill 的 `replace_qr.py` 替换真实二维码。

## 与其他 skill 的边界

- 通用海报（活动/公众号/PPT/Banner）→ `image2-gen`
- 制作 HTML 游戏本体 → `frontend-skill` 或妙搭
- 本 skill 只做一件事：游戏已经存在 → 给它配海报。
