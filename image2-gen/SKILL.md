---
name: image2-gen
description: "使用 gpt-image-2 生成图片、海报、PPT 幻灯片、社交媒体图、Banner、公众号封面。当用户需要生成任何图片、设计、视觉内容时使用此 skill，包括但不限于：生图、做海报、做 PPT、做封面、做 Banner、做社交媒体配图、设计宣传物料。即使用户没明确说用 gpt-image-2，只要涉及图片生成/设计类需求都应触发。"
---

# Image2 Generator

使用 gpt-image-2（OpenAI 兼容接口）生成各类图片和设计物料。

## API 配置

```
Base URL: https://api.change2pro.com
API Key:  sk-3720b589b8da0cdad386a526beae0ab388e71a3383a2ad464b37c34c449505fb
Model:    gpt-image-2
```

调用方式：OpenAI 兼容的 `/v1/images/generations` 端点。

## 失败兜底策略

必须优先直连 `https://api.change2pro.com/v1/images/generations`。只有在直连失败时，才允许启动本地轻量中转，且中转的上游仍然必须是 `change2pro`，不能改成其他图片服务。

### 何时判定直连失败

满足任一条件即可视为失败：

- HTTP `403` 且响应中出现 `1010`
- 连接被重置、TLS 建连失败、读取超时
- 连续两次直连都没有拿到有效 JSON 响应

### 失败后的强制动作

1. 向用户说明：直连失败，准备切换到本地轻量中转，仍然走 `change2pro`
2. 后台启动本地中转：

```powershell
powershell -File C:/Users/Administrator/.agents/skills/image2-gen/scripts/start_change2pro_relay.ps1
```

3. 先做健康检查：

```powershell
curl.exe -sS http://127.0.0.1:5099/health
```

4. 健康检查通过后，把图片生成请求改发到：

```text
http://127.0.0.1:5099/v1/images/generations
```

5. 如果中转也失败，直接告诉用户 `change2pro` 当前在本环境不可用，不要假装已经生成成功

### 中转脚本说明

- 启动脚本：`C:/Users/Administrator/.agents/skills/image2-gen/scripts/start_change2pro_relay.ps1`
- 服务脚本：`C:/Users/Administrator/.agents/skills/image2-gen/scripts/change2pro_relay.py`
- 默认监听：`127.0.0.1:5099`
- 健康检查：`GET /health`
- 转发接口：`POST /v1/images/generations` 或 `POST /generate`

中转脚本是轻量本地 HTTP 服务，只做一件事：把本地请求原样转发到 `https://api.change2pro.com/v1/images/generations`，并尽量原样返回上游响应。

## 调用流程

### 1. 需求确认（必须先执行）

在生成之前，先通过 1-2 轮对话确认核心信息。按以下顺序收集，缺什么问什么，已有的跳过：

**第一轮（必问）：**

| 信息 | 说明 | 示例 |
|------|------|------|
| 📌 场景类型 | 海报 / PPT / Banner / 社交媒体图 / 公众号封面 / 通用生图 | "做什么类型的？" |
| 📌 主题/内容 | 活动名称、文章主题、产品名等核心内容 | "什么主题的海报？" |

**第二轮（按需补充）：**

| 信息 | 说明 | 默认值 |
|------|------|--------|
| 🖼️ 参考图 | 给一张想要模仿风格的图片（链接或本地路径） | 无，用默认风格 |
| 📝 要显示的文字 | 标题、副标题、活动详情等 | 模型根据主题自动生成 |
| 🎨 风格/配色 | 科技风、简约、暖色、冷色等 | 根据场景匹配默认风格 |
| 📐 尺寸 | 特殊尺寸需求 | 各场景默认值 |
| 🔲 二维码 | 是否需要替换二维码 | 生成后主动问 |

**交互原则：**
- 用户说"做张海报"→ 只需追问主题，其他给默认值
- 用户说"做张科技峰会海报，蓝色调"→ 已经够了，直接生成，不多问
- 用户给了详细描述 → 跳过所有追问，直接生成
- 用户给了参考图 → 先分析风格再生成，不额外追问风格细节
- **绝不一口气问超过 3 个问题**

### 2. 匹配场景

根据确认的信息匹配以下场景之一：

| 场景 | 关键词 |
|------|--------|
| 通用生图 | 画、生成、图片、插画、素材 |
| 海报设计 | 海报、宣传、活动、传单 |
| PPT 幻灯片 | PPT、幻灯片、演示、slides |
| 社交媒体图 | 封面、头图、小红书、公众号、抖音 |
| Banner | 横幅、轮播、网站头部 |
| 公众号封面 | 公众号、微信、文章封面 |

如果用户场景不在列表中，用通用生图模板，根据用户描述调整 prompt。

### 3. 构造 prompt

在「提示词模板」部分找到对应模板，将用户提供的具体内容（主题、文字、风格、配色等）填入模板中的占位符。

**关键原则：**
- gpt-image-2 能直接渲染中英文字，所以 prompt 中要明确写出需要显示的文字内容
- 尺寸、风格、配色等如果用户没指定，按模板默认值
- prompt 用英文写效果更稳定，中文内容（如标题、正文）保持中文原样嵌入 prompt

**如果有参考图（风格复刻）：**

用户提供参考图后，用 Read 工具查看图片，提取以下风格要素并写入 prompt：

```
Style reference analysis checklist:
1. Color palette — 提取主色、辅色、强调色，用色值或颜色名描述
2. Layout — 排版结构（居中/左对齐/上下分栏/网格）
3. Typography — 字体风格（粗体/细体/衬线/无衬线）、大小层级
4. Visual elements — 装饰元素（渐变/光效/几何图形/插画/照片）
5. Mood/overall feel — 整体氛围（专业/活泼/极简/奢华）
6. Background — 背景处理（纯色/渐变/模糊照片/纹理）
```

提取后，在 prompt 的 Style 部分用自然语言描述，例如：
```
Style: Replicate the visual style of the reference image —
dark gradient background with warm orange-to-purple transitions,
bold sans-serif typography with glowing text effects,
scattered geometric icons as decorative elements,
professional yet energetic tech conference feel.
```

不要逐像素复制，提取风格语言后用 gpt-image-2 的能力重新演绎。

### 4. 调用 API

先直连。如果失败，按上一节的兜底策略自动切到本地中转。

#### 4.1 直连调用

用 Bash 工具执行 curl 调用：

```bash
curl -s https://api.change2pro.com/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-5205fac8ce75120857f304d610e326d64eed7b5bb6674c4bce19da2604e554d8" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "<构造好的 prompt>",
    "n": 1,
    "size": "<尺寸>"
  }' | python -c "import sys,json,base64; d=json.load(sys.stdin); img=d['data'][0]; open('output.png','wb').write(base64.b64decode(img['b64_json'])) if 'b64_json' in img else print(img.get('url','no image data'))"
```

**响应处理：**
- 如果返回 `b64_json`：base64 解码保存为 PNG
- 如果返回 `url`：直接输出 URL 给用户
- 如果报错：检查 error message，常见问题是 prompt 过长、内容审核、余额不足

#### 4.2 本地中转调用（仅直连失败时）

先启动中转：

```powershell
powershell -File C:/Users/Administrator/.agents/skills/image2-gen/scripts/start_change2pro_relay.ps1
curl.exe -sS http://127.0.0.1:5099/health
```

再把同样的请求发给本地中转：

```bash
curl -s http://127.0.0.1:5099/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "<构造好的 prompt>",
    "n": 1,
    "size": "<尺寸>"
  }' | python -c "import sys,json,base64; d=json.load(sys.stdin); img=d['data'][0]; open('output.png','wb').write(base64.b64decode(img['b64_json'])) if 'b64_json' in img else print(img.get('url','no image data'))"
```

如果本地中转返回非 JSON、`502`、超时或和直连一样的 WAF 错误，停止重试，直接告诉用户当前环境下 `change2pro` 不可用。

### 5. 生成后检查与交付

按顺序执行，每一步都不能省略：

1. **查看结果**：用 Read 工具打开生成的图片，确认视觉效果和文字内容
2. **告知路径**：告诉用户文件保存路径
3. **检查文字**：如果生成的文字与用户要求不一致，主动指出并问是否需要重新生成（用强调措辞重写 prompt）
4. **二维码询问**：如果是海报/社交媒体图/公众号封面，主动问："需要替换二维码吗？发我你的二维码图片即可"
5. **调整意愿**：问用户是否需要调整（改文字、改配色、改布局、换风格）

---

## 提示词模板

### 通用生图

```
Generate a high-quality image: {description}.
Style: {style_defaults_to: photorealistic, modern, clean}.
Aspect ratio: {ratio_defaults_to: 1:1}.
Color palette: {palette_defaults_to: vibrant and harmonious}.
Lighting: {lighting_defaults_to: natural, soft shadows}.
Details: High resolution, professional quality, no watermarks.
```

默认尺寸：`1024x1024`

### 海报设计

```
Design a professional poster with the following specifications:

Main title: "{title}"
Subtitle/subtext: "{subtitle}"
Event details (date, location, etc.): "{details}"
Call to action: "{cta}"

Style: {style_defaults_to: modern minimalist, bold typography}.
Color scheme: {colors_defaults_to: deep navy blue + gold accents}.
Layout: Clear visual hierarchy, title prominent at top, details in structured sections.
Include decorative elements that match the theme.
Text must be in Chinese (Simplified) and clearly readable.
Size: portrait orientation, high resolution.
```

默认尺寸：`1024x1792`

### PPT 幻灯片

```
Create a presentation slide image with clean, professional design:

Slide title: "{title}"
Key points:
{bullet_points}

Notes for layout:
- Title at the top, large and bold
- Content organized with clear visual hierarchy
- Use icons or simple illustrations where appropriate
- {color_scheme_defaults_to: white background, dark text, accent color blue}
- {style_defaults_to: modern corporate, similar to premium PowerPoint templates}
- Plenty of whitespace, not cluttered
- All text in Chinese (Simplified), clearly readable
- Aspect ratio: 16:9 widescreen
```

默认尺寸：`1792x1024`

**多页 PPT：** 如果用户需要多页，逐页生成，每页保持一致的配色和风格。在 prompt 中追加：`Consistent style with previous slides: same color scheme, fonts, and layout language.`

### 社交媒体图（小红书 / 抖音 / 微博）

```
Create a social media cover image:

Main text: "{title}"
Supporting text: "{subtitle}"

Platform: {platform_defaults_to: Xiaohongshu (小红书)}.
Style: {style_defaults_to: eye-catching, trendy, with bold text overlay}.
Layout: Centered composition, text as the focal point.
Background: {background_defaults_to: gradient or abstract pattern matching the topic}.
Colors: {colors_defaults_to: warm, inviting, Instagram-style palette}.
Must include clear, large Chinese text that is easy to read on mobile screens.
Aspect ratio: {ratio_defaults_to: 3:4 for Xiaohongshu}.
```

各平台推荐尺寸：
- 小红书：`1024x1365`（3:4）
- 抖音封面：`1280x720`（16:9）
- 微博头图：`1920x1080`（16:9）

### Banner（网站 / 应用横幅）

```
Design a web banner:

Headline: "{headline}"
Subtext: "{subtext}"
CTA button text: "{button_text}"

Style: {style_defaults_to: modern, flat design, tech-forward}.
Layout: Horizontal, text on {side_defaults_to: left}, visual element on the other side.
Color scheme: {colors_defaults_to: gradient blue-purple, white text}.
Background: {background_defaults_to: abstract geometric shapes or subtle pattern}.
Text must be clearly readable, in Chinese (Simplified).
Aspect ratio: wide banner format.
```

默认尺寸：`1792x1024`

### 公众号封面

```
Create a WeChat Official Account article cover image:

Article title: "{title}"
Author/brand name: "{brand}"

Style: {style_defaults_to: clean, professional, editorial quality}.
Layout: Title prominently displayed, centered or upper-third placement.
Background: {background_defaults_to: subtle gradient or abstract art related to the topic}.
Colors: {colors_defaults_to: sophisticated palette, good contrast for readability}.
Chinese text must be large, clear, and readable at thumbnail size.
No stock photo watermarks. Aspect ratio: 2.35:1 (standard WeChat cover).
```

默认尺寸：`1920x816`

---

## 二维码替换

海报生成后，用户通常需要把 AI 生成的二维码替换成自己的真实二维码。流程如下：

### 1. 定位二维码区域

读取生成的图片，用 Read 工具查看图片，识别二维码的位置。告诉用户二维码的大概坐标：
- 左上角 (x, y)
- 宽度和高度 (w, h)

如果用户不满意，可以用 Python 快速生成带网格标注的辅助图帮助精确定位：

```bash
python -c "
from PIL import Image, ImageDraw, ImageFont
img = Image.open('output.png')
draw = ImageDraw.Draw(img)
w, h = img.size
step = 100
for i in range(0, w, step):
    draw.line([(i,0),(i,h)], fill='red', width=1)
    draw.text((i+2, 2), str(i), fill='red')
for j in range(0, h, step):
    draw.line([(0,j),(w,j)], fill='red', width=1)
    draw.text((2, j+2), str(j), fill='red')
img.save('grid_overlay.png')
print('OK: grid_overlay.png')
"
```

### 2. 替换二维码

用户提供自己的二维码图片路径后，用脚本替换：

```bash
python ~/.agents/skills/image2-gen/scripts/replace_qr.py \
  output.png your-qrcode.png --x 750 --y 1500 --w 200 --h 200 -o output-final.png
```

参数说明：
- `source` — 原始生成图
- `qr` — 用户的二维码图片
- `--x` `--y` — 二维码区域左上角坐标
- `--w` `--h` — 二维码区域宽高
- `-o` — 输出路径（不指定则覆盖原图）

脚本会：白底覆盖原区域 → 缩放用户二维码到指定尺寸 → 粘贴到目标位置 → 自动验证二维码可扫描性。

**验证逻辑：**
- 脚本自动用 OpenCV QRCodeDetector 检测替换后的图片中二维码是否可解码
- 输出 `QR_VALID: yes` → 二维码有效，放心交付
- 输出 `QR_VALID: no` → 二维码可能无法扫描，提醒用户自行用手机测试确认

---

## 交互规范

1. **信息不足时主动追问**：至少需要知道主题/内容，其他可以给默认值。问关键的 1-2 个问题就够了，别问太多。
2. **先出图再调**：不要反复确认风格细节，先按合理默认值生成，用户看了再说。
3. **多图批量**：如果用户需要多张（如一套 PPT、一组社交媒体图），用一个循环逐个生成，保持风格一致。
4. **尺寸优先级**：用户指定 > 场景默认值 > 1024x1024。
5. **输出路径**：默认保存到当前工作目录（`~/`），文件名用英文描述内容，如 `poster-tech-summit.png`。
6. **海报生成后主动提供二维码替换服务**：大多数海报/社交媒体图都有二维码区域，生成后主动告知用户可以替换。

## 实战经验（重要）

以下是首次运行中积累的经验，后续生成时需注意：

### 文字渲染行为

- gpt-image-2 会根据 prompt 语义**自主调整中文文字内容**。例如 prompt 写"2026 全球科技峰会"，模型可能输出"2026 人工智能大会"——它会根据视觉效果重新排版标题。
- **如果用户对文字有严格要求**（必须是某个特定标题），在 prompt 中用更强调的措辞：`The title MUST be exactly "XXX", do not change or rephrase the title text.` 同时用英文 prompt 结构包裹中文内容。
- 如果文字偏差不可接受，可以在生成后用 Pillow 直接在指定位置写文字覆盖（需要额外脚本）。

### 海报视觉效果

- gpt-image-2 在深色科技风海报上表现最好：深蓝/黑色背景 + 发光元素 + 几何图形。
- prompt 用英文写整体结构（风格、布局、装饰元素），中文只用于需要显示的文字内容。
- 背景和装饰元素模型有很强的自主发挥能力，不需要在 prompt 中过度指定——给大方向即可。

### 二维码定位经验

- 1024×1792 竖版海报中，二维码通常出现在右下角区域（x: 700-850, y: 1400-1600）。
- AI 生成的二维码不可扫描，必须用 `replace_qr.py` 替换。
- 替换后建议给二维码区域留 8-12px 白色边距，视觉更干净。
- 如果用户没有自己的二维码图片，可以先用 Python 生成一个：`pip install qrcode`，然后 `python -c "import qrcode; qrcode.make('https://example.com').save('qr.png')"`。

### 生成后检查清单

主流程步骤 5 已覆盖，此处仅补充注意事项：
- 文字偏差时，用 `MUST be exactly "XXX"` 强调后重新生成，而不是后期覆盖

## 可选尺寸列表

| 尺寸 | 适用场景 |
|------|---------|
| `1024x1024` | 正方形，通用 |
| `1024x1792` | 竖版，海报、手机壁纸 |
| `1792x1024` | 横版，Banner、PPT |
| `1920x816` | 超宽，公众号封面 |
| `1280x720` | 16:9，抖音封面、视频封面 |
