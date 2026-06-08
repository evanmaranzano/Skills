# 批量补日志流程

## 适用场景
多天日报缺失需要补生成（如连续几天未跑定时任务）。

## 推荐流程：两阶段并行

### 阶段 1：数据采集（可并行）

对每个缺失日期运行数据管道：

```powershell
python "C:/Users/Administrator/.claude/skills/activitywatch-daily-log/scripts/run_daily_log.py" --date <YYYY-MM-DD> --agent-mode
```

输出 summary.json + timeline.json 到 `F:/activitywatch-daily-log/processed/`。

确认缺失日期范围：
- 查已有报告：`ls F:/activitywatch-daily-log/reports/*.html`
- 确认 AW 有原始数据：`curl "http://localhost:5600/api/0/buckets/aw-watcher-window_imHowie/events?start=<ISO>&end=<ISO>&limit=1"`

### 阶段 2：HTML 生成 + 归档（并行子代理）

为每个日期启动独立子代理，任务仅包含：
1. 读取已有 summary/timeline JSON
2. 分类未识别项
3. 调用 frontend-design skill 生成 HTML
4. 写入 Obsidian 归档

每个代理约 2-5 分钟，远低于 socket 超时阈值。

## 注意事项

- 子代理 prompt 中必须明确分类名使用中文
- 多代理并行写 `classification_cache.json` 可能冲突，见 troubleshooting.md 第 4 条
- 每个代理独立打开报告（`start ""`），浏览器会打开多个标签页
