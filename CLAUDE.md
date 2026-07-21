# Skills 仓库

自建 Claude Code / Codex skills 集合。本仓库是全量 skill 源码的唯一源头；`~/.agents/skills/` 是同 remote（evanmaranzano/Skills）的 sparse-checkout 工作副本，只跟踪 activitywatch-daily-log、last30days、web-hub 三个已安装 skill，`~/.claude/skills/` 与 `~/.codex/skills/` 是指向 `~/.agents/skills/` 的软链接。其余 skill（lark-*、officecli、neat-freak 等）在本机 `.agents` 副本中被 .gitignore 排除，不在本仓库跟踪。

## 管理约定

- 新 skill 开发在本仓库进行；需要在本机启用时再到 `~/.agents/skills/` 执行 `git sparse-checkout add <name> && git pull`。
- `~/.agents/skills/.gitignore` 里的排除清单是"本机已装但未纳入版本管理"的 skill，不等于本仓库内容。
- SKILL.md frontmatter 必须加 `user-invocable: true` 才会被 Claude Code 发现为可用 skill。

## children-game-judges（评分与颁奖视觉决策，2026-07-15 定稿）

- 评分基调：五维（创意想象力/完成度质量/技术探索/视听表现/趣味可玩性，各 0-20），每维 19 分为常态、全员总分 95+。
- 奖项分配：`scores.json` 三个奖项都没填 `winnerIds` 时按总分蛇形均分（15 组→5/5/5、各奖总分均衡）；任一奖项填了则走手动覆盖模式。
- 视觉：浅色调——暖象牙舞台 + 近不透明浅色卡片（主题色细边/光晕/同心圆纹理）；奖项名与图标用紫/珊瑚/青三主题色加深版作身份色；正文深紫墨；金色加深后用于标题/分数/按钮等仪式元素（由早期深色"星光典藏奖牌"版改为浅色）。
- 摩力创境 logo 为方形，CSS 单独放大一档以与横向的加速中心 logo 视觉平衡。

## web-hub（架构与运维要点）

- 核心能力：CDP 浏览器代理（带登录态）+ 本地书签/历史检索 + 智能工具选择；依赖 Node.js 22+。
- Chrome 调试必须同时加 `--remote-debugging-port=9222` 和 `--user-data-dir`，仅加 port 不生效；9222 被 Edge 占用时用 9223。
- DevToolsActivePort 可能过期，fallback `http://127.0.0.1:PORT/json/version`。
- Chrome 143 截图后导航可能挂起；web-hub 已用截图前 layout、截图后 `Page.disable` 规避。
- 截图保存到 Node `os.tmpdir()/cdp-screenshots/`，仅图片扩展名，禁止覆盖。
- CDP token：MINGW64 `$TMPDIR` 可能为空，优先读 `/tmp/cdp-proxy-token` 或 Node `os.tmpdir()`。
- find-url 默认脱敏 URL query/hash；需完整 URL 用 `--full-url`，无关键词查历史需 `--all`。
- 自动触发不可靠，联网操作需用户手动 `/web-hub`。
