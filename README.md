# wechat-hot-article

微信 24h 热文榜抓取 + 垂类评分 + 飞书文档发布 — AI Agent Skill

## 功能

- 从 [TopHub](https://tophub.today/n/WnBe01o371) 抓取微信 24h 热文榜（最多 50 条）
- 按垂类关键词自动评分排序（AI/科技/财经/健康/教育/消费/职场/娱乐）
- 搜索可靠来源补充选题背景（AIHOT、36氪、WHO、PubMed 等）
- 通过 lark-cli 创建飞书文档并设置公开权限
- 完整链路：抓榜 → 评分 → 选题 → 搜索 → 写文 → 发布

## 安装

零依赖，纯 Python 标准库。可选增强：

- `pip install curl_cffi` — Chrome TLS 指纹，自动安装
- [scrapling](https://github.com/D4Vinci/Scrapling) — 最佳反反爬（需要 Playwright）
- [lark-cli](https://github.com/nicepkg/lark-cli) — 飞书文档发布

## 使用

```bash
# 抓取 + 评分一步到位
python wechat_hot_article.py full --vertical "科技/AI/互联网" --top 10

# 单独抓取
python wechat_hot_article.py fetch

# 搜索可靠来源
python wechat_hot_article.py search --query "英伟达 财报" --vertical "AI"

# 发布到飞书
python wechat_hot_article.py publish --content article.md --title "标题" --public
```

## 子命令

| 命令 | 功能 |
|------|------|
| `fetch` | 抓取 TopHub 榜单 |
| `rank` | 按垂类关键词评分排序 |
| `search` | 搜索可靠来源 |
| `publish` | 创建飞书文档 + 设置权限 |
| `full` | fetch + rank 合并 |

## 作为 Claude Code Skill 使用

将 `skill.md` 和 `wechat_hot_article.py` 放入 skill 目录，Claude Code 会自动识别触发。

```bash
~/.claude/skills/wechat-hot-article/
├── skill.md
└── wechat_hot_article.py
```

## 反反爬策略

按优先级依次尝试：

1. **curl_cffi** — Chrome TLS 指纹模拟，自动安装
2. **scrapling** — Playwright 驱动的隐身浏览器
3. **curl** — 系统 curl 命令
4. **urllib** — Python 标准库兜底

## License

MIT
