# Agent 会话存储路径与读取方式（daily-work-log 阶段 0/2）

> 本机（win32, 用户名 Administrator）各 agent 会话的落盘位置与读取方法。路径全部实测过
> （2026-09-03 复核），供 `enumerate_sessions.py` 与手工读取使用。
> 通用语义：**一律按会话创建日（created）过滤到目标日**；长会话跨天的后续工作不会出现在
> 后一天，靠阶段 2 的归并兜底。脚本输出统一 `{agent, session_id, title, first_prompt,
> created_at, directory, has_content}`，`first_prompt` 已做凭据脱敏（sk-…/JWT/Bearer/
> password=… → `***`）。

## opencode

- **数据库**：`C:\Users\Administrator\.local\share\opencode\opencode.db`（SQLite 单文件，另有
  `-shm` / `-wal` 并发文件，查询时别动）。
- **关键表**：
  - `session`：列含 `id`（形如 `ses_…`）、`title`、`time_created`（**毫秒 Unix**）、
    `time_updated`、`model`、`agent`、`directory`（真实 cwd，脚本直接输出）。
  - `part`：列含 `id`、`session_id`、`time_created`、`data`（JSON）。`data.type=="text"` 时
    `data.text` 是消息/思考文本。
- **今日会话查询**（脚本已改为毫秒区间查询，比全表扫快）：
  ```sql
  SELECT id,title,time_created,directory FROM session
   WHERE time_created >= <当日0点毫秒> AND time_created < <次日0点毫秒>;
  ```
- **读某会话 user prompt**：`SELECT data FROM part WHERE session_id=? ORDER BY time_created`，
  找 `data.type=='text'` 且文本非噪声的首条。

## claudecode（Claude Code）

- **会话文件**：`C:\Users\Administrator\.claude\projects\<project-dir>\<sessionId>.jsonl`
  （`project-dir` 形如 `C--Users-Administrator`，对应工作目录转义；编码有损，脚本不反解
  directory）。
- **格式**：每行一个 JSON 对象。`type=="user"` 的行 `message.content` 是用户输入（数组或字符串）；
  `message.content[].type=="text"` 的 `.text` 是要看的 prompt，`type=="image"` 是截图（base64，忽略）。
  `timestamp` 为 RFC3339 UTC。
- **筛选今日**：脚本先按文件 mtime ≥ 当日 0 点预过滤（今天没写过的文件直接跳过，避免全量
  读大 jsonl），再按行内 `timestamp` 精确判断。只扫到首条真实 user 文本即停（上限 5000 行）。

## kimicode（Kimi Code）

- **根目录**：`C:\Users\Administrator\.kimi-code\sessions\`
- **结构**：`<wd>_<hash>\session_<uuid>\` 每个会话一个目录；`<wd>` 形如 `wd_administrator_999b891b683b`。
- **每个会话语义文件**：
  - `state.json`：含 `title`、`lastPrompt`、`createdAt` / `updatedAt`（**RFC3339 UTC 字符串**
    或毫秒两种都见过，脚本兼容）。
  - `agents\main\wire.jsonl` 含会话时间线。
- **筛选今日**：脚本按 `state.json` 的 mtime ≥ 当日 0 点预过滤（避开大量历史会话目录），
  再按 `createdAt` 精确判断。`title` / `lastPrompt` 直接给出工作主题。
- ⚠️ `.kimi-code\sessions` 底下有大量历史会话目录，别全读。

## zcode

- **数据库**：`C:\Users\Administrator\.zcode\cli\db\db.sqlite`（SQLite 单文件，另有
  `-shm` / `-wal` 并发文件，查询时别动）。
- **关键表**（与 opencode 同构，zcode 是 opencode 的国产化分支）：
  - `session`：列含 `id`（形如 `sess_…`）、`title`、`directory`、`time_created`
    （**毫秒 Unix**）、`time_updated`。
  - `message`：列含 `id`、`session_id`、`time_created`、`data`（JSON）。`data.role=="user"`
    且 `data.semantics.kind=="user_prompt"` 是真实用户消息。
  - `part`：列含 `id`、`message_id`、`session_id`、`time_created`、`data`（JSON）。
    `data.type=="text"` 时 `data.text` 是消息文本。真实 prompt 在 user message 关联的 text part 里。
- **今日会话查询**：同 opencode（毫秒区间）。

## pi（Pi Coding Agent）

- **会话文件**：`C:\Users\Administrator\.pi\agent\sessions\<项目目录>\<时间戳>_<uuid>.jsonl`
  （`项目目录` 形如 `--C--Users-Administrator--`，对应 cwd 转义；文件名前缀是会话创建时间 UTC）。
- **格式**：每行一个 JSON 对象。
  - 首行 `type=="session"`：含 `id`、`timestamp`（RFC3339 UTC）、`cwd`（真实路径，脚本输出）。
  - `type=="message"`：`message.role=="user"` 时 `message.content[].type=="text"` 的 `.text`
    是用户输入（assistant 的 content 还有 `type=="thinking"` 思考块，忽略）。
  - `type=="model_change"` / `thinking_level_change` 等是元事件，跳过。
- **筛选今日**：文件 mtime 预过滤 + 首行 `session.timestamp`（UTC → 本地时区）精确判断。

## deepseek-harness（dsh）

- **会话根目录**：`C:\Users\Administrator\.dsh\sessions\<项目目录>\session-<uuid>\`
  （`项目目录` 形如 `--F-molispark--`；每个会话一个目录）。
- **会话文件**：`session.jsonl.zstd`（**zstd 压缩的 jsonl**，必须用
  `zstandard.stream_reader()` 流式解压；脚本逐行迭代、找到首条真实 prompt 即停，行数上限
  20 万行防解压炸弹）。
- **格式**：每行一个 JSON 对象。
  - 首行 `type=="session"`：含 `id`、`createdAt`（**毫秒 Unix**）、`cwd`（真实路径，脚本输出）。
  - `type=="user/message"`：`data.content[].type=="text"` 的 `.text` 是用户输入；**必须**用
    `data.source.kind=="user"` 区分真实用户 vs 系统注入的 `<system-reminder>`（reminder 无
    `source` 或 kind 不同，务必跳过，否则把 AGENTS.md 注入当 prompt）。
  - 其余 `reasoning-chunks` / `assistant/chunk` / `tool/call` 等是过程事件，跳过。
- **依赖**：需要 `zstandard` Python 包（`pip install zstandard`）；缺失时脚本自动跳过 dsh。

## codex（Codex CLI，2026-09-03 实测 v0.145.0）

- **会话文件**：`C:\Users\Administrator\.codex\sessions\<YYYY>\<MM>\<DD>\rollout-<本地时间戳>-<uuid>.jsonl`
  （**文件名时间戳是本地时间**，如 `rollout-2026-09-02T15-52-03-01a0611a-….jsonl`）。
  另有 `archived_sessions\`（扁平目录，同名格式），脚本两个位置都扫。
- **格式**：每行一个 JSON 对象，顶层 `{timestamp, ordinal, type, payload}`：
  - 首行 `type=="session_meta"`：`payload` 含 `session_id`、`id`、`timestamp`（**RFC3339 UTC**）、
    `cwd`（真实路径，脚本输出）、`cli_version`、`originator`。
  - 用户消息两种形态都认：`type=="response_item"` 且 `payload.type=="message"`、
    `payload.role=="user"`（`content[].type=="input_text"` 的 `.text`）；
    或 `type=="event_msg"` 且 `payload.type=="user_message"`（`payload.message`）。
- **⚠️ 注入过滤（必须）**：user 角色里混着系统注入上下文，脚本会跳过：
  - XML 形态：`<recommended_plugins>`、`<user_instructions>`、`<environment_context>`…
  - markdown 形态：`# AGENTS.md instructions …`（event_msg 里常见，实测首条就是它）。
- **标题**：`~/.codex/session_index.jsonl`（`{id, thread_name, updated_at}`，同 id 后写覆盖
  前写）可当标题索引；文件超 64MB 时脚本放弃索引。

## gemini（Gemini CLI，2026-09-03 实测 v0.52.0）

- **会话文件**：`C:\Users\Administrator\.gemini\tmp\<项目hash或目录名>\chats\session-<UTC时间戳>-<hash>.json`
  （每个会话一个 JSON 文件；`tmp/` 下 hash 目录与 `administrator` 这类目录名混存）。
- **格式**（单 JSON，非 jsonl）：顶层 `{sessionId, projectHash, startTime, lastUpdated, messages[]}`：
  - `startTime` 为 **RFC3339 UTC**。
  - `messages[].type=="user"` 时 `content`（字符串）是用户输入；assistant 消息 `type=="gemini"`
    带 thoughts/tokens/model，跳过。
- **筛选今日**：文件 mtime 预过滤 + `startTime` 精确判断；文件超 32MB 跳过。

## grok（Grok CLI）——暂不支持

- 本机 `C:\Users\Administrator\.grok\` 只有 `config.toml`（自定义 model provider 配置），
  **CLI 未安装、会话不落盘**，无法枚举。脚本保留 `grok` 占位：指定 `--agents grok` 时在
  stderr 提示后返回空，不会静默。⚠️ 该 config.toml 内含 api_key，脚本不读它。

## antigravity（Gemini IDE）——暂不支持

- `~/.gemini/antigravity/`（brain/、annotations/、code_tracker/ 等私有格式 + `.pb` 文件），
  非通用会话 jsonl，暂不扫描。

## ccusage 备选

`npx ccusage session --format json`（临时，需联网拉包）可跨 16+ agent 枚举今日会话标题/时间
骨架；本机未常驻安装。它不返回内容——内容始终走上面本地读取。

## 批量扫描

优先跑 `scripts/enumerate_sessions.py --date YYYY-MM-DD`（默认全部 8 个受支持的 harness，
`--agents a,b,c` 可裁剪），输出统一 JSON。阶段 0 用它；阶段 2 对重点会话再按本文件读细节。
