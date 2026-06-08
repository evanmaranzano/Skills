# ActivityWatch Daily Log — Agent Notes

## 概览
ActivityWatch 屏幕活动 → 每日时间分类 HTML 报告。读取本地 AW 数据，按应用/域名聚合分类，输出增强版日报。

## 文档索引
- `skill.md` — 主流程定义（skill 入口）
- `docs/troubleshooting.md` — 常见问题与修复（分类名翻译、socket 断连、缓存冲突等）
- `docs/batch-backfill.md` — 批量补日志详细流程
- `prompts/html_gen_prompt.md` — 设计系统规范

## 前提
- ActivityWatch 运行中（`http://localhost:5600/api/0`）
- Python: Anaconda (`F:\anaconda`)
- 脚本：`~/.agents/skills/activitywatch-daily-log/scripts/`
- 数据目录：`F:/activitywatch-daily-log/`（config、raw、processed、reports）

## 执行
skill.md 定义了完整流程。核心步骤：
1. 确定目标日期（默认今天）
2. 运行 `scripts/aggregate.py` 导出 + 聚合
3. Agent 分类 → 生成 HTML 日报

## aggregate.py 已知 bug
`parse_day()` 返回 `date` 对象，无 `.timestamp()` 方法。aggregate.py 中所有需要时间戳的地方必须用 `datetime.combine(target_day, time.min).timestamp()` 包装。

## Pipeline 后必须同步 timeline 分类
管道输出的 timeline JSON 全部标记"未分类"。agent 分类完 summary 后，必须用 key (`{app}|{domain}`) 映射同步到 timeline：
```python
key_map = {a['key']: (a['category'], a.get('confidence')) for a in summary['aggregated']}
for e in timeline:
    k = f"{e['app']}|{e['domain']}"
    if k in key_map:
        e['category'], e['confidence'] = key_map[k]
```

## 日期判断
系统时钟可能与 currentDate 提示不一致。判断"昨天"前先 `python -c "from datetime import datetime; print(datetime.now().date())"` 确认实际日期。

## Shell 环境
默认 PowerShell (pwsh 7.6+)，与全局设定一致。skill.md 命令示例均为 PowerShell 语法。

## Summary JSON 数据字段
- `active_seconds` 字段可能为 0，必须用 `sum(i['duration_seconds'] for i in aggregated)` 计算真实活跃时长
- `afk_seconds` 在 AW 非全天运行时会虚高（如显示 24.8h），不代表真实 AFK
- `duration_seconds` 已扣除 AFK 重叠时段，是真实活跃时长；`raw_duration_seconds` 含 AFK
- Timeline JSON 可能不存在（AW 重启/数据丢失），读取时 try/except

## 批量补日志模式
1. 用 AW API 确认哪些天有原始数据但缺报告：`curl http://localhost:5600/api/0/buckets/aw-watcher-window_imHowie/events?start=...&end=...&limit=5`
2. 逐天跑 `run_daily_log.py --date <date> --agent-mode`
3. 分类未识别项并写入 `classification_cache.json`
4. 生成 HTML 用 Python 脚本写入 `reports/`（不可用 bash heredoc + f-string，花括号冲突）
5. 生成 Obsidian markdown 写入 `10-Daily/`
