# Skills

个人 AI Agent Skills 合集（兼容 Claude Code 与 Codex）。

## 包含 Skills

| Skill | 说明 | 触发词 |
|-------|------|--------|
| [web-hub](./web-hub/) | 统一联网能力中枢：Brave/Tavily/CDP/Playwright/Scrapling 智能路由 | "搜索"、"浏览"、"抓取"、"网页" |
| [activitywatch-daily-log](./activitywatch-daily-log/) | ActivityWatch 每日活动日报：AFK 裁剪 + agent 内联分类 + 深色主题 HTML | "日报"、"活动报告"、"daily log" |
| [wechat-hot-article](./wechat-hot-article/) | 微信 24h 热文榜抓取 + 垂类评分 + 飞书文档发布 | "热文"、"微信文章"、"选题" |
| [docx-paper-skill-zh](./docx-paper-skill-zh/) | 中文学术论文排版（课程论文/毕设/数模），Markdown 转 Word | "论文"、"docx"、"排版" |

## 安装

```bash
# 克隆到 skill 目录
# Claude Code: ~/.claude/skills/
# Codex:       ~/.codex/skills/ 或 ~/.agents/skills/
git clone https://github.com/evanmaranzano/Skills.git ~/.claude/skills/

# 或单独安装某个 skill（将目标路径替换为你的宿主目录）
cp -r web-hub ~/.claude/skills/
cp -r activitywatch-daily-log ~/.claude/skills/
cp -r wechat-hot-article ~/.claude/skills/
cp -r docx-paper-skill-zh/docx-editor-cn ~/.claude/skills/
```

## License

MIT
