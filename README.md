# Skills

个人 AI Agent Skills 合集（兼容 Claude Code 与 Codex）。全部为自建或深度修改的 skill；第三方纯搬运 skill 已于 2026-11-04 移除。

## 包含 Skills

### 内容创作
| Skill | 说明 |
|-------|------|
| [image2-gen](./image2-gen/) | gpt-image-2 生图：海报、PPT、封面、Banner（key 走 `.env`，不入库） |
| [khazix-writer](./khazix-writer/) | 公众号长文写作 |
| [game-poster](./game-poster/) | HTML 游戏配套宣传海报 |
| [picture-book](./picture-book/) | AI 绘本全流程：故事→定妆照→逐页生图→单文件翻页绘本 |
| [wechat-hot-article](./wechat-hot-article/) | 微信热文榜→选题→公众号成文→飞书文档 |
| [hv-analysis](./hv-analysis/) | 横纵分析法深度研究 PDF 报告 |

### 工作流与效率
| Skill | 说明 |
|-------|------|
| [search-fusion](./search-fusion/) | 深度检索编排与证据融合（RRF/provenance/freshness） |
| [daily-work-log](./daily-work-log/) | 多 agent 会话汇总写入飞书工作日志 |
| [storage-analyzer](./storage-analyzer/) | 只读存储分析 + 交互式 HTML 报告 |
| [officecli](./officecli/) | Office 文档（docx/xlsx/pptx）CLI 处理 |
| [wechatide-skill](./wechatide-skill/) | 微信开发者工具 CLI 自动化 |
| [neat-freak](./neat-freak/) | 项目文档/规则/记忆收尾治理与规范审计 |
| [rules-memory-refresh](./rules-memory-refresh/) | 规则与记忆刷新 |
| [super-handoff](./super-handoff/) | 会话交接与续作双流程（写/读 HANDOFF 文档） |

### 项目专属
| Skill | 说明 |
|-------|------|
| [jszx-workspace](./jszx-workspace/) | jszx 集群特权工作区容器与公网端口管理 |
| [kid-career-portrait-batch](./kid-career-portrait-batch/) | 儿童未来职业照批量生成（含 PPTX/飞书发布） |
| [children-game-judges](./children-game-judges/) | 儿童游戏/代码作品评奖与颁奖动画页 |
| [video-workflow](./video-workflow/) | 视频生成与批量处理工作流 |

## 安装

```bash
git clone https://github.com/evanmaranzano/Skills.git ~/.agents/skills/
# ~/.claude/skills/ 与 ~/.codex/skills/ 软链到 ~/.agents/skills/
```

需要 API key 的 skill（如 image2-gen）在本目录建 `.env` 填入真实值（`.gitignore` 已排除），变量名见对应 SKILL.md。

## 安全红线

本仓库为 public：**每次提交前必须凭据扫描**（rg 模式见 `CLAUDE.md`/`AGENTS.md` 提交纪律节），凭据一律走 `.env`，不入库、不进文档。

## License

MIT
