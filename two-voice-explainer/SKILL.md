---
name: two-voice-explainer
user-invocable: true
description: >
  从一个主题出发，经多代理深度调研 → 双人对谈稿件 → 视频分镜 → H3 AI 画面 +
  edge-tts 双人旁白 → Remotion 矢量合成 → 15 服务器远程渲染，端到端产出一条
  60–180 秒的双人对谈式讲解视频（晓晓主持 + 云希专家）。当用户要"做一条讲解视频/
  科普视频/双人播客视频/Blueprint 式复盘"，或已有调研素材要转成双人解说片时使用。
  依赖：15 服务器 jszx-tl（10.10.127.15）SSH 与工作台 admin 通道（SSH 助手
  scripts/om_ssh.py、H3 批量脚本 scripts/h3_batch.py 均 skill 自带；凭据运行时
  读桌面「服务器信息整理」最新日期版）、本地 python3 + paramiko + edge-tts +
  ffmpeg，渲染在 15 上完成（Remotion 4.x），不依赖任何特定工作区。
  不适用于：纯口播无画面、单人解说、竖屏短视频（需改 composition）。
---

# 双人对谈讲解视频生产 Skill

把一个主题变成一条 60–180 秒、1920×1080、双人对谈（晓晓主持 + 云希专家）的讲解 MP4。
H3 提供 AI 电影感 B-roll，Remotion 做矢量信息层（stat 卡/图表/时间轴/对比表），
edge-tts 出双人旁白，15 服务器远程渲染。

> 参考成片（可选阅读，位于 sextant2 工作区 deliverables/ 与 blueprint/）：
> - `deliverables/final_qwen38-deploy_duo.mp4`（64s，技术踩坑复盘）
> - `blueprint/RESEARCH_AND_PRODUCTION_PLAN.md`（180s 抗衰科普，调研→分镜全流程样例）

## 0. 前置与红线（先读）

- **SSH/凭据**：用 skill 自带 `scripts/om_ssh.py`，密码运行时从桌面「服务器信息整理」最新日期版读入内存，**不回显、不落盘、不进日志**。SSH 客户端要求 `~/.ssh/known_hosts` 已有 10.10.127.15 的人工核验指纹；不会自动接受未知主机密钥。
- **H3 红线**：**禁止直连 16:18081**。H3 素材一律经 15 上 Molispark 工作台（127.0.0.1:18090）admin 批量通道，脚本 `scripts/h3_batch.py`（skill 自带；15 上 /opt/data/om-deploy/h3_batch.py 缺失时用 om_ssh.put 部署）。
- **渲染必带** `--browser-executable=/root/.cache/ms-playwright/chromium-1234/chrome-linux/chrome --gl=angle --concurrency=6`。
- **确定性渲染**：index.tsx 禁 `Date.now()`/`Math.random()`，伪随机用固定种子 `h()`。
- **转场只用 {fade, cut, none}**；H3 素材 1344×768 cover 裁切 + 压暗 0.55。
- 不构成医疗/财务/法律建议时，相关主题在片尾加免责声明。

## 1. 工作流总览（七步）

```
① 调研  →  ② 稿件  →  ③ 分镜  →  ④ H3 素材  →  ⑤ 双人 TTS  →  ⑥ Remotion 工程  →  ⑦ 远程渲染
  (多代理)  (对谈稿)   (beat表)   (工作台批量)   (edge-tts)    (index.tsx)      (15 服务器)
```

每一步的产物是下一步的输入；建议每步完成后落盘 JSON/MD 再继续，便于中断续做。

### 目录约定（在当前工作目录下建项目目录，不依赖任何固定工作区）
```
<project>/
├── research.json          # ① 多代理调研原始结果
├── script.md              # ② 双人对谈稿
├── beats.json             # ③ 分镜表（见 templates/beats.example.json）
├── h3_batch.jsonl         # ④ H3 批次定义
├── clips/                 # ⑤ edge-tts 产出的 wav + timing.json
├── public/
│   ├── assets/video/      # H3 mp4（从 15 拉回）
│   ├── assets/audio/narration/  # 双人 wav
│   ├── assets/audio/bgm|sfx/
│   └── fonts/             # Noto Sans/Serif SC VF
├── index.tsx              # ⑥ Remotion atelier 工程
└── final_<project>.mp4    # ⑦ 成片（从 15 拉回）
```

---

## 2. 步骤详解

### ① 多代理深度调研

用 Workflow 起 4–5 个研究代理并行联网核实，再 1 个代理综合。
维度按主题选，通用四维度：**核心事实/数据**、**机制/How**、**争议/反方/风险**、**受众（25 岁年轻人）适配**。

要求每个代理：
- 用 WebSearch/WebFetch 核实，**每个事实带来源 URL 和置信度（high/medium/low）**；
- 区分"当事人声称"与"独立核实"；
- 数字要精确（带单位、时间、版本）；
- 主动找反方证据和该主题的"翻车/辟谣"点。

综合代理产出 `research.json`：
```json
{
  "title": "...", "logline": "一句话钩子",
  "key_facts": [{"fact":"","number":"","dimension":"","source":"","confidence":""}],
  "soundbites": ["可直接做旁白的金句"],
  "cautions": ["风险/辟谣/合规点"],
  "citations": ["url"]
}
```
> 真实调研产物样例（5 代理、143 次工具调用）在 sextant2 的 `blueprint/research_raw.json`（可选阅读）。

### ② 双人对谈稿件

两个角色：
- **晓晓（X，女，zh-CN-XiaoxiaoNeural）**：主持/观众代言人——提问、抛钩子、说"这也太极端了吧"、做受众落点。
- **云希（Y，男，zh-CN-YunxiNeural）**：专家——讲事实、数字、机制、反方观点。

写作原则：
- 每句 ≤20 字（字幕一行放得下），长句按语义断两行；
- 数字口语化但字幕可显示阿拉伯数字（"百分之六十六"念，"66%"显示）；
- 形成"问—答"或"引子—细节"节奏，保留少量反应词（"结果""更隐蔽的是""呢"）；
- 按信息块切句，每句对应一个 H3 B-roll 或一个矢量画面；
- 总字数 ≈ 时长(s) × 4.5（中文旁白约 4.5 字/秒，含停顿）。

落盘 `script.md`，按"X:/Y:"标角色。

### ③ 视频分镜（beats.json）

把稿件拆成 beat 表。每个 beat 是一个画面单元：
```json
{
  "beat": 1, "from": 0, "dur": 300,  // from/dur 均为 30fps 时间线帧（10 秒）
  "speaker": "X",           // X | Y | both
  "visual_type": "h3",      // h3 | vector_stat | vector_chart | vector_timeline | vector_compare | vector_grid | title
  "h3_prompt": "英文 prompt...",  // visual_type=h3 时
  "vector": {...},          // visual_type=vector_* 时的数据
  "narration": "旁白文本",
  "speaker_lines": [{"spk":"X","text":"..."}]  // 本 beat 内逐句（多句=多人切换）
}
```

**H3 时长硬约束**：工作台 `duration` 是 **5–15 整数秒**，做不了 3s。要 ≥30s H3 就用 6–7 段 5s。
H3 prompt 要求：英文、电影感、16:9、5s、**no text/no watermark/no logos**（H3 渲染不好文字，所有文字走矢量层）。
`sum(dur)/30` = 总时长（秒）；`sum(h3 duration)` ≥ 需求（通常 ≥30 秒）。H3 批次里的 `duration` 是 5–15 的整数秒，和 beats 的 `dur` 帧字段不是同一单位。

### ④ H3 批量生成

0. 首次使用先确认 15 上 `/opt/data/om-deploy/h3_batch.py` 存在；缺失时用
   `om_ssh.put("scripts/h3_batch.py", "/opt/data/om-deploy/h3_batch.py")` 部署到 15。
1. 把 beats 里所有 `h3_prompt` 转成 jsonl（一行一片）：
   ```json
   {"prompt":"...","task":"t2va","duration":5,"ar":"16:9","out":"/opt/data/om-deploy/out/<proj>_h3_1.mp4"}
   ```
   参考 `templates/h3_batch.example.jsonl`。
2. 将批次文件和 `scripts/h3_batch.py` 放到 15 的 `/opt/data/om-deploy/`（15 已有同版本脚本时可跳过）。
3. 在 15 上显式注入工作台环境变量后运行：
   ```bash
   # H3_WORKBENCH_USER / H3_WORKBENCH_PASS 由调用方运行时注入，不写入命令历史或日志
   cd /opt/data/om-deploy && /opt/py312/bin/python3.12 h3_batch.py \
     --batch <proj>.jsonl --wait-all
   ```
   从本机编排时，可用 skill 自带 `om_ssh.workbench_admin()` 读取桌面凭据后，通过 `om_ssh.run_env()` 经 SSH stdin 注入；`h3_batch.py` 本身只读取环境变量，不自动读取凭据文件。
   `--wait-all` 会阻塞到全部终态并逐条 ffprobe 校验（时长、画幅、1344×768、h264/aac）。
4. 拉回 mp4 到 `public/assets/video/`。

语义：阻塞等待完整生成（引擎并发=1，串行不损吞吐）；断点续跑凭 task log 重挂不重复提交；失败可 `--retry-failed`。详见 `references/h3-workbench-api.md`。

### ⑤ 双人 TTS

用 skill 自带的 `scripts/make_duo_tts.py`：
- 输入 `beats.json`，按 `speaker_lines` 逐句 edge-tts 合成；
- 每段（beat 或 narration 窗口）拼接，句间插 0.15–0.22s 静音；
- **按段单独调 `rate`（+8%~+40%）**，让拼接总时长 ≤ 窗口秒数，避免被 `-t` 截断吞尾字；
- 输出 24kHz mono wav + `clips/timing.json`（每句精确 start/dur）。

```bash
python scripts/make_duo_tts.py --beats beats.json --out clips/
# 看输出每段 total/window，OVER 就调大该段 rate 重跑
```
将生成的 `clips/*.wav` 复制到 `public/assets/audio/narration/`，供 `render_remote.py` 上传；`clips/timing.json` 留在 clips/ 供字幕时间轴使用。
> edge-tts 偶发 `NoAudioReceived`，脚本已带 4 次重试 + size>1000 校验。
> 备选男声音色：云扬 YunyangNeural（新闻腔）、云峰 YunfengNeural（低沉）、云健 YunjianNeural（浑厚）。

### ⑥ Remotion atelier 工程

单文件 `index.tsx`，自包含，零 stock-registry import。基于 `templates/index.tsx` 改：

**固定骨架**（直接复用，不用重写）：
- 常量 `FPS=30/W=1920/H=1080/DURATION=<总帧>`；色板；`@font-face` 从 `public/fonts/` 加载 Noto VF；`FontGate`。
- 三张时间线表：`NARRATION`（from/dur/src）、`SFX`、`SUBTITLES`（from/to/spk/lines）。
- 组件：`SceneShell/SceneFade`（转场）、`H3Clip`（cover+Ken Burns+压暗+音量）、`SpeakerBadges`（左下双人头像，谁说话谁亮）、`Subtitles`（按 spk 着色的小字幕贴底）、`BGM_ENVELOPE`（ducking）。

**每项目要写的**：
- 各 beat 的场景组件：H3 场景用 `<H3Clip>` + 矢量叠加层；矢量场景按 `vector` 数据画 stat 卡/条形图/时间轴/对比表/补剂网格。
- `Main` 里用 `SceneShell from=<帧> durationInFrames=<帧>` 逐个排。
- 时间换算：`秒×30 = 帧`。字幕 from/to 用 `timing.json` 的 `beat起点帧 + start*30`。
- 确定性：用 `interpolate/spring`，伪随机 `h(n)`，禁运行时随机。

矢量组件参考 skill 自带 `templates/index.full_example.tsx`（含 stat 卡、终端、里程表、H3+矢量叠加等 10 种场景的完整工程）。

### ⑦ 远程渲染

用 `scripts/render_remote.py`：
1. 备份远端同名 `index.tsx`；如确认要复用 project 名称，可加 `--clean-remote` 清理该项目已知的旧视频/音频/字体目录；
2. SFTP 上传 narration wav + H3 mp4 + index.tsx + BGM/SFX/字体（运行前检查 `--local-public` 和 `--local-index`）；
3. 后台 `npx remotion render`（日志到 `/tmp/om_<project>_render.log`）；
4. `--wait` 时在有限时限内轮询到 `EXIT_CODE=0` 并确认远端成片非空；
5. 若指定 `--out`，拉回成片并做本地文件大小检查；视觉/编码/帧率 QA 仍按下方验收清单人工或用 ffprobe 完成。

```bash
python scripts/render_remote.py \
  --project <project> --composition <CompId> \
  --local-public ./public --local-index ./index.tsx \
  --duration-s 180 --wait --out ./final_<project>.mp4
```

渲染命令模板：
```bash
cd /opt/data/om-deploy/OpenMontage/remotion-composer
npx remotion render projects/<proj>/index.tsx <CompId> \
  /opt/data/om-deploy/.../renders/final.mp4 \
  --public-dir=<...>/public \
  --browser-executable=/root/.cache/ms-playwright/chromium-1234/chrome-linux/chrome \
  --concurrency=6 --gl=angle --crf=18 --timeout=60000
```

## 3. 验收清单

- [ ] ffprobe：时长/DURATION 一致、1920×1080、h264+aac、30fps
- [ ] H3 总时长 ≥ 需求（≥30s），无黑帧/无 H3 原生文字
- [ ] 时间轴：旁白/画面/字幕对齐（每 beat 抽 1 帧）
- [ ] 双人角标正确高亮，字幕按 spk 着色、无溢出、无豆腐块（CJK 字体加载）
- [ ] 数字与 research.json 一致，来源可查
- [ ] 听感：edge-tts 双人语速自然、无截断吞字
- [ ] 合规：免责声明在位（如需），无凭据泄露
- [ ] 可复现：beats.json + index.tsx + timing.json 落盘

## 4. 常见坑

| 坑 | 解法 |
|---|---|
| H3 做 3s 片段 | 工作台最短 5s；用 5s 片段或在 Remotion 里裁 |
| 旁白超窗口被截断 | 调大该段 `rate`，看 `total≤window` 再渲染 |
| 字幕同时两条 | 前一条 `to` 收在后一条 `from` 前 |
| CJK 豆腐块 | public/fonts 放 Noto VF，FontGate 加载字重 |
| 渲染 0.5fps | `--gl=angle`（纯软件 GL 慢 10 倍） |
| chromium 下载失败 | `--browser-executable` 指 playwright chromium-1234 |
| paramiko 后台命令超时 | 启动后用远端日志 marker 确认；`--wait` 有总超时，SSH 读取失败不会无限挂起 |
| H3 直连 18081 | 红线，脚本强制只允许本机回环 18090；跨机先做 SSH 端口转发 |
| 重用 project 产生旧素材 | 使用新的 project slug，或显式加 `--clean-remote` 清理已知素材目录 |
| n=1/营销话术 | 区分"声称 vs 证据"，主动放反方和辟谣点 |

## 5. 文件索引

- `scripts/make_duo_tts.py` — 双人 TTS 生成（beats.json → wav + timing.json）
- `scripts/render_remote.py` — 部署+远程渲染+拉回
- `scripts/om_ssh.py` — SSH 助手（skill 自带；凭据读桌面「服务器信息整理」最新版）
- `scripts/h3_batch.py` — H3 批量脚本（skill 自带；可部署到 15 的 /opt/data/om-deploy/）
- `templates/index.tsx` — Remotion 工程骨架
- `templates/index.full_example.tsx` — 完整参考工程（10 种场景实现）
- `templates/beats.example.json` — 分镜表示例
- `templates/h3_batch.example.jsonl` — H3 批次示例
- `references/h3-workbench-api.md` — 工作台 API 契约
- `references/remotion-patterns.md` — 矢量组件实现要点
- 可选参考（sextant2 工作区存在时）：`../../deliverables/index.tsx` 旧版、`../../blueprint/` 180s 全流程样例
