# Skills 仓库

自建 Claude Code / Codex skills 集合。本仓库是全量 skill 源码的唯一源头；`~/.agents/skills/` 是同 remote（evanmaranzano/Skills）的 sparse-checkout 工作副本，跟踪清单以 `.git/info/sparse-checkout` 为准（当前 16 项：activitywatch-daily-log、children-game-judges、daily-work-log、game-poster、hv-analysis、image2-gen、khazix-writer、kimi-webbridge、last30days、neat-freak、officecli、scrapling-official、storage-analyzer、two-voice-explainer、web-hub、wechatide-skill；其中 activitywatch-daily-log、last30days、web-hub 三项当前目录缺失），`~/.claude/skills/` 与 `~/.codex/skills/` 是指向 `~/.agents/skills/` 的软链接。其余 skill（lark-* 多数、aihot、frontend-skill 等）在本机 `.agents` 副本中被 .gitignore 排除，不在本仓库跟踪。

## 管理约定

- 新 skill 开发在本仓库进行；需要在本机启用时再到 `~/.agents/skills/` 执行 `git sparse-checkout add <name> && git pull`。
- `~/.agents/skills/.gitignore` 里的排除清单是"本机已装但未纳入版本管理"的 skill，不等于本仓库内容。
- SKILL.md frontmatter 必须加 `user-invocable: true` 才会被 Claude Code 发现为可用 skill。

## daily-work-log / two-voice-explainer

- `daily-work-log` 扫描多个 agent 的会话并整理到飞书《工作日志》；执行时依赖飞书 CLI/认证，具体流程以对应 `SKILL.md` 为准。
- `two-voice-explainer` 已独立打包 SSH 助手、H3 批量脚本和 Remotion 完整参考工程，不依赖特定工作区；仅依赖本机 Python/edge-tts/ffmpeg 与 15 服务器通道。
- H3 任务必须经 15 服务器的 Molispark 工作台 admin 通道，禁止直连 16:18081；凭据只运行时读取桌面「服务器信息整理」最新日期版，不写入仓库。

## children-game-judges（评分与颁奖视觉决策，2026-07-15 定稿）

- 评分基调：五维（创意想象力/完成度质量/技术探索/视听表现/趣味可玩性，各 0-20），每维 19 分为常态、全员总分 95+。
- 奖项分配：`scores.json` 三个奖项都没填 `winnerIds` 时按总分蛇形均分（15 组→5/5/5、各奖总分均衡）；任一奖项填了则走手动覆盖模式。
- 视觉：浅色调——暖象牙舞台 + 近不透明浅色卡片（主题色细边/光晕/同心圆纹理）；奖项名与图标用紫/珊瑚/青三主题色加深版作身份色；正文深紫墨；金色加深后用于标题/分数/按钮等仪式元素（由早期深色"星光典藏奖牌"版改为浅色）。
- 摩力创境 logo 为方形，CSS 单独放大一档以与横向的加速中心 logo 视觉平衡。

## video-judges（视频评奖，2026-08-18 由 children-game-judges 改造）

- 输入为视频文件夹顶层文件（.mp4/.mov/.mkv/.avi/.webm，不递归），一视频一参与者，id 按文件名排序 `video-001…`。
- 无评分：每个视频只有 agent 填写的 2-4 句中文评价/颁奖词（videos.json 的 comment）和一个 awardId；awardId 全缺时按名单顺序向当前人数最少的奖项轮转均分，兼容按奖项名填写。
- 视频理解由调用方 agent 完成：understand-video-cloud 只用 Gemini（`understand_video.py --models "[福利]gemini-3.7-flash"`，`--models` 为 2026-08-22 新增的队列过滤参数），Gemini 失败直接回退 new-api 网关 Qwen3.8-27B 抽帧识别（参考 `~/.kimi-work/recognize_videos.py`），不再走百炼轮询队列；API key 只从桌面《服务器信息整理》最新版取，不落 skill。
- 封面：优先 `<视频名>.cover.<ext>`（output 或 input 目录），否则 ffmpeg 抽 1 秒帧缩放到 ≤960px；Pillow 改为可选依赖，缺省时图片原样嵌入。封面记录横竖向（Pillow 或 stdlib 解析 JPEG/PNG 头），9:16 竖屏封面在详情页居中不裁剪（max-height 58vh + contain），获奖者列表缩略图换竖版 24×42。
- 视觉沿用 children-game-judges 浅色三卡翻卡方案；详情为模态弹层（半透明遮罩+blur+pop 动画，✕/‹返回/点遮罩/Esc 关闭），左右两栏：左栏信息（奖项 chip 用奖项主题色、作品名、金色分割线、✦评委寄语✦ 全文），右栏深色媒体区播放复制到输出目录的原视频（相对路径、按 videoWidth/Height 自适应比例，文件缺失回退内嵌封面图）；窄屏 <820px 上下堆叠。index.html 单独拷走仍可看封面与文字。
- `assets/award-music.mp3` 存在时 base64 内嵌为 `<audio loop>`，加载即尝试播放、被拦截则首次点击/按键起播后一直循环；缺失时静默跳过。--event 默认「摩力AI亲子公益沙龙」（不写期数）。
- 防御：--output 等于或嵌套于 --input 时直接报错。

## web-hub（架构与运维要点）

- 核心能力：CDP 浏览器代理（带登录态）+ 本地书签/历史检索 + 智能工具选择；依赖 Node.js 22+。
- Chrome 调试必须同时加 `--remote-debugging-port=9222` 和 `--user-data-dir`，仅加 port 不生效；9222 被 Edge 占用时用 9223。
- DevToolsActivePort 可能过期，fallback `http://127.0.0.1:PORT/json/version`。
- Chrome 143 截图后导航可能挂起；web-hub 已用截图前 layout、截图后 `Page.disable` 规避。
- 截图保存到 Node `os.tmpdir()/cdp-screenshots/`，仅图片扩展名，禁止覆盖。
- CDP token：MINGW64 `$TMPDIR` 可能为空，优先读 `/tmp/cdp-proxy-token` 或 Node `os.tmpdir()`。
- find-url 默认脱敏 URL query/hash；需完整 URL 用 `--full-url`，无关键词查历史需 `--all`。
- 自动触发不可靠，联网操作需用户手动 `/web-hub`。
