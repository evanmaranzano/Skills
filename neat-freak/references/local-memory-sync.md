# local-memory 快照同步规程（本地 → ai-memory 单向）

协议出处：`~/.agents/AGENTS.md`「长期记忆与知识分层」——文件记忆（`~/.agents/memory/` + `MEMORY.md` 索引）是唯一权威源；ai-memory（服务器 10.10.127.15:49374）里的 `local-memory/*` 页只是导入快照。**方向永远是 本地 → ai-memory，禁止以快照反向更新本地文件。**

## 何时刷

- 触发点：neat-freak 同步会话走到 SKILL.md 治理清单的「快照新鲜度」项时。
- 增量判定：状态文件 `~/.agents/memory/.snapshot-sync-state.json` 记录上次成功推送时每个文件的 mtime；没有状态文件或 mtime 变了 / 新增的文件即待推。本机删除的 .md 不主动删远端页（ai-memory 无对应删除约定），在摘要里列出让用户决定。

## 页面格式（与既有快照保持一致）

1. 去掉本地文件的 YAML frontmatter。
2. 标题：本地正文首个 H1 存在则保留它作页首（页面标题随它派生）；否则补 `# <文件名去扩展名>`。
3. 紧跟标题后空一行插入权威源头注（日期用绝对日期）：
   `> 权威源：<设备标签> \`~/.agents/memory/<原文件名含扩展名>\`；本页为 <YYYY-MM-DD> 导入快照，后续更新以本地为准。`
   `<设备标签>` 默认 `本机（<home 目录名>）`——主目录用户名即设备标识。
4. 其余正文逐字保留，不做改写（相对时间应在 neat-freak 主流程里已换成绝对日期）。
5. 写入参数：`path=local-memory/<原文件名>`、`tags=["local-memory-import"]`、`tier=semantic`、不传 `title`（H1 已存在）。

## 推送与验证

- 用 ai-memory MCP 的 `memory_write_page` 逐页写；单批建议 ≤5 页。
- **超时报错 ≠ 失败**：请求超时先 `memory_read_page` 回读核对内容是否已落库，再决定重写与否，避免制造重复版本。
- 服务端会自动脱敏密钥（出现 `[REDACTED]` 属正常），不要预先手工改写正文。

## 脚本辅助（只做确定性部分）

`scripts/prepare_snapshot_sync.py`：对比状态文件找变更文件、按上述规则渲染好正文写到输出目录、打印清单。MCP 推送和落账仍由 agent 完成：

```bash
python scripts/prepare_snapshot_sync.py          # 生成待推送正文 + 清单
# agent 按清单逐页 memory_write_page，全部回读验证通过后——
python scripts/prepare_snapshot_sync.py --mark   # 落账本次 mtime 基线
```

脚本不修改 `~/.agents/memory/` 下任何 `.md`，只读写 `.snapshot-sync-state.json` 和输出目录。
