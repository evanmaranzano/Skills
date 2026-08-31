# H3 工作台批量通道 — 技术参考

> 这是 `scripts/h3_batch.py`（skill 自带，部署在 15 的 /opt/data/om-deploy/）的背景知识。日常使用直接跑脚本即可，不必手调 API。脚本只允许工作台回环地址 `127.0.0.1:18090`；跨机请先做 SSH 端口转发。
> 红线：**禁止直连 `10.10.127.16:18081`** 提交任务；一律走 15 上的工作台 `127.0.0.1:18090` admin 通道。

## 为什么不能直连

16:18081 是 Molispark Design 工作台的**生产引擎**，并发=1，由工作台的公平轮转队列调度，服务线上用户。直连等于插队，会饿死普通用户。工作台改造（2026-08-26）给了 admin 账号 `daily_limit=-1`（不限额）+ `next_queued()` admin 优先调度：admin 任务插到普通用户前、但**不抢占正在生成的任务**，普通用户公平轮转不变。

## API 契约（源自工作台 app.py）

| 操作 | 方法+路径 | 说明 |
|---|---|---|
| 登录 | `POST /api/login` | JSON `{username, password}` → cookie `h3_session`（httponly，7 天）。**全程登录一次**：IP 10 分钟内 5 次失败 → 429 |
| 提交 | `POST /api/tasks` | JSON `{prompt, duration(int 5–15), aspect_ratio, task_type(t2va\|fl2va), quality(turbo\|native), image_data?, seed?}` → `{id}` |
| 轮询 | `GET /api/tasks` | **无单任务端点**，返回列表（200 条窗口，单批 ≤200），按 id 过滤；状态 `queued→generating→done/failed` |
| 取片 | `GET /api/tasks/{id}/video` | FileResponse mp4 |
| 删除 | `DELETE /api/tasks/{id}` | 仅排队中可删（退额度）；视频保留 14 天 |
| 当前用户 | `GET /api/me` | |

### 约束
- `prompt` ≤ 2000 字符
- `duration` 整数 5–15 秒（**做不了 3s**；要短片段在 Remotion 里裁）
- `aspect_ratio` ∈ {16:9, 9:16, 1:1, 4:3, 3:4}
- `quality`：`turbo`=9 步 LoRA（快，批量用这个）；`native`=50 步（慢、质量略高）
- fl2va 需 `image_data`（data URI，≤12M 字符）
- 输出 **1344×768**（16:9，短边 768 硬校验），h264+aac

## 脚本语义（h3_batch.py）

```bash
# 在 15 上跑（回环调工作台，免疫 VPN 抖动）
H3_WORKBENCH_USER=admin H3_WORKBENCH_PASS=*** \
  /opt/py312/bin/python3.12 h3_batch.py --batch proj.jsonl --wait-all
```

- **阻塞等待完整生成**：提交后 10s 轮询，到 `done` 并下载落盘才提交下一条（引擎并发=1，串行不损吞吐）。
- **单条硬超时 15 分钟**，自 `generating` 起算（`queued` 排队等待不计）；超时把工作台 id + `polling_timeout` 写日志，可凭 id 重挂。
- **断点续跑**：`<batch>.log.jsonl` 记录每条状态。重启时：`completed` 且文件存在→跳过；`submitted/polling/timeout`→凭 `workbench_task_id` **重挂轮询不重复提交**；`failed`→默认跳过，加 `--retry-failed` 重提。
- **`--wait-all`**：阻塞到全部终态，逐条 ffprobe 校验（时长、画幅、16:9 时 1344×768、h264/aac），打印汇总表，有失败以非零码退出。
- **网络韧性**：GET 等幂等请求异常时指数退避重试；POST 创建任务遇到网络异常或 5xx 不自动重试，避免服务端已创建任务后重复扣额度。
- 凭据从环境变量读，**不落盘、不进远端进程 cmdline、不写日志**（从本机编排时用 `om_ssh.run_env` 经 SSH stdin 注入）。

## 批次文件格式（jsonl，一行一片）

```json
{"prompt": "英文电影感画面描述...", "task": "t2va", "duration": 5, "ar": "16:9", "out": "/opt/data/om-deploy/out/proj_h3_1.mp4"}
```
字段：`prompt` / `task`(t2va|fl2va) / `duration`(5–15 整数) / `ar` / `out`(15 上绝对路径) / 可选 `quality`(默认 turbo) / `image`(fl2va 参考图路径) / `seed`。

## H3 prompt 写作要点

- **英文**效果最好；电影感、具体镜头运动（slow dolly / drone pull-back / macro tracking）、具体光线（golden hour / cool teal / volumetric haze）。
- **明确写 `no text, no watermark, no logos`**——H3 会尝试渲染文字但质量差，所有文字走 Remotion 矢量层。
- 16:9 B-roll 适合：环境空镜（实验室/自然/城市）、食物、运动、睡眠、微距物体、科学可视化、日出。
- 避免：需要精确文字/图表/人脸特写一致性的画面（H3 不擅长）。
- t2va 自带原生环境音轨；混音时旁白段压到 0.15，纯画面段可保留当环境床。

## 768p → 1080p 升频对策

H3 短边 768，成片 1080p：
- full-bleed cover 裁切（1344×768 → 1920×1080，竖裁约 0.8%）+ 持续 Ken Burns 缓推（静止放大最暴露软）；
- H3 上压暗 0.55 + 暗角，文字走矢量叠加层；
- 不在高对比文字下垫 H3 原图；数字/UI 特写用纯矢量场景。
