---
name: daily-work-log
user-invocable: true
description: >
  扫描本机全部 agent harness（Claude Code · ZCode · Codex CLI · OpenCode · Kimi Code ·
  Gemini CLI · Pi · DeepSeek Harness）的今日会话，汇总并提炼为当日工作条目，优化表达、
  增强工作量体现，写入飞书《工作日志》文档对应「X 月 Y 日」章节；今日落成的飞书文档统一
  挂 <cite> 超链接。触发词：今日工作、整理工作日志、写工作日志、日志、汇总今天做了什么、
  standup、今日总结、生成日报、把今天的工作记一下。
  跨平台：Claude Code · ZCode · Codex · OpenCode · Kimi Code · Gemini CLI · Pi · DeepSeek Harness 通用。
---

# daily-work-log — 跨 Harness 每日工作日志

> 今天的你开了八个终端、用了八个 agent。散在八个工具里的会话，汇成飞书里的一条日志——
> 换任何 harness 干活，日终都有同一份交代。

## 为什么

- **工作天然分散在多个 harness。** 同一天可能在 Claude Code 里排查事故、在 Codex 里核实能力、
  在 dsh 里调服务器、在 ZCode 里写工作台。单看任何一条会话都很零碎，汇总起来才是一个人的一天。
- **同一件事常常在多个工具里各跑一遍。** 用户在不同终端重复问同样的事——日志必须按「工作成果」
  归并，同一工作只记一条。
- **落成的交付物必须可追溯。** 当日在飞书新建的所有文档（docx/sheet/bitable/wiki）都要进日志
  并挂 `<cite>` 超链接，靠官方搜索接口枚举，不靠人工 token 索引（索引会漏）。
- **忠实扩写，不编造。** 把"做了什么"写成"为什么做、怎么做、交付了什么、实测了什么效果"，
  但会话里没测过的数字一个都不写。

目标文档唯一且固定：飞书《工作日志》
（`https://my.feishu.cn/docx/B7vjd31ukoYMBmx1Dk9c7A8Jnzd`），按月分章、按日分条。

## 它怎么工作

```
scan ──────────▶ dedupe ──▶ polish ──────────▶ write
本地脚本枚举      跨工具归并    拆条扩写          飞书《工作日志》
8 个 harness     同一工作线    动机/做法/        「M 月 D 日」章节
只读会话存储      只记一条      产出/效果         + <cite> 挂链
        │
        └── drive +search --created-by-me 枚举今日落成的飞书文档，供挂链
```

## 支持矩阵

会话枚举由 `scripts/enumerate_sessions.py` 完成，全部只读。本机（win32）实测覆盖：

| Harness | 本地会话存储 | 枚举 | 备注 |
| --- | --- | --- | --- |
| OpenCode | `~/.local/share/opencode/opencode.db`（SQLite） | ✅ | 毫秒区间查询，带 directory |
| ZCode | `~/.zcode/cli/db/db.sqlite`（SQLite） | ✅ | 同 opencode 结构 |
| Claude Code | `~/.claude/projects/**/*.jsonl` | ✅ | mtime 预过滤，首条 user 即停 |
| Codex CLI | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | ✅ | 文件名=本地时间；`archived_sessions/` 一并扫；标题来自 `session_index.jsonl`；**必须过滤注入的 AGENTS.md / `<…>` 上下文** |
| Kimi Code | `~/.kimi-code/sessions/*/session_*/state.json` | ✅ | title/lastPrompt 现成 |
| Gemini CLI | `~/.gemini/tmp/*/chats/session-*.json` | ✅ | `messages[].type=="user"` |
| Pi | `~/.pi/agent/sessions/**/*.jsonl` | ✅ | 首行 session 带 cwd |
| DeepSeek Harness (dsh) | `~/.dsh/sessions/*/session-*/session.jsonl.zstd` | ✅ | 需 `pip install zstandard`；流式解压+行数上限 |
| Grok CLI | `~/.grok/`（仅 config.toml，无会话落盘） | ⚠️ | CLI 未装，占位提示不静默 |

细节与逐家格式见 `references/agent-storage-paths.md`。`npx ccusage session --format json`
可作跨工具会话标题骨架的补充，但它不返回内容——内容始终走本地脚本。

## 前置：必须读的依赖 skill 知识

执行前 MUST 用 Read 工具读取以下（决定参数与写法正确性，缺了会写错格式）：
1. `~/.agents/skills/lark-doc/SKILL.md` + `references/lark-doc-fetch.md` + `references/lark-doc-update.md`（读/写飞书文档、block 定位、<cite> 挂链接）
2. `~/.agents/skills/lark-drive/references/lark-drive-search.md`（`+search --created-by-me` 枚举当日文档）
3. `~/.agents/skills/lark-shared/SKILL.md`（认证、JSON 信封、@file 相对路径、高风险确认）

## 输入

- **日期**（默认今天；可指定 `--date YYYY-MM-DD`）。默认按本机当前日期。
- **扫描范围**：默认全部 8 个受支持 harness（可 `--agents a,b,c` 裁剪）。
- **目标文档**：固定 `https://my.feishu.cn/docx/B7vjd31ukoYMBmx1Dk9c7A8Jnzd`。

## 工作流（四阶段）

### 阶段 0 — 会话扫描：找出「今天」开过哪些会话

目标：拿到今天所有 agent 会话的清单（标题 / 时间 / 项目 / 首条 user prompt），不急着读全文。

```bash
python ~/.agents/skills/daily-work-log/scripts/enumerate_sessions.py --date YYYY-MM-DD
```

- 输出统一 JSON：`[{agent, session_id, title, first_prompt, created_at, directory, has_content}]`；
  `directory` 可用来把会话归到项目（opencode/zcode/pi/dsh/codex 提供）。
- 剔除纯空会话（无实质 user prompt，`has_content=false`）。
- `npx ccusage` 可选补充标题骨架；脚本没装 `zstandard` 时 dsh 自动跳过并在 stderr 提示。

> ⚠️ **多工具去重（关键）**：同一个任务常常在多个 harness 里各跑一遍。阶段 2 提炼时必须按
> 「工作成果」归并，**同一工作只记一条**。判据：会话标题和首条 user prompt 高度重合 ⇒
> 视为同一工作线；`directory` 同项目可作为辅助证据。

### 阶段 1 — 飞书文档发现：捕获「今天落成的所有飞书文档」

用官方搜索接口按**今日创建**枚举，**不要只靠人工 token 索引**（索引会漏）：

```bash
lark-cli drive +search --query "" --created-by-me \
  --created-since "<今日 YYYY-MM-DD>" --created-until "<明日 YYYY-MM-DD>" \
  --sort create_time --format json
```

- 每条的 `title` / `token` / `entity_type` / `url` 就是挂 `<cite>` 所需的全部信息。
- 想覆盖「今天编辑而非创建」的文档，追加一查比照：
  `lark-cli drive +search --query "" --created-by-me --edited-since 1d --format json`
- 整理成「当日文档库」：`{ title → {token, type, url} }`。阶段 2 写条目时，凡提到这些文档
  就用真实 token 挂 `<cite>`；**不要在文档库之外凭印象猜 token**。

### 阶段 2 — 内容提炼（LLM，最吃功夫的一步）

1. **读内容**：对每个有实质 work 的会话，读其 user prompt 与关键 tool 调用（用脚本已抽出的
   prompt，或按 `references/agent-storage-paths.md` 读该 harness 的存储细节；重点会话可用
   `memory_read_session_observations` 辅助）。
2. **归并去重**：跨工具重复的同一工作只留一条（见阶段 0 的判据）。
3. **拆条扩写**（写作规范见下）：把大动作拆成可见的工作量粒度的高光条目。
4. **挂链**：命中当日文档库的插 `<cite>`；文档库里没有但确实落成了飞书文档的，写占位
   `【挂链：<文档名>，token 待补】` 留待用户补。

### 阶段 3 — 写入飞书《工作日志》

1. **定位目标章节**：fetch 文档取 `--scope outline`，找目标月份的 `# YYYY 年 M 月` 及其下
   `## M 月 D 日`：
   - 当日 `## M 月 D 日` 已存在 ⇒ 在其**最后一条 li 之后**插入新条目（`block_insert_after`，
     或当日就是文档最后章节时直接 `append`）。
   - 不存在 ⇒ 在月份 h1 下最后一个已有 `## 日` 之后创建 `## M 月 D 日` + `<ul>` 列表。
2. **写入**：内容用 **XML**：`<h2>M 月 D 日</h2><ul><li>…</li>…</ul>`，高光条目加 `<b>`。
   - **不要在 PowerShell 里内联带引号的 XML**（`\"` 会被拆裂、`<` 触发 parser error）。一律
     写到 cwd 下的临时文件（`@file.xml`，相对路径），用 `--content @file.xml` 传入，**写完删除**。
3. **block 生命周期**：`append` / `block_insert_after` 后新内容是新 block id；要继续改就得重新
   fetch。**能用一次 `block_replace` 的不要拆两次 `str_replace`**（叠加替换会产出重复文本）。

### 阶段 4 — 校验

- 重 fetch 目标 `## M 月 D 日` 章节，确认条目都在、`<cite>` 正确、无重复段（如 `。。`、重复句子）。
- 向用户汇报：写入的位置、条目数、挂了哪些文档链接、有哪些占位待补。

## 写作规范（表达优化 + 工作量体现，与日志既有风格一致）

- **每一条 = 一个可独立交付的工作单元**。压缩进单条的多工作拆成多条 li，让工作量可见。
- **高光/主线条目开头加粗**：`**<主题>。</b>`（如 `**dubhe 三容器公网 SSH 排查并在防火墙侧
  打通。**`），与文档里既有条目一致。
- **扩写动机/做法/产出/效果**：基于会话原文 + 引用文档标题 + 已知项目背景，把"做了什么"
  写成"为什么要做、怎么做的、交付了什么、实测了什么效果"；**不编造数字**（会话没测的别写
  "实测 100%"）。
- **部署/参数类**只写到会话当时提到的程度，不擅自从部署文档搬运超范围参数（那些留在各自
  部署文档，不进日志）。
- **挂链接**：凡落成飞书文档的条目，在该文档名处插 `<cite doc-id="<token>" file-type="<docx|sheets|bitable|wiki>" title="<标题>" type="doc"></cite>`。只有确实落成飞书文档的才挂；纯更新既有权威源（如改桌面 md）或本地软件产物不挂。
- 日期 h2 命名固定「M 月 D 日」；当日已有日期 h2 则在其下列条目。

## 安全

- **本地扫描只读**：SQLite 以 `mode=ro` 打开、会话文件只读、无网络、无子进程、无动态执行；
  不触碰任何凭据文件（`auth.json` / `oauth_creds.json` / `config.toml` 等）。
- **凭据脱敏**：脚本对 `first_prompt`/`title` 自动抹除 `sk-…`、JWT（`eyJ…`）、`Bearer …`、
  `password=…` 等形态（实测会话里出现过明文 key）；阶段 2 扩写时**不得**把会话里看到的密钥、
  令牌、Cookie、内网凭据、`.env` 值写进日志条目。
- **写入边界**：目标文档固定为《工作日志》，不写其他飞书文档；lark-cli 的高风险操作确认、
  认证与 JSON 信封约定以 `lark-shared` 为准；`@file.xml` 临时文件用完即删。

## 关键坑（实操踩出来的，务必遵守）

- **str_replace 叠加会重复段**：连续两次替换同一段会产出重复文本。能用一次 `block_replace`
  整块写，别拆两次 `str_replace`。
- **PowerShell + lark-cli 传参**：`--content` / `--json` 有引号或 `<` 时用 `@相对路径文件`；
  绝对路径会被拒（`--file must be relative path within cwd`）。
- **JSON 信封**：lark-cli 成功看 `ok==true`（退 0），不看 `code==0`（成功无顶层 code）。
- **多工具去重**：同一工作跨 harness 各跑一遍很常见，归并成一条。
- **长会话跨天**：枚举按会话创建日归档，长会话后一天的工作不另起条目，靠阶段 2 归并兜底。
- **脚本兜底优先**：ccusage 未装不阻塞，直接跑本地脚本。

## 参考文件

| 文件 | 内容 |
| --- | --- |
| `references/agent-storage-paths.md` | 8+2 家 harness 的会话存储路径、格式与读取方式（逐家实测） |
| `references/work-log-format.md` | 工作日志既有结构、风格示例、`<cite>` 用法 |
| `references/lark-write-pitfalls.md` | lark-cli 写飞书文档的避坑（@file、block 生命周期、str_replace 叠加） |
| `references/firewall-syn-false-positive.md` | 防火墙 SYN 假握手 + 连通性测试正确做法 |
| `scripts/enumerate_sessions.py` | 本地会话枚举脚本（只读、脱敏、8 harness） |

## 致谢

- **[ccusage](https://github.com/ryoppippi/ccusage)**（MIT）— 多 agent 会话枚举的思路来源；
  其只做统计不做内容提炼，内容层由本 Skill 的 LLM 阶段补上。
- **[ai-memory](https://github.com/akitaonrails/ai-memory)**（MIT）— 本文档的写法与「支持矩阵 +
  安全边界」的组织方式参考自其 README；跨 harness 记忆共享是它的活，日志归并是本 Skill 的活。
- 写法规范对齐 `neat-freak` skill：跨平台、目标是让日志对"下一个接手的人"友好。
