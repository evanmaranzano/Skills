---
name: daily-work-log
description: >
  扫描 opencode / claudecode / kimicode 等所有 agent 的今日会话，汇总并提炼为当日工作条目，
  优化表达、增强工作量体现，写入飞书《工作日志》文档对应「X 月 Y 日」章节；今日落成的飞书
  文档统一挂 <cite> 超链接。触发词：今日工作、整理工作日志、写工作日志、日志、汇总今天做了
  什么、standup、今日总结、生成日报、把今天的工作记一下。跨平台：Claude Code · Codex ·
  OpenCode · Kimi Code 通用。
---

# Daily Work Log — 每日工作日志生成 Skill

你是一个**工作日志编辑**。你读取今天（或指定日期）本机所有 agent 的会话记录，把散落的
工作动作归并成结构化的日志条目，用能体现工作量的语言扩写，写入飞书《工作日志》，并在
涉及落成飞书文档的条目上挂文档超链接。你不是记录员（不会逐条照抄），你是编辑（归并、
提炼、增强、按规范写作）。

## 为什么这件事重要

日常工作分散在多个 agent（opencode / claudecode / kimicode…）的多个会话里——今天改了 3
个服务器、排查了 2 个事故、写了 1 份交付文档、调了 1 张表格。单看任何一条会话都很零碎，
汇总起来才是一个人的一天。本 Skill 的唯一正式目标文档是飞书《工作日志》
（`https://my.feishu.cn/docx/B7vjd31ukoYMBmx1Dk9c7A8Jnzd`，revision 随写入递增），日志是
按月分章、按日分条，条目按「工作单元」扩写。

## 前置：必须读的依赖 skill 知识

执行前 MUST 用 Read 工具读取以下（决定参数与写法正确性，缺了会写错格式）：
1. `~/.agents/skills/lark-doc/SKILL.md` + `references/lark-doc-fetch.md` + `references/lark-doc-update.md`（读/写飞书文档、block 定位、<cite> 挂链接）
2. `~/.agents/skills/lark-drive/references/lark-drive-search.md`（`+search --created-by-me` 枚举当日文档）
3. `~/.agents/skills/lark-shared/SKILL.md`（认证、JSON 信封、@file 相对路径、高风险确认）

## 输入

- **日期**（默认今天；可指定 `--date YYYY-MM-DD`）。默认按本机当前日期。
- **多工具扫描范围**：默认 `opencode,claudecode,kimicode`（可 `--agents a,b,c` 裁剪）。
- **目标文档**：固定 `https://my.feishu.cn/docx/B7vjd31ukoYMBmx1Dk9c7A8Jnzd`。

## 工作流（四阶段）

### 阶段 0 — 会话扫描：找出「今天」开过哪些会话

目标：拿到今天所有 agent 会话的清单（标题 / 时间 / 项目 / 关键 user prompt），不急着读全文。

1. **首选 ccusage 枚举**（开源多 agent 用量/会话聚合，`npx ccusage` 临时可用）：
   ```bash
   npx ccusage session --format json       # 本机所有源，按 session 分组
   ```
   ccusage 覆盖 Claude Code、Codex、OpenCode、Kimi、Qwen、Copilot 等 16+ 源。它给的会话
   **标题/时间**用来建立「今天开了哪些会」的骨架；内容仍需走到阶段 2 的本地脚本。
2. **本地脚本兜底**（ccusage 没装/超时/覆盖不到时直接跑）：
   ```bash
   python ~/.agents/skills/daily-work-log/scripts/enumerate_sessions.py --date YYYY-MM-DD
   ```
   该脚本直接读各工具本地存储，输出今日会话清单 JSON（含 session id、工具、标题、时间、首条
   user prompt）。各工具存储路径见 `references/agent-storage-paths.md`。
3. **过滤出「今天」**：按会话 created / 首条 message 时间落在目标日期内的会话。剔除纯空会话
   （只有 session-start/end、无实质 user prompt——如 ai-memory 标记的空会话）。

> ⚠️ **多工具去重（关键）**：同一个任务常常在 opencode / claudecode / kimi 里各跑一遍
> （用户在不同终端重复问同样的事）。阶段 3 提炼时必须按「工作成果」归并，**同一工作只记一条**，
> 不能被三个工具各记一遍。判据：会话标题和首条 user prompt 高度重合 ⇒ 视为同一工作线。

### 阶段 1 — 飞书文档发现：捕获「今天落成的所有飞书文档」（用户要求捕获全）

这是「凡是今日产出的飞书文档都进工作日志」的机制，用官方搜索接口按**今日创建**枚举，
**不要只靠人工 token 索引**（索引会漏）：

```bash
# 今日创建的（新文档/表格/多维表格/wiki，含 docx/sheet/bitable/states...）
lark-cli drive +search --query "" --created-by-me \
  --created-since "<今日 YYYY-MM-DD>" --created-until "<明日 YYYY-MM-DD>" \
  --sort create_time --format json
```

- 返回里每条的 `title` / `token` / `entity_type` / `url` 就是挂 <cite> 所需的全部信息（docx/sheet
  用 `url` 里的 token；`entity_type` 映射 `--doc-types` 的 file_type）。
- 若担心「今天创建但没建完」或「今天编辑而非创建」的文档，可追加一查比照：
  ```bash
  lark-cli drive +search --query "" --created-by-me --edited-since 1d --format json
  ```
- 把结果整理成「当日文档库」：`{ title → {token, type, url} }`。阶段 3 写条目时，凡提到这些
  文档就用真实 token 挂 `<cite>`；**不要在文档库之外凭印象猜 token**。

### 阶段 2 — 内容提炼（LLM，最吃功夫的一步）

把阶段 0 的会话清单 + 各会话关键内容 + 阶段 1 的文档库交给模型，生成日志条目草稿：

1. **读内容**：对每个「有实质 work」的会话，读其 user prompt 与关键 tool 调用（用
   `enumerate_sessions.py` 已抽出的 prompt，或对重点会话用 `memory_read_session_observations` /
   直接读各自存储）。参考存储路径与读取方式见 `references/agent-storage-paths.md`。
2. **归并去重**：跨工具重复的同一工作只留一条。
3. **拆条扩写**（写作规范，见下）：把大动作拆成可见的工作量粒度的高光条目，扩全
   动机/做法/产出/效果。
4. **挂链**：命中阶段 1 文档库的，条目里对应处插入 `<cite ...>`；文档库里没有但确实
   落成了飞书文档的，entry 里写占位 `【挂链：<文档名>，token 待补】` 留待用户补。

### 阶段 3 — 写入飞书《工作日志》

1. **定位目标章节**：fetch 文档取 `--scope outline`，找目标月份的 `# YYYY 年 M 月` 及其下
   `## M 月 D 日`：
   - 当日 `## M 月 D 日` 已存在 ⇒ 定位其 h2，在其**最后一条 li 之后**插入新条目（`block_insert_after`，
     或直接用 `append` 若当日就是文档最后章节）。
   - 不存在 ⇒ 在月份 h1 下最后一个已有 `## 日` 之后创建 `## M 月 D 日` + `<ul>` 列表。
2. **写入**：优先 `append`（当日是文档末尾时最稳）或 `block_insert_after --block-id <锚点>`。
   - 内容用 **XML**：`<h2>M 月 D 日</h2><ul><li>…</li>…</ul>`，高光条目加 `<b>`。
   - **不要在 PowerShell 里内联带引号的 XML**（`\"` 会被拆裂、`<` 触发 parser error）。一律
     写到 cwd 下的临时文件（`@file.xml`，相对路径），用 `--content @file.xml` 传入，写完删除。
3. **block 生命周期**：`append` / `block_insert_after` 后新内容是新 block id；要继续改就得重新 fetch。
   多个 `str_replace` 叠加同一段会重复替换——**能用一次 block_replace 的不要用两次 str_replace**。

### 阶段 4 — 校验

- 重 fetch 目标 `## M 月 D 日` 章节，确认条目都在、`<cite>` 正确、无重复段（如 `。。`、重复句子）。
- 向用户汇报：写入的位置、条目数、挂了哪些文档链接、有哪些占位待补。

## 写作规范（表达优化 + 工作量体现，与日志既有风格一致）

- **每一条 = 一个可独立交付的工作单元**。压缩进单条的多工作拆成多条 li，让工作量可见。
- **高光/主线条目开头加粗**：`**<主题>。</b>`（如 `**dubhe 三容器公网 SSH 排查并在防火墙侧打通。**`），
  与文档里既有条目一致。
- **扩写动机/做法/产出/效果**：基于会话原文 + 引用文档标题 + 已知项目背景，把"做了什么"
  写成"为什么要做、怎么做的、交付了什么、实测了什么效果"；**不编造数字**（会话没测的别写
  "实测 100%"）。
- **部署/参数类**只写到会话当时提到的程度，不擅自从部署文档搬运超范围参数（那些留在各自
  部署文档，不进日志）。
- **挂链接**：凡落成飞书文档的条目，在该文档名处插 `<cite doc-id="<token>" file-type="<docx|sheets|bitable|wiki>" title="<标题>" type="doc"></cite>`。只有确实落成飞书文档的才挂；纯更新既有权威源（如改桌面 md）或本地软件产物不挂。
- **高光项（获奖等）加粗**；日期 h2 命名固定「M 月 D 日」。
- 当日已有日期 h2 则在其下列条目；单工具重复不计。

## 关键坑（今天实操踩出来的，务必遵守）

- **hs：防火墙端口「TCP 能连上」≠ 服务可用**：安恒明御防火墙对任意端口做 SYN 假握手，扫描/
  测试连通性必须以「拿到服务 banner / 完成登录」为判据，不能看 TCP connect 成功（`references/firewall-syn-false-positive.md`）。
- **str_replace 叠加会重复段**：连续两次替换同一段会产出重复文本。能用一次 `block_replace` 整块写，别拆两次 `str_replace`。
- **PowerShell + lark-cli 传参**：`--content` / `--json` 有引号或 `<` 时用 `@相对路径文件`；绝对路径会被拒（`--file must be relative path within cwd`）。
- **JSON 信封**：lark-cli 成功看 `ok==true`（退 0），不看 `code==0`（成功无顶层 code）。
- **多工具去重**：同一工作跨 opencode/claude/kimi 各跑一遍很常见，归并成一条。
- **ccusage 未装**：用 `npx ccusage`（临时）或直接跑本地 `enumerate_sessions.py` 兜底，不阻塞。

## 开源借鉴（为什么这么设计）

- **ccusage**（GitHub ryoppippi/ccusage，MIT）：多编码 agent 用量/会话聚合 CLI，覆盖 16+ 源
  （Claude/Codex/OpenCode/Kimi/Qwen/Copilot/Gemini…）。本 Skill 借其「会话枚举」层做今日会话
  发现；其只做统计不做内容提炼，故内容层由本 Skill 的 LLM 阶段补上。
- 飞书侧用官方 `drive +search --created-by-me --created-*` 做「当日文档捕获全」，比维护 token
  索引可靠、无额外 scope（`search:docs:read` 已有）。
- 写法规范对齐 `neat-freak` skill：跨平台、目标是让日志对"下一个接手的人"友好。

## 参考文件

- `references/work-log-format.md` — 工作日志既有结构、风格示例、<cite> 用法
- `references/agent-storage-paths.md` — opencode/claudecode/kimicode 会话存储路径与读取方式
- `references/firewall-syn-false-positive.md` — 防火墙 SYN 假握手 + 连接测试正确做法
- `references/lark-write-pitfalls.md` — lark-cli 写飞书文档的避坑（@file、block 生命周期、str_replace 叠加）
- `scripts/enumerate_sessions.py` — 本地会话枚举脚本（ccusage 兜底）
