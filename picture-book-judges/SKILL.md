---
name: picture-book-judges
description: 面向摩力 AI 亲子公益沙龙（如第七期《空白谜案》及后续亲子 AI 绘本活动，约 20 组家庭）的绘本评奖 skill。支持解析单文件 StPageFlip 翻页绘本 HTML（完整跳过头部 44KB 引擎库）、story.json 或图片目录及 zip 包，生成轻量化图文评审摘要与拼接接触表（review-assets/），由调用方 Agent 分批进行多模态图文评审后，产出离线自包含的 3D 翻牌颁奖页 index.html、规范化 scores.json，以及供现场手写实物奖状核对的 UTF-8 BOM 汇总表 awards-summary.csv。不做批量电子奖状。
user-invocable: true
---

# Picture Book Judges（亲子 AI 绘本评奖）

## Overview

面向亲子 AI 绘本创作活动的离线评奖与颁奖展示工具。针对绘本作品图文并重、单文件翻页 HTML 头部包含约 44KB StPageFlip 引擎库的特点，采用**无截断数据解析 + 轻量化接触表（contact sheet）视觉评审 + 离线 3D 翻牌颁奖页 + Excel 友好 CSV 名单**流程。

三大默认奖项：**最佳故事奖**、**最佳画面奖**、**最佳创意奖**（支持 `--awards` 自定义任意 3 个奖项）。
支持约 20 组家庭规模，默认通过蛇形分配（snake draft）均匀分布到三个奖项（如 7 / 7 / 6），保证每组作品恰好归属一个奖项。

## When to Use

- 收到亲子 AI 绘本作品集合（`.zip` 压缩包或本地目录），包含 `picture-book` / `绘本组装工具.html` 导出的单文件 `.html`、`story.json` + 配图目录，或散装图片目录。
- 需要结合**故事文本 + 实际画面**完成多维度评分与鼓励式评语。
- 需要现场大屏可离线打开的 3D 翻牌颁奖典礼页面 `index.html`，以及方便现场手写实物奖状与核对的 `awards-summary.csv`。

## When Not to Use

- 小游戏/编程项目评奖请使用 `children-game-judges`；视频作品评奖请使用 `video-judges`。
- 本 skill **不做批量电子奖状**（不生成电子奖状 HTML/PNG/PDF 模板或批量导出器）；现场手写实物奖状请直接核对 `awards-summary.csv`。

## Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--input` | Yes | — | 作品目录或 `.zip` 压缩包路径 |
| `--output` | Yes | — | 输出目录（必须与 `--input` 分离，不得嵌套在其内部） |
| `--awards` | No | `最佳故事奖,最佳画面奖,最佳创意奖` | 恰好 3 个英文逗号分隔的奖项名称 |
| `--event` | No | `摩力AI亲子公益沙龙 · 第七期《空白谜案》` | 首页顶部活动徽章文案 |
| `--title` | No | `小小绘本创作家` | 首页主标题 |
| `--subtitle` | No | `AI绘本作品颁奖典礼` | 首页副标题 |
| `--logo` | No | 无 | 可选 Logo 图片路径（可重复传入，支持 `路径\|替代文本`；文件缺失时打印告警并优雅跳过） |
| `--music` | No | `assets/award-music.mp3` | 自定义背景音乐 MP3 路径；默认资源缺失时静默降级 |
| `--no-music` | No | `false` | 禁用背景音乐内嵌（可明显减小 `index.html` 体积） |

## Supported Input Formats

脚本按以下顺序兼容识别参赛作品（不设固定字节截断）：

1. **顶层单文件绘本 HTML**：`<姓名>-<作品名>.html` 或 `<作品名>.html`（`绘本组装工具.html` 默认导出形态）。自动跳过头部 StPageFlip 引擎 JS，提取完整 `TITLE`、`AUTHOR`、`DATE`、`COVER`、`PAGES`。
2. **`姓名-作品名/` 子目录**：
   - 优先解析目录内的 StPageFlip `.html`/`.htm`（若发现多个 HTML 会记录告警）；
   - 其次解析 `story.json` + 目录内（或 `out/`、`images/`、`imgs/`）配图；
   - 再次解析散装图片（自然排序，`cover` 优先作为封面）+ 可选 `.txt`/`.md` 脚本文字。
3. **非标准 HTML 降级**：提取 `<title>`、`<img>` 与段落文字并附带告警。

> **异常与重复提交提醒**：空目录、无法解析的文件、不支持的顶层文件会记录到 `stderr` 与 `manifest.json` 的 `warnings` 字段中，不会静默吞错；若检测到 `(作者, 作品名)` 重复提交，会明确提示核对活动规则（「重复提交评委只看第 1 份」）。

## Workflow

### 1. Discovery（提取文本与生成视觉接触表）

先运行探索模式（此时 `<output>/scores.json` 尚不存在）：

```bash
python -B scripts/judge.py --input <submissions_dir_or_zip> --output <output_dir>
```

脚本会在 `<output_dir>` 下生成：
- `manifest.json`：精简结构化元数据（不含 base64 大图），含每本书的 `id`、`author`、`project`、`page_count`、每页 `text` 与 `warnings`。
- `review-assets/<id>-cover.jpg`：轻量化封面缩略图。
- `review-assets/<id>-sheet.jpg`：按每张最多 16 格（4 列网格）拼接的绘本接触表，每格顶部标有清晰页码（`COVER`、`P01`、`P02`…），体积可控（通常 120–250 KB/本）。

### 2. 分批图文多模态评审（约 20 组规模）

为避免撑爆上下文，按 **每批 4–5 本** 分批评审：

1. 读取 `<output_dir>/manifest.json` 中的故事文字与页数信息。
2. 直接查看本批作品对应的 `review-assets/<id>-sheet.jpg`（必要时辅以 `<id>-cover.jpg`），重点核查：
   - **故事是否通顺完整**：是否具备起承转合 / 冒险开端、探索、危机与破局。
   - **角色与画风一致性**：跨页主角的服装、发型、配色是否稳定，有无明显多手指或畸形。
   - **图文契合与汉字准确性**：文字与当页场景/动作/景别是否呼应，画面内的「」短汉字（书名、石碑、路牌等）是否准确。
3. 为每组作品给出 5 项评分（0–20）、3 条具体鼓励式闪光点（`strengths`）与 1 条建设性下一步挑战（`suggestion`）。

### 3. 写入 `scores.json` 并生成交付物

将全部评审结果写入 `<output_dir>/scores.json`，然后再次运行同一命令：

```bash
python -B scripts/judge.py --input <submissions_dir_or_zip> --output <output_dir> [--logo path/to/logo.png]
```

脚本将产出：
- `index.html`：离线单文件 3D 翻牌颁奖页（内嵌压缩后的封面与最多 4 张代表内页缩略图，支持点击放大预览、礼花动画、可选背景音乐、移动端与桌面大屏自适应）。
- `scores.json`：规范化后的评分与最终奖项分配备份。
- `awards-summary.csv`：UTF-8 with BOM（`utf-8-sig`）编码的现场核对汇总表，含中文字段与 Excel 公式注入防护。

## Scoring Dimensions & Rubric

每项 0–20 分，总分 100 分：

| Dimension | Focus |
|---|---|
| `故事结构与完整性` | 起承转合是否完整（开场、探索、危机、破局），故事节奏与童趣感染力 |
| `画面表现与角色一致性` | 角色外观服饰跨页是否一致、构图景别变化、色彩氛围与画面完整性 |
| `创意想象力` | 世界观设定、道具法宝、危机冲突与机智破局点的新奇度 |
| `图文契合度` | 文字与画面动作/情绪是否呼应，画面中汉字（书名、路牌等）是否准确 |
| `完成度与细节` | 封面设计、页数（建议 8–12 页）、文字可读性及整体打磨度 |

### 鼓励式打分指导（95+ 分段）

面向儿童与亲子创作，评语保持温暖鼓励，常规作品基准 **19 分/项**（总分 **95–96** 参与佳作，**96–97** 优秀作品，**97–99** 突出佳作，**20 分**留给特别惊艳的亮点），轻微瑕疵可记至 18 分或偶见 17 分，整体保持 **95 分以上**。

## Awards & Distribution

默认三奖项与对应维度优先级（用于手动指定部分 `winnerIds` 后对剩余作品自动匹配）：

- **最佳故事奖**：`故事结构与完整性 > 创意想象力 > 图文契合度 > 完成度与细节 > 画面表现与角色一致性`
- **最佳画面奖**：`画面表现与角色一致性 > 图文契合度 > 完成度与细节 > 创意想象力 > 故事结构与完整性`
- **最佳创意奖**：`创意想象力 > 故事结构与完整性 > 画面表现与角色一致性 > 图文契合度 > 完成度与细节`

### 均匀蛇形分配（默认）

当 `scores.json` 中所有奖项均未填写 `winnerIds`（或 `winnerId`）时，按总分降序（同分按 `id` 降序稳定打破）进行蛇形分配（round 0: 0→1→2，round 1: 2→1→0…），20 组家庭固定分布为 **7 / 7 / 6**，确保每组作品有且仅有一个奖项。

### 手动指定覆盖

在 `scores.json` 的 `awards` 中填入 `winnerIds`（支持 `book-001` 或原始 `key`，也兼容单值 `winnerId`）。脚本会自动跨奖项去重，先补齐空奖项，再按维度优先级为其余未分配作品匹配最契合的奖项。

## `scores.json` Schema

```json
{
  "version": 1,
  "participants": [
    {
      "id": "book-001",
      "author": "阿砚",
      "project": "云梦仙踪",
      "scores": {
        "故事结构与完整性": 20,
        "画面表现与角色一致性": 19,
        "创意想象力": 20,
        "图文契合度": 19,
        "完成度与细节": 19
      },
      "strengths": [
        "白玉镇纸化作小墨龙的开场奇巧自然，四幕冒险节奏紧扣",
        "阿砚的青色汉服与小墨龙造型跨页高度稳定，远景悬空寺震撼",
        "「云梦泽」石碑汉字清晰准确，书卷龙形墨印结尾余韵十足"
      ],
      "suggestion": "可以试着给山灵加一句专属台词，让迷雾引路那一幕更有互动感！"
    }
  ],
  "awards": [
    {"id": "best-story", "title": "最佳故事奖"},
    {"id": "best-art", "title": "最佳画面奖"},
    {"id": "best-creativity", "title": "最佳创意奖"}
  ]
}
```

## `awards-summary.csv` Fields

输出使用 `utf-8-sig`（UTF-8 with BOM）与 CRLF 行尾，Windows Excel 双击直接正常显示中文；并对以 `=`、`+`、`-`、`@`、Tab、CR 开头的字符串单元格自动前置 `'` 以防止电子表格公式注入。

字段顺序：`奖项, 奖内序号, 总序号, 作者/姓名, 作品名, 总分, 故事结构与完整性, 画面表现与角色一致性, 创意想象力, 图文契合度, 完成度与细节, 评价等级, 一句话闪光点/颁奖词, 下一步挑战, 页数, 来源文件, 作品ID`。

## Notes & Constraints

- **绝不调用外部 LLM API 或外网 CDN**：`index.html` 完全离线自包含，评分与图文理解由调用方 Agent 完成。
- **不做批量电子奖状**：现场手写实物奖状直接以 `awards-summary.csv` 为准。
- **输入输出目录隔离**：`--output` 不得与 `--input` 相同或嵌套在其内部（脚本会主动拦截报错）。
- **XSS 与转义**：作者名、书名、评语在 HTML 与内联 `<script>` JSON 中均做严格转义（含 `<`/`>`/`&`）。
