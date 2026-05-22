---
name: wechat-hot-article
description: "Use when the user wants to create a WeChat public account article from trending topics, mentions WeChat hot articles (微信热文榜), TopHub leaderboard, 公众号推文, content topic selection (选题), or wants a complete workflow from trend analysis to a shareable Feishu document. Also use when user identifies as a blogger/content creator asking for hot topic based article generation."
metadata:
  requires:
    bins: ["python3"]
---

# WeChat Hot Article Skill

## 触发场景

当用户提出以下任一需求时使用本 skill：

- "我是科技区博主，帮我根据微信24h热文榜写公众号推文"
- "根据微信热文榜给我选题并写成公众号文章"
- "抓 TopHub 微信24h 热文榜，整理成飞书文档"
- "帮我做今日热点公众号推文"
- 用户提到：微信热文榜、TopHub、公众号推文、飞书文档、科技区博主、内容选题、热点追踪

## 核心工具

本 skill 使用 `wechat_hot_article.py` 脚本（纯 Python stdlib，无需 pip install）。

五个子命令：

| 命令 | 功能 | 依赖 |
|------|------|------|
| `fetch` | 抓取 TopHub 榜单 | Python（自动尝试 scrapling → curl → urllib） |
| `rank` | 按垂类关键词评分排序 | Python |
| `search` | 搜索可靠来源补充选题背景 | Python |
| `publish` | 创建飞书文档 + 设置权限 | Python + lark-cli |
| `full` | fetch + rank 合并 | Python |

## 固定目标

你必须完成完整链路：

1. 从 TopHub 获取微信 24h 热文榜。
2. 根据用户给出的身份、主题、赛道或受众自动归类。
3. 不要询问用户，不要让用户选择方向。
4. 直接确定一个最适合的推文选题。
5. 明确告诉用户：为什么选择这个选题。
6. 对该选题进行简单 fetch / search，补充背景信息。
7. 写一篇微信公众号推文。
8. 用 `lark-cli` 创建飞书文档。
9. 设置飞书文档为“互联网获得链接的人都可阅读”。
10. 最后回复用户：选题、选择原因、飞书文档链接、权限设置结果。

## 关键原则

- **不要编造榜单内容。** 榜单抓取失败时必须停止，并说明失败原因。
- **不要尝试抓取微信原始文章。** 微信有反爬机制，会返回验证页面或空内容。选题确定后，使用 `search` 子命令或 WebFetch 搜索可靠来源（WHO、AHA、PubMed、权威媒体）。
- **不要询问用户补充信息。** 信息不足时使用合理默认值。
- **不要机械复述榜单。** 必须完成“热点 → 垂类匹配 → 选题判断 → 成文”的内容转化。
- **不要输出营销号标题党，** 要有事实、逻辑和观点。
- **涉及事实性内容时，** 必须用 search 补充来源，不要凭记忆写。
- **公众号推文应是草稿，** 不要自动发布到微信公众号。

## 工作流

### Step 1：提取用户画像

从用户请求中提取垂类、身份、目标、风格。信息不足时使用默认值：

- 默认身份：泛科技 / AI 效率类博主
- 默认受众：普通职场人、内容创作者、AI 工具用户
- 默认风格：专业但易读，观点鲜明，不油腻

### Step 2：抓取 + 评分

```bash
python wechat_hot_article.py full \
  --vertical "科技/AI/互联网" \
  --top 10 \
  --out /tmp/wechat_hot.json
```

### Step 3：垂类筛选

脚本按关键词匹配自动评分：

| 因素 | 加分 |
|------|------|
| 与垂类高度匹配 | +5 |
| 榜单排名靠前 | +3 |
| 争议/反转/曝光 | +3 |
| 趋势/突破/发布 | +3 |
| 疑似标题党 | -3 |

### Step 4：确定选题

输出一个确定选题，不要给多个选项。

### Step 5：搜索可靠来源

```bash
python wechat_hot_article.py search \
  --query "关键词" \
  --vertical "垂类" \
  --out /tmp/topic_search.json
```

已验证可达的来源：AIHOT、36氪、虎嗅、WHO、PubMed、丁香医生、果壳、澎湃新闻等。

### Step 6：写公众号推文

结构：热点解读 → 垂类关联 → 核心观点 → 具体建议 → 趋势判断 → 参考来源。

### Step 7：创建飞书文档 + 设置权限

```bash
python wechat_hot_article.py publish \
  --content /tmp/wechat_article.md \
  --title "文章标题" \
  --public \
  --out /tmp/feishu_publish.json
```

### Step 8：回复用户

选题 + 选择原因 + 飞书文档链接 + 权限状态。
