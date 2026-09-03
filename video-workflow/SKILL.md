---
name: video-workflow
user-invocable: true
description: >
  从一个主题出发，经深度调研（含事实核查与合规软化）→ 解说稿 → 视频分镜 → H3 AI
  画面（工作台批量）→ edge-tts 旁白 → Remotion 矢量合成（全程持续动画）→ 探针渲染
  低成本 QA → 15 服务器终渲，端到端产出一条 60–180 秒的 1080p 科普/讲解 MP4。
  两种模式：单人解说（默认，一个声音讲到底）与双人对谈（晓晓主持 + 云希专家）。
  当用户要"做一条讲解视频/科普视频/复盘片"，或已有调研素材要转成视频时使用。
  依赖：15 服务器 jszx-tl（10.10.127.15）SSH 与工作台 admin 通道（脚本 om_ssh.py、
  h3_batch.py 均 skill 自带；凭据运行时读桌面「服务器信息整理」最新日期版）、
  本地 python3 + edge-tts + ffmpeg + scrapling（选 BGM 用），渲染在 15 上完成
  （Remotion 4.x + Playwright chromium-1234）。
  不适用于：纯口播无画面、竖屏短视频（需改 composition）。
---

# 讲解视频生产 Skill（video-workflow）

把一个主题变成一条 60–180 秒、1920×1080、**全程有动画**的讲解 MP4。
H3 提供 AI 电影感 B-roll，Remotion 做矢量信息层（stat 卡/图表/时间轴/对比表/机制图），
edge-tts 出旁白（单人或双人），15 服务器远程渲染。QA 用「探针渲染」低成本闭环。

> 三次端到端验证：tundra_2《Qwen3.8 部署踩坑记》64s（双人）、ripple2《workbuddy》64s（双人）、
> shanghuo《你以为的上火=慢性炎症》111.7s（单人，2026-09-03）。完整运行手册样例 = 桌面
> `tundra_2_产出物合集/deliverables/HANDOFF.md`。

## 0. 前置与红线（先读）

- **SSH/凭据**：用 skill 自带 `scripts/om_ssh.py`，密码运行时从桌面「服务器信息整理」最新日期版读入内存，**不回显、不落盘、不进日志**。`~/.ssh/known_hosts` 须已有 10.10.127.15 的人工核验指纹。
- **H3 红线**：**禁止直连 16:18081**。H3 素材一律经 15 上 Molispark 工作台（127.0.0.1:18090）admin 批量通道，脚本 `scripts/h3_batch.py`（15 上 `/opt/data/om-deploy/h3_batch.py` 缺失时用 om_ssh.put 部署）。
- **H3 质量档位红线**：**禁用速度档 `vsa`（文字渲染几乎完全不可用）**；默认只用原生 `native`；太慢或排队过多时才允许回退均衡 `turbo_lora`，**回退后必须检查文字渲染**（qa_check 抽帧 + 底缘条带）。注意 `turbo` 别名已被工作台路由到 vsa 速度引擎，同样禁用（详见 §2④）。
- **渲染必带** `--browser-executable=/root/.cache/ms-playwright/chromium-1234/chrome-linux/chrome --gl=angle --concurrency=6 --public-dir=<项目public绝对路径>`（render_remote.py 已内置；缺 public-dir 会 404）。
- **确定性渲染**：index.tsx 禁 `Date.now()`/`Math.random()`，伪随机用固定种子 `h()`。
- **转场只用 {fade, cut, none}**；H3 素材 1344×768 cover 裁切 + 压暗。
- **健康/财经/法律内容必须做事实核查与合规软化**（见 §2①），片尾加免责声明。
- 先探针后终渲：探针（0.5x）约 3–4 分钟，终渲约 9 分钟。**禁止跳过探针直接烧终渲。**

## 1. 工作流总览（八步）

```
① 调研  →  ② 稿件  →  ③ 分镜  →  ④ H3 素材  →  ⑤ TTS  →  ⑥ Remotion 工程  →  ⑦ 探针 QA  →  ⑧ 终渲+验收
(核查+合规) (单人/双人) (帧表)   (工作台批量)  (rate拟合)  (持续动画铁律)   (0.5x 全片)   (qa_check.py)
```

每步产物是下一步输入；每步落盘 JSON/MD 再继续，中断可续。

### 目录约定（项目目录 = 当前工作目录下新建）

```
<project>/
├── article_full.md         # 原文存档（如从网页抓取，scrapling）
├── research.json           # ① 调研核查结果（事实+来源+置信度+合规注意）
├── script.md               # ② 解说稿
├── beats.json              # ③ 分镜帧表（权威源，见 templates/beats.example.json）
├── h3_batch.jsonl          # ④ H3 批次定义
├── clips/                  # ⑤ TTS wav + timing.json
├── bgm_candidates/         # BGM 候选（pick_bgm.py 下载）
├── public/
│   ├── assets/video/       # H3 mp4（h3_1.mp4 ... 命名与 index.tsx 引用一致）
│   ├── assets/audio/narration/  # 旁白 wav（从 clips/ 复制）
│   ├── assets/audio/bgm/   # 选定的 BGM
│   └── fonts/              # 渲染机上用软链复用（见坑表），本地可不放
├── index.tsx               # ⑥ Remotion atelier 工程
├── run_h3_batch.py         # 项目级：上传批次+阻塞生成（参考 article-video 项目）
├── qa_frames/              # qa_check.py 产出（抽帧/条带/响度报告）
└── final_<project>.mp4     # ⑧ 成片
```

---

## 2. 步骤详解

### ① 深度调研（多代理核查 + 合规软化）

起 1 个研究代理（或 4–5 个并行 + 1 个综合）用 WebSearch/WebFetch 核实稿件核心数字与机制声明：
- **每个事实带来源 URL + 置信度（high/medium/low）**；区分「当事人声称」与「独立核实」；数字要精确（单位/年份/口径）。
- 主动找反方证据与辟谣点；医疗健康内容重点核查：绝对化表述（"就是"→"与…相关"）、伪科学概念（如"肠漏症"非正式诊断但肠通透性是真实研究对象）、补剂/疗法证据强度。
- **合规软化**：把软化措辞直接写进分镜（片尾免责声明 + 场景内脚注），不要只留在调研文档里。
- 产出 `research.json`（facts/cautions/soundbites/citations）。

### ② 解说稿

- 单人模式：一个叙述者讲到底，语气跟主题走（犀利科普/冷静纪录）；双人模式：晓晓（X，zh-CN-XiaoxiaoNeural）主持提问 + 云希（Y，zh-CN-YunxiNeural）专家作答，"问—答"节奏。
- **语速预算（edge-tts 中文实测）**：含标点停顿约 **4.2–4.7 字/秒**（+8%~+15%）。初稿按 `window_s × 4.3` 字写，每个标点按 0.2s 计。超窗的 beat 要么删字、要么升 rate（+18%~+20% 是可懂度上限）、要么加长 window——TTS 步骤会精确报告。
- 每句 ≤20 字（字幕一行）；数字口语化但字幕显示阿拉伯数字。
- 总字数 ≈ 总时长 × 4.3。

### ③ 分镜帧表（beats.json）

```json
{"beat":1, "from":0, "dur":180, "rate":"+10%", "gap":0.15, "speaker":"Y",
 "visual_type":"h3", "h3_idx":1,
 "h3_prompt":"Cinematic ..., 16:9, no text, no watermark, no logos",
 "narration":"...", "speaker_lines":[{"spk":"Y","text":"..."}]}
```

- `from`/`dur` 为 30fps 帧，beat 之间**连续无缝**（下一 beat 的 from = 上一 from+dur）；总 dur = 总帧数 = 秒×30。
- `visual_type`: h3 | vector_stat | vector_chart | vector_timeline | vector_compare | vector_grid | vector_*(自定机制图)。
- **H3 两种用法**：① `duration:5` 原速配 150f 窗口；② **拉伸**——窗口 180f（6s）配 `playbackRate=0.8333`（=5/6），慢速更电影感且 H3 屏占更高。比例红线按"屏占"算：H3 beat 窗口帧数之和 / 总帧数 ≥ 用户要求（常见 ≥1/3）。
- H3 prompt：英文、电影感、运动镜头、`no text, no watermark, no logos`。**no text 不保证真没字**——生成后必须查底缘（§4 第 5 步）。
- 节奏设计：钩子（H3）→ 揭示（矢量）→ 机制（矢量为主）→ 数据卡 → 清单 → 金句（H3）→ 结尾+免责。矢量场景承担信息密度，H3 承担情绪与呼吸。
- 时长目标 90–120s 最稳（60s 太赶、180s 渲染太久）。

### ④ H3 批量生成（工作台 admin 通道）

**质量档位政策（2026-09-03 用户拍板，文字渲染实测结论）：**

| 档位 | quality 值 | 步数 | 文字渲染 | 实测耗时中位数（工作台口径） | 政策 |
|---|---|---|---|---|---|
| 原生 | `native` | 50 | **最好** | 5s≈266s / 7s≈473s / 15s≈1452s | **默认，唯一常规档** |
| 均衡 | `turbo_lora` | 9 | 中等，需检查 | 5s≈50s / 10s≈135s / 15s≈256s | 仅当原生太慢或排队过多时回退；**回退后必须检查文字渲染** |
| 速度 | `vsa`（4步，`turbo` 别名同路由） | — | **几乎完全不可用** | — | **禁用**，h3_batch.py 会直接拒绝 |

1. beats 里的 h3_prompt 转 jsonl：`{"prompt":"...","task":"t2va","duration":5,"ar":"16:9","out":"/opt/data/om-deploy/out/<proj>_h3_N.mp4"}`（duration 5–15 整数；**native 档下务必用 5s**——15s 原生一条约 24 分钟）。
2. 上传批次到 15 并运行（凭据经 `om_ssh.run_env` 注入，参考工作区 `article-video/run_h3_batch.py`）：
   `cd /opt/data/om-deploy && /opt/py312/bin/python3.12 h3_batch.py --batch <proj>.jsonl --wait-all`
   行内没写 `quality` 时默认 **native**；排队过多/赶时间回退均衡：加 `--quality turbo_lora`（无需改 jsonl）。
3. `--wait-all` 自动 ffprobe 校验（时长/1344×768/h264+aac）。native 串行要有耐心：7×5s 约 30 分钟；排队过多时可先只等 done 再评估是否回退。
4. **回退均衡后的文字检查（必做）**：qa_check.py 的抽帧 + H3 底缘条带重点看假字幕/烂字；出现烂字的镜头重生成或改构图避开文字。
5. **素材直接在 15 上复用**：`cp /opt/data/om-deploy/out/<proj>_h3_*.mp4 <项目public>/assets/video/` 并**重命名为 h3_N.mp4**（与 index.tsx 引用一致）——不要 SFTP 绕道本机。本地留档可再拉一份。
6. **底缘烙印检查**（必做，native 也可能出）：抽每条底部条带人工看一眼：
   `ffmpeg -ss 2 -i h3_N.mp4 -frames:v 1 -vf "crop=1344:120:0:648" strip_N.png`
   有字的片段在 H3Clip 里加基础放大（zoomFrom≥1.2；qa_check.py 会自动生成条带图）。

### ⑤ TTS（edge-tts，单人/双人）

```bash
python scripts/make_tts.py --beats beats.json --out clips/ --voice-Y zh-CN-YunxiNeural
# 单人模式：beats.json 里所有 speaker_lines 的 spk 都写同一个（如全 "Y"），--voice-Y 选音色。
# 双人模式：X=晓晓 Y=云希，按 speaker_lines 逐句切换。
```

- 语音选择参考：云希 Yunxi（年轻男、活泼，犀利科普）/ 云扬 Yunyang（新闻腔）/ 晓晓 Xiaoxiao（女声）。
- 脚本输出每段 `total/window`，**OVER 就调该段 rate 或删字重跑**，直到全 OK（超窗会 exit 1 并列出）。
- 产物：24kHz mono wav（窗长补静音）+ `clips/timing.json`（逐句精确 start/dur，字幕时间轴从这里换算）。

### ⑥ Remotion atelier 工程（持续动画铁律）

单文件 `index.tsx`，自包含，基于 `templates/index.tsx`（骨架）+ `templates/index.full_example.tsx`（10 种场景完整实现）。

**六条铁律（违反 = 黑屏/豆腐块/动画缺失，全部实战踩过）：**
1. **场景包一层 `SceneShell`（内部 SceneFade 子组件）**。SceneFade 是真组件、在 Sequence 内 useCurrentFrame 取相对帧——**禁止在 Sequence 外的 IIFE 里调 useCurrentFrame**（取到全局帧 → 除第一景外全部黑屏）。
2. **场景内所有延迟入场的叠加层，必须写在组件里**（用模板的 `Reveal`/`Tag`/`Stamp`，内部 useCurrentFrame）。**禁止内联 `opacity: seg(0,…)`**——帧号硬编码 0，永不显示。
3. **禁 emoji**：渲染机无彩色 emoji 字体，一律汉字/CSS 图形（火焰=CSS 圆角条、微生物=汉字「菌」等）。
4. **含中文的文本禁用裸 mono 字体链**（`"DejaVu Sans Mono", Menlo, monospace` 结尾无 CJK → 豆腐块）。混排数字+中文用 `'"DejaVu Sans Mono","Noto Sans SC",monospace'`（Noto 兜底）。
5. **全局动效层**（EmberField 粒子/顶部进度条）+ 每个 H3Clip Ken Burns + 每个矢量场景至少一个持续动画（spring 入场、描画、脉冲），满足"不是图文讲解"的要求；关键信息落定后仍 hold ≥1s。
6. 字幕预算每行 ≤20 字、多句 cue 按字符占比切分 TTS 时长；底部 260px 是字幕区，场景文字别压进来。

其余：三张时间线表（NARRATION/SFX/SUBTITLES 从 timing.json 换算）、BGM_ENVELOPE 预计算、确定性伪随机 `h()`、字体 FontGate。

### ⑦ 探针渲染（低成本 QA 闭环）

```bash
# 语法预检（5 秒，避免浪费一整轮渲染）
npx esbuild index.tsx --loader:.tsx=tsx --outfile=/dev/null

# 0.5x 探针（全片 960×540，约 3-4 分钟）
python scripts/render_remote.py --project <proj> --composition Explainer \
  --local-public ./public --local-index ./index.tsx --duration-s <秒> --scale 0.5 \
  --wait --out ./probe.mp4
```

- 抽帧审查**全部场景**：采样点用帧表算**场景中点**（`from+dur/2` 换算秒，避开首尾 10% 的转场淡入淡出）；草算时间戳容易踩进下一场景的 fade。
- 重点看：每景内容真的渲染了（防黑屏）、emoji/豆腐块、文字重叠/溢出、H3 底缘烙印、字幕对齐。
- 修完再探针（快），收敛后才烧终渲。**每轮修复必须收敛所有问题，别一景一修。**

### ⑧ 终渲 + 自动验收

```bash
python scripts/render_remote.py --project <proj> --composition Explainer \
  --local-public ./public --local-index ./index.tsx --duration-s <秒> \
  --wait --wait-timeout-s 2400 --out ./final_<proj>.mp4

python scripts/qa_check.py --video ./final_<proj>.mp4 --beats beats.json --public ./public
```

qa_check.py 自动做：ffprobe 规格（时长=帧数/fps、1080p、h264+aac）、**H3 屏占比红线**、按帧表抽全部场景中点帧 + **H3 素材底缘条带图**（供人工目检）、代表性窗口响度（旁白/床/淡出）。
人工目检 qa_frames/ 后才算过；有问题 → 修 → 探针 → 终渲 → 重跑 qa_check，直到全过。

---

## 3. 验收清单

- [ ] qa_check.py 全绿：时长=帧数/fps、1920×1080、h264+aac、H3 屏占 ≥ 要求
- [ ] 抽帧目检：每场景内容可见（无黑屏）、无 emoji/豆腐块、无文字重叠溢出、H3 底缘干净
- [ ] 时间轴：旁白/画面/字幕对齐（字幕 from/to 来自 timing.json）
- [ ] 听感：无截断吞字（TTS 全 OK 是前置）
- [ ] 数字与 research.json 一致，来源可查；合规软化到位、免责声明在片尾
- [ ] 混音：旁白峰值 ≥ -10dB、床 ≤ -28dB、结尾淡出干净
- [ ] 可复现：beats.json + index.tsx + timing.json + research.json 落盘

## 4. 常见坑（实战全录）

| 坑 | 解法 |
|---|---|
| **除第一景外全部黑屏** | SceneShell 里 IIFE 调 useCurrentFrame 取到全局帧——必须 SceneFade 子组件（模板已修；full_example 一直是对的） |
| **内联 `seg(0,…)` 叠加层永不出现** | 帧号硬编码 0；场景动画必须写在取相对帧的组件里（Reveal/Tag/Stamp） |
| **渲染机 emoji 豆腐块** | 无彩色 emoji 字体；用汉字/CSS 图形 |
| **CJK 套裸 mono 链** | `"DejaVu Sans Mono", Menlo, monospace` 结尾无中文字形；链里必须插 `"Noto Sans SC"` |
| **H3 素材底缘有模型烙印文字** | no text 不保险；底缘条带检查 + H3Clip 基础 zoom ≥1.2 裁掉 |
| 旁白超窗被截断 | make_tts.py 会报 OVER；删字或升 rate（≤+20%） |
| remotion render 404 asset | 缺 `--public-dir`；render_remote.py 已内置 |
| 渲染 0.5fps | `--gl=angle` |
| chromium 下载失败 | `--browser-executable` 指 playwright chromium-1234 |
| 15 上换 BGM 后上传写穿软链 | 软链指向 qwen38-deploy 共享目录；先 `rm` 软链 `mkdir` 实体目录再上传 |
| 探针抽帧踩到转场黑帧 | 采样点用帧表算场景中点，别拍脑袋估时间 |
| esbuild/语法错误浪费一轮渲染 | 渲染前 `npx esbuild index.tsx --loader:.tsx=tsx --outfile=/dev/null` |
| 重用 project 有旧素材 | 用新 project slug 或 `--clean-remote` |
| H3 直连 16:18081 | 红线；只走工作台 admin 通道 |
| **`quality=turbo` 被路由到 vsa 速度引擎** | 工作台 select_backend 把 turbo 别名转 vsa（速度档文字烂）；h3_batch.py 已默认 native 并拒绝 vsa/turbo |
| **速度档（vsa）文字几乎不可用 / 均衡档文字需检查** | 原生 native 是唯一常规档；回退 turbo_lora 后必须跑 qa_check 查文字 |

## 5. BGM 选曲与音量标定

```bash
python scripts/pick_bgm.py --list --tag ambient --min-sec 110     # 列候选（Mixkit 免费商用免署名）
python scripts/pick_bgm.py --download <mp3_url> --out public/assets/audio/bgm/bgm-x.mp3
```

- FreePD 已关站（2026-09 核实）；Mixkit 可用，JSON-LD 直链下载稳定。备选：用户自备文件（零版权风险）。
- **响度标定**（脚本会算）：目标床响度 ≈ **-30dB mean**，`乘数 = 10^((-30 - 曲目mean_dB)/20)`；闪避 = 乘数 × 0.4。写入 BGM_ENVELOPE。
- 走 render_remote 上传前，15 上该项目的 `bgm` 必须是实体目录（见坑表）。

## 6. 单人 vs 双人差异

| 项 | 单人（默认推荐） | 双人 |
|---|---|---|
| speaker_lines | 全部同一 spk | X/Y 交替，问—答节奏 |
| 音色 | 自选一个（云希/云扬/晓晓） | 晓晓+云希 |
| SpeakerBadges | 删掉 | 左下双人角标谁说谁亮 |
| 字幕着色 | 单色白字 | 按 spk 着色 |
| 适型 | 科普/复盘/叙事 | 观点对撞/访谈感 |

## 7. 文件索引

- `scripts/make_tts.py` — TTS 生成（beats.json → wav + timing.json；单人/双人通用，原 make_duo_tts.py）
- `scripts/render_remote.py` — 部署+远程渲染+拉回（支持 `--scale 0.5` 探针）
- `scripts/qa_check.py` — 自动验收（规格/H3占比/抽帧/底缘条带/响度）
- `scripts/pick_bgm.py` — Mixkit 选曲 + 响度标定
- `scripts/om_ssh.py` — SSH 助手（凭据运行时读桌面服务器清单）
- `scripts/h3_batch.py` — H3 工作台批量（可部署到 15 /opt/data/om-deploy/）
- `templates/index.tsx` — 工程骨架（SceneFade/Reveal/H3Clip/EmberField 可直接抄）
- `templates/index.full_example.tsx` — 10 种矢量场景完整实现
- `templates/beats.example.json` / `templates/h3_batch.example.jsonl`
- `references/remotion-patterns.md` — 矢量组件与渲染规则细节
- `references/h3-workbench-api.md` — 工作台 API 契约
- 参考成片/手册：桌面 `tundra_2_产出物合集/`（64s 双人+完整 HANDOFF）、`ripple2/`、工作区 `article-video/`（111.7s 单人，research.json/qa 流程全档）
