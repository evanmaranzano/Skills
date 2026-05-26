---
name: activitywatch-daily-log
description: >
  生成 ActivityWatch 每日活动日报（Agent 增强版）。使用本地 ActivityWatch 数据导出、分类、聚合，
  再由当前 agent 直接生成增强版 HTML 日报。当用户提到"日报"、"今日日志"、"activitywatch"、"daily log"、
  "活动报告"、"时间追踪报告"、"今天做了什么"、"activity log"、"跑一下日志"时触发此 skill。
  也适用于用户想查看过去某天的活动记录，或者问"昨天的时间花在哪了"。
---

# ActivityWatch Daily Log

生成 ActivityWatch 活动日报，由当前 agent 直接生成增强版 HTML（无需 `claude -p`）。

## 前提条件

- ActivityWatch 必须在本机运行（`http://localhost:5600/api/0`）
- Python 可用（Anaconda，路径 `F:\anaconda`）
- 脚本路径：`~/.claude/skills/activitywatch-daily-log/scripts/`
- 数据目录：`F:/activitywatch-daily-log/`（config、raw、processed、reports）

## 执行步骤

### 1. 确定目标日期

- 用户未指定日期 → 默认今天
- 用户说"昨天"、"前天"等 → 解析为对应日期
- 用户给出具体日期 → 直接使用
- 日期格式：`YYYY-MM-DD`

### 2. 运行数据管道（阶段 1）

```powershell
python "C:/Users/Administrator/.claude/skills/activitywatch-daily-log/scripts/run_daily_log.py" --date <YYYY-MM-DD> --agent-mode
```

脚本会完成数据采集、聚合、分类，然后输出结构化 JSON 到 stdout。

JSON 包含：
- `date`：目标日期
- `summary`：聚合后的活动数据（类别、时长、置信度）
- `timeline`：时间线数据（已采样）
- `ai_sessions`：AI 工具会话数据
- `design_system`：设计系统 prompt 文件路径
- `output_path`：HTML 报告输出路径
- `vault_path`：Obsidian 归档路径（`10-Daily/YYYY-MM-DD.md`）
- `unclassified_count`：未分类活动数量

如果脚本报错（如 ActivityWatch 未启动），告知用户并中止。

### 2.5 分类未识别项（阶段 1.5）

`--agent-mode` 跳过了 LLM 分类步骤。如果 JSON 中 `unclassified_count > 0`，agent 必须在生成 HTML 前自行分类。

流程：
1. 读取 `summary` 中 `category` 为 `"未分类"` 或空的聚合项
2. 根据 `apps`、`domains`、`sample_titles` 判断类别，可选类别：
   - AI 编程 / 论文/文档 / 资料检索 / 沟通 / 娱乐 / 系统杂项 / 开发工具 / 其他
3. 将分类结果写回 `summary.aggregated` 对应项的 `category` 和 `confidence` 字段
4. 同步写入分类缓存 `F:/activitywatch-daily-log/config/classification_cache.json`，key 格式 `{app}|{domain}`，value 格式：`{"category": "...", "confidence": 0.85, "reason": "...", "timestamp": "ISO", "reviewed": false}`
5. 更新 `unclassified_count` 为 0（或剩余未确定数）
6. 写回 summary JSON 文件

### 3. 生成 HTML 报告（阶段 2）

**【强制】必须先调用 `frontend-design` skill，再生成 HTML。** 不可跳过、不可自行手写。

```
/frontend-design
```

调用 skill 后，按以下流程执行：

1. 读取 `design_system` 指向的设计系统 prompt 文件
2. 将 JSON 数据 + 设计系统规范一起传给 frontend-design skill 生成完整 HTML
3. 将 HTML 写入 `output_path` 指定的路径
4. 用浏览器打开：`start "" "<output_path>"`

**生成要求：**
- 严格遵循设计系统 prompt 中的 CSS 变量、布局、动画规范
- 不编造没有数据支撑的活动
- 未分类项用"可能"或"置信度较低"标注
- 包含所有必需 section：今日总览、活动类别、AI 工具详情、时间线、产出判断、分心点、建议、数据可信度

### 4. 归档到知识库

JSON 中的 `vault_path` 指向 Obsidian vault 的 `10-Daily/` 目录。

基于已生成的 HTML 日报数据，生成一份 Markdown 摘要，写入 `vault_path`：

```markdown
---
date: YYYY-MM-DD
type: daily-log
source: activitywatch
---

# YYYY-MM-DD 活动日报

## 核心指标
- 活跃时长：Xh Xm
- AFK 时长：Xh Xm
- 活动片段：N 个

## 活动类别
| 类别 | 时长 | 置信度 |
|------|------|--------|
| ... | ... | ... |

## AI 工具使用
- 工具名：时段 — 一句话描述

## 时间线（关键节点）
- HH:MM — 活动描述

## 产出判断
...

## 分心点 / 低效点
...

## 明日建议
1. ...
2. ...
3. ...
```

要求：
- 数据必须与 HTML 日报一致，不编造
- 简洁，不贴大段原文
- YAML frontmatter 包含 date、type、source

### 5. 汇报结果

向用户简要说明：
- 生成日期
- 活动类别数量、AI 会话数量
- 未分类项数量（如有）
- HTML 报告路径
- Obsidian 归档路径（`vault_path`）

## 离线演示

如果用户想测试但 ActivityWatch 未运行，可加 `--use-sample` 参数：

```powershell
python "C:/Users/Administrator/.claude/skills/activitywatch-daily-log/scripts/run_daily_log.py" --date <YYYY-MM-DD> --agent-mode --use-sample
```

注意：示例数据不代表真实活动记录。

## 降级模式

如果 agent 生成 HTML 失败，可用基础版兜底：

```powershell
python "C:/Users/Administrator/.claude/skills/activitywatch-daily-log/scripts/run_daily_log.py" --date <YYYY-MM-DD> --skip-llm
```

这会使用脚本内置的 `render_base_html` 生成基础版 HTML（无 LLM 增强）。

## 向后兼容

不加 `--agent-mode` 时，脚本仍走原流程（调用 `claude -p` 生成 HTML）。

## 目录结构

```
~/.claude/skills/activitywatch-daily-log/
├── skill.md                    # 本文件
├── scripts/
│   ├── common.py               # 公共配置和工具函数
│   ├── run_daily_log.py        # 主入口
│   ├── export_activitywatch.py # ActivityWatch 数据导出
│   ├── aggregate.py            # 数据聚合
│   ├── merge_ai_sessions.py    # AI 会话合并
│   ├── classify_llm.py         # 启发式 + LLM 分类
│   └── build_prompt_v2.py      # Prompt 构建
└── prompts/
    └── html_gen_prompt.md      # 设计系统规范

F:/activitywatch-daily-log/
├── config/
│   ├── settings.json           # 运行配置
│   └── classification_cache.json # 分类缓存
├── raw/activitywatch/          # 原始导出数据
├── processed/                  # 聚合后的 JSON
└── reports/                    # 生成的 HTML 日报
```
