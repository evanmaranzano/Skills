# 常见问题与修复

## 1. 子代理把分类名翻译成英文

**现象**：HTML 报告中出现 "AI Programming"、"Entertainment" 等英文分类名，而非 "AI 编程"、"娱乐"。

**根因**：子代理生成 HTML 时倾向将中文分类名翻译为英文（LLM 默认英文输出偏好）。

**修复**：批量替换：
```python
replacements = {
    'AI Programming': 'AI 编程',
    'Research / Info Retrieval': '资料检索',
    'Entertainment': '娱乐',
    'Communication': '沟通',
    'System / Misc': '系统杂项',
    'Dev Tools': '开发工具',
    'Papers / Docs': '论文/文档',
    'Unclassified': '未分类',
}
for eng, chn in replacements.items():
    html = html.replace(eng, chn)
```

**预防**：子代理 prompt 中明确列出中文分类名，并加"禁止翻译为英文"。

---

## 2. 子代理 socket 断连

**现象**：长时间运行的子代理报 `API Error: The socket connection was closed unexpectedly`。

**根因**：单个代理任务过重（数据采集 + 分类 + HTML 生成 + 归档），运行时间超过 socket 超时。

**缓解**：两阶段分离——阶段 1 跑数据管道生成 JSON，阶段 2 启动轻量代理只做 HTML + 归档。

---

## 3. Timeline 分类未同步

**现象**：summary 已分类但 timeline JSON 中仍是"未分类"。

**根因**：`run_daily_log.py --agent-mode` 跳过 LLM 分类，timeline 默认全标"未分类"。

**修复**：分类完 summary 后必须同步到 timeline：
```python
key_map = {a['key']: (a['category'], a.get('confidence')) for a in summary['aggregated']}
for e in timeline:
    k = f"{e['app']}|{e['domain']}"
    if k in key_map:
        e['category'], e['confidence'] = key_map[k]
```

---

## 4. classification_cache.json 并发写入冲突

**现象**：多代理并行写入同一缓存文件导致内容丢失。

**缓解**：各代理读取时用 try/except 处理 JSON 解析错误；写入前先读取、合并、再写入。理想情况下应为每个日期独立缓存文件，或使用文件锁。

---

## 5. active_seconds 为 0

**现象**：summary 中 `active_seconds` 字段为 0。

**根因**：聚合脚本未正确计算。

**修复**：用 `sum(i['duration_seconds'] for i in aggregated)` 手动计算。
