# Agent 会话存储路径与读取方式（daily-work-log 阶段 0/2）

> 本机（win32, 用户名 26566）各 agent 会话的落盘位置与读取方法。路径都是实测过的，
> 供 `enumerate_sessions.py` 与手工读取使用。

## opencode

- **数据库**：`C:\Users\26566\.local\share\opencode\opencode.db`（SQLite 单文件，另有
  `-shm` / `-wal` 并发文件，查询时别动）。
- **关键表**：
  - `session`：列含 `id`（形如 `ses_…`）、`title`、`time_created`（**毫秒 Unix**）、
    `time_updated`、`model`、`agent`、`directory`。
  - `part`：列含 `id`、`session_id`、`time_created`、`data`（JSON）。`data.type=="text"` 时
    `data.text` 是消息/思考文本。
- **今日会话查询**：
  ```sql
  SELECT id,title,time_created FROM session
   WHERE datetime(time_created/1000,'unixepoch','localtime') >= 'YYYY-MM-DD 00:00'
     AND datetime(time_created/1000,'unixepoch','localtime') <  'YYYY-MM-DD+1 00:00';
  ```
- **读某会话 user prompt**：`SELECT data FROM part WHERE session_id=? ORDER BY time_created`，
  找 `data.type=='text'` 且角色为 user（标题/首条多是人话，工具结果一般很长，按序先出现的是 prompt）。

## claudecode（Claude Code）

- **会话文件**：`C:\Users\26566\.claude\projects\<project-dir>\<sessionId>.jsonl`
  （`project-dir` 形如 `C--Users-26566`，对应工作目录转义）。
- **格式**：每行一个 JSON 对象。`type=="user"` 的行 `message.content` 是用户输入（数组或字符串）；
  `message.content[].type=="text"` 的 `.text` 是要看的 prompt，`type=="image"` 是截图（base64，忽略）。
  `timestamp` 为 RFC3339 UTC。
- **筛选今日**：按文件 mtime（LastWriteTime 落在当日）或按行 `timestamp` 过滤。
- **优化**：`.jsonl` 体积大，`Select-String -Pattern '"role":"user"'` 只抽 user 行，再逐个
  `ConvertFrom-Json` 取 `message.content`，避免全文读入 context。

## kimicode（Kimi Code）

- **根目录**：`C:\Users\26566\.kimi-code\sessions\`
- **结构**：`<wd>_<hash>\session_<uuid>\` 每个会话一个目录；`<wd>` 形如 `wd_26566_999b891b683b`。
- **每个会话语义文件**：
  - `state.json`：含 `title`、`lastPrompt`、`createdAt` / `updatedAt`（**毫秒 Unix**）。
  - `agents\main\wire.jsonl` 含会话时间线。
- **筛选今日**：按 `session_*` 目录的 LastWriteTime 落在当日；或按 `state.json` 的 `createdAt`/
  `updatedAt`（毫秒 → `fromtimestamp(ms/1000)`）。`title` / `lastPrompt` 直接给出工作主题。
- ⚠️ `.kimi-code\sessions` 底下有大量历史会话目录，**必须按 mtime/createdAt 过滤到目标日**，
  别全读。

## 批量扫描

优先跑 `scripts/enumerate_sessions.py --date YYYY-MM-DD`，它会汇总上述三边输出统一的 JSON：
`[{agent, session_id, title, first_prompt, created_at}]`。阶段 0 用它；阶段 2 对重点会话再
按本文件读细节。

## ccusage 备选

`npx ccusage session --format json`（临时，需联网拉包）可跨 16+ agent 枚举今日会话骨架；
本机未常驻安装。ccusage 返回会话标题/时间，不返回内容——内容仍走上面本地读取。
