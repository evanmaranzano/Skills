---
name: rules-memory-refresh
user-invocable: true
description: >
  例行更新本机规则与记忆基础设施，并含本机生产拓扑的 ai-memory 双端升级
  （Windows 客户端 + 15 服务器 overlay）。触发词：更新规则与记忆系统、同步规则仓、
  刷新记忆路由、规则体检、rules refresh、memory refresh、更新本机规则、
  升级/更新 ai-memory、升到 x.y.z、aimemory 发版、双端升级、重刷 hooks/MCP、
  修 127.0.0.1:49374、install-mcp 丢 Authorization、升级 lark-cli。
  不用于项目 docs 洁癖（neat-freak）、wiki 检索/handoff（ai-memory-retrieval 等）、
  或上游通用贡献。
---

# rules-memory-refresh — 规则 / 记忆 / ai-memory 例行更新

四层一次性对齐：`~/.agents/rules/`、`~/.agents/memory/` + `MEMORY.md`、各 harness 的 `AGENTS.md` 软链（权威源 `~/.agents/AGENTS.md`）、ai-memory（客户端 + `10.10.127.15:49374`）。

**不要和 neat-freak 搞混**：neat-freak 整理项目 docs / 毕业记忆；本 skill 只动基础设施。不写 wiki 页、不 merge observation、不 prune 项目记忆。

路径用 `%USERPROFILE%` / `~/.agents`，不要写死 `26566` 或 `Administrator`。凭据只运行时读，不打印、不写入 skill / 记忆 / commit。

用户没明确要求时 **不 commit / 不 push**。`agent-memory` 09-14 已 merge origin/main（`8eeebbc`）。禁止 `pull --ff-only`，分叉时先 merge，冲突按最新业务事实。

## 流程总览

```
1. 盘点          客户端/服务器 version+status · lark-cli · 规则仓 git 分叉
2. 升 ai-memory  客户端 zip+sha256 → 15 overlay（默认不重建）
3. 升 lark-cli   非 npm 安装须手动换 exe（lark-cli update 不干活）
4. 刷新路由      install-instructions（只替换 AGENTS.md 管理块）
5. 刷新 hooks/MCP  六端；zcode 永不 install-hooks --apply
6. 健康检查      lint/curator/forget-sweep/embed --dry-run（只报告）
7. 记版本事实    更新 reference_ai_memory_local.md + MEMORY.md 索引行
```

只升客户端、不动 15：仍走 2 的 Windows 节 + 5。只刷新规则仓、不升级二进制：跳过 2–3。用户说「与服务器一致」时：现场 `docker exec`/`status` 对上客户端 `--version` 就不要追 GitHub latest（公司机 2.2.1 ≠ 服务器 2.2.0）。

## 1. 盘点

内网必须旁路 Clash：`NO_PROXY`/`no_proxy=10.10.127.15`，并清掉进程里四套 `http(s)_proxy`。GitHub 必须带 `HTTPS_PROXY=http://127.0.0.1:7897`。

```
ai-memory --version
# status 没有 --server-url。用户级环境变量不会自动进当前进程；
# 本进程必须 export AI_MEMORY_SERVER_URL=http://10.10.127.15:49374 并清掉四套 proxy，
# 否则默认打 127.0.0.1:49374（连接拒绝）。
AI_MEMORY_SERVER_URL=http://10.10.127.15:49374 ai-memory status
lark-cli --version && lark-cli doctor
cd ~/.agents && git fetch && git status -sb && git merge-base HEAD origin/main
```

对照 GitHub latest release（带代理）决定要不要升。`winget upgrade` 只报告 harness 本体，不代装。

## 2. ai-memory 双端升级

目标是可回滚、不丢数据、不把 MCP 打回 loopback。现场以命令输出为准，本页数字会过期。

### 拓扑

| 端 | 位置 | 核对 |
|---|---|---|
| Windows 客户端 | `%USERPROFILE%\.local\bin\ai-memory.exe` | `--version` |
| 15 容器 | 名 `ai-memory`，`10.10.127.15:49374` | `docker exec ai-memory ai-memory --version` |
| 数据盘 | `/opt/data/ai-memory` → `/data` | inspect Binds |
| 监听 | **HostIp=`10.10.127.15` HostPort=`49374`** | 不是 `0.0.0.0` / `127.0.0.1` |
| env | `/opt/data/ai-memory.env-2.0.0`（约 14 行） | 含 `LLM_API_KEY`，无 `AI_MEMORY_` 前缀 |
| data-dir | `%LOCALAPPDATA%\ai-memory\` | `auth-token` 在这里 |
| SSH | `video-workflow/scripts/om_ssh.py` / paramiko | **禁用 sshpass** |

镜像标签落后于容器内 `--version` 是 overlay 常态，不是失败。

### 铁律

1. **默认 overlay，不重建容器。** `docker rm` / 新 `docker run` 才会掉回旧镜像。
2. **Schema 单向。** 升完 pages=0 先停手，查是不是连错实例。
3. 碰 `10.10.127.15` 必须 `NO_PROXY`；GitHub 必须 Clash。
4. `gh -D` 用 `C:/Users/...`，不要 Git Bash 的 `/c/Users/...`。
5. hooks/MCP **必须** `--server-url http://10.10.127.15:49374`。MCP 还要 `--auth-token`（从 data-dir 读，不打印）；漏了会删掉 Authorization → 401。
6. 重建容器必须全文 `--env-file`，不要按 `AI_MEMORY_*` 过滤（会丢 `LLM_API_KEY`）。
7. 不要改官方 managed skills（`<!-- ai-memory-managed: routing-skill -->`）。

### 2.1 Windows 客户端

资产名以该 release 页为准（Windows：`ai-memory-windows-x86_64.zip` + `.sha256`）。

```powershell
$env:HTTPS_PROXY = "http://127.0.0.1:7897"
gh release download <tag> -R akitaonrails/ai-memory -p "ai-memory-windows-x86_64.zip*" -D "$env:TEMP\ai-memory-<ver>"
Get-FileHash ...\ai-memory-windows-x86_64.zip -Algorithm SHA256   # 对照 .sha256
Copy-Item $env:USERPROFILE\.local\bin\ai-memory.exe $env:USERPROFILE\.local\bin\ai-memory.exe.bak-<oldver>
Expand-Archive ...zip -DestinationPath ...\extracted -Force
Copy-Item ...\extracted\ai-memory.exe $env:USERPROFILE\.local\bin\ai-memory.exe -Force
```

验证前清代理：`NO_PROXY=10.10.127.15`，去掉四套 proxy，并 **export `AI_MEMORY_SERVER_URL`**（`status` 不接受 `--server-url`）。`ai-memory status` 的 `server:` 必须是 `http://10.10.127.15:49374`。

MSYS 写文件用 `C:/tmp/...` 正斜杠，反斜杠会被吃掉。

### 2.2 15 overlay（默认）

容器 `User=ai-memory`，改二进制必须 root。不要 `docker cp` 覆盖正在跑的 inode。备份写数据盘，不要写容器 `/tmp`。

本机拉 `ai-memory-linux-aarch64`（带 Clash）→ scp 到 15 →：

```bash
docker exec -u root ai-memory cp /usr/local/bin/ai-memory /data/backups/ai-memory.bin-<oldver>
install -o ai-memory -g ai-memory -m 0755 /tmp/ai-memory-linux-aarch64 /usr/local/bin/ai-memory
docker restart ai-memory
```

重启后 health 会 unhealthy 数分钟（2.2.0+ V61–V63 pages 表 backfill，8GB sqlite 曾 >2 分钟）。**不要当挂了就回滚。** 本机 `curl 127.0.0.1:49374` 一定失败；探测 `http://10.10.127.15:49374/mcp`，无 token → 401 才是活的。

只有需要新基础镜像，或容器已被 `docker rm`、可写层没了，才重建：本机 Docker Desktop 拉 `linux/arm64` → save → scp → 15 load → 完整 env-file 起同名容器。不要在 15 上 `docker pull`。

### 2.3 回滚

客户端：`Copy-Item .local\bin\ai-memory.exe.bak-<oldver> .local\bin\ai-memory.exe`。

服务器：把 `/opt/data/ai-memory/backups/ai-memory.bin-<oldver>` install 回 `/usr/local/bin/ai-memory` 后 restart。只回二进制，不动数据盘。禁止用 1.x 打开已升 schema 的 wiki。

## 3. lark-cli

`lark-cli update` 对非 npm 安装只打印不干活。手动下 `lark-cli-<VER>-windows-amd64.zip`，对 checksums.txt，备份后覆盖 `%LOCALAPPDATA%\lark-cli\lark-cli.exe`，再 `lark-cli doctor`（`cli_update` 应变 pass）。

## 4. 刷新 AGENTS.md 管理块

权威文件是 `~/.agents/AGENTS.md`（各 harness 软链过来）。**必须 cd 到该目录再用相对路径**（≤2.2.1：`--target` 传绝对 Windows 路径会在 cwd 造 `C:Users...` 垃圾文件）：

```
cd ~/.agents
ai-memory install-instructions --target AGENTS.md --skills-scope global --skills-agent both
```

只替换 `<!-- ai-memory:start -->` ~ `<!-- ai-memory:end -->`。本机 `AGENTS.md` 用户正文（09-11/09-13 改写）必须保留，不要用公司机旧精简稿覆盖。

## 5. 刷新 hooks / MCP

升级客户端后必做。先设**用户级** `AI_MEMORY_SERVER_URL=http://10.10.127.15:49374`，当前进程也要 export 同值。token 从 data-dir `auth-token` 读入变量，不 print。

官方端：`claude-code` `kimi-code` `codex` `open-code` `omp`；`~/.pi/agent` 存在则再刷 **pi**（只 `install-hooks --agent pi --apply`）。

**zcode 永不 `install-hooks --apply`。** 2.2.x 官方列表已含 zcode，模板是直调 `ai-memory.exe`，且注明 ZCode **每轮都发 Stop、没有 SessionEnd**。`--apply` 会在公司 wrapper 旁追加直调 exe，每事件双写。用 `~/.zcode/hooks/ai-memory-zcode.ps1`（pwsh 7 + `-NoProfile`，禁止 powershell.exe 5.1；Stop 不得清 session 状态文件，只有 `session-end` 才删）。`install-mcp --client zcode --apply` 可以刷 MCP，刷完必须再确认 hooks 仍是 wrapper、没有 `ai-memory.exe` 直调。

```
ai-memory install-hooks --agent <c> --apply --server-url http://10.10.127.15:49374
ai-memory install-mcp   --client <c> --apply --server-url http://10.10.127.15:49374 --auth-token <from-file>
```

`install-hooks` 的选择器是 `--agent`，不是 `--client`。`install-mcp --client pi` 会失败：Pi 没有原生 mcp.json，MCP 走 hooks 生成的 TS 桥，不要写 `~/.pi/agent/mcp.json`。

`install-mcp` 省略 `--auth-token` 且进程没有 `AI_MEMORY_AUTH_TOKEN` = **不写 header**。codex 首次需从 release zip 抽出 `hooks/codex/` 到 `%LOCALAPPDATA%\ai-memory\hooks\`，TUI 会提示 Hooks need review → Trust all。

2.1.0+ TS 扩展 `TOKEN = null` + `resolveToken()` 是正常的，不要手补（#625 已进模板）。改完的客户端必须重启。

扫残留（只数次数）：`127.0.0.1:49374` 应为 0（bak/会话日志除外）；`10.10.127.15:49374` 应出现在 claude/kimi/codex/zcode/omp/opencode 的 MCP 配置里。JSON 应有 `headers.Authorization`（长度约 71）。WindowsApps 的 `pwsh.exe` 0 字节 shim 不要写进 hook `command`，用真实 `WindowsApps\Microsoft.PowerShell_*\pwsh.exe`。

## 6. 健康检查（只报告不乱修）

```
ai-memory lint --no-llm --dry-run
ai-memory curator
ai-memory forget-sweep --dry-run
ai-memory embed --dry-run    # 只看本机桶；服务器缺失须 docker exec 回填
```

`forget-sweep` **默认会真删**。只报告时必须 `--dry-run`。带 LLM 的 lint 会 300s 超时，跳过。`status` 里 `M latest pages missing` 是服务器全库口径。

## 7. 记版本事实

只改事实，不改结构：`reference_ai_memory_local.md` 版本行 / 计数 / 版本历史；`MEMORY.md` 对应 L0。某 harness 行为变了再改对应 `reference_*.md`。

`cd ~/.agents && git status && git diff`。**用户明确要求才** `commit` + 带代理 `push`。已分叉则 `merge origin/main`，不要 ff-only。

## 坑表

| 现象 | 原因 | 处理 |
|---|---|---|
| `curl 127.0.0.1:49374` 失败 | 端口只绑 15 | 用 `10.10.127.15:49374`；无 token 的 401 = 活着 |
| CLI 打 15 返回 502 | 小写 `http_proxy` 走 Clash | `NO_PROXY` 并清四套 proxy |
| `install-mcp` 后全 401 | 没带 `--auth-token` | 从 data-dir 读再 apply |
| MCP 变成 127.0.0.1 | 没带 `--server-url` | 先设用户级环境变量，再六端重刷 |
| overlay 后 version 仍旧 | `docker cp` 打正在跑的 inode | 拷到 `/tmp` 再 `install`；restart |
| health 长时间 unhealthy + CPU 99% | pages 表 backfill | 等；不要重启循环 |
| 重建后 LLM 静默 | env 过滤丢了 `LLM_API_KEY` | 完整 env-file |
| `pull --ff-only` 失败 | 09-14 在 `13bc9bb` 分叉 | merge，冲突按最新业务事实 |
| `install-instructions` 造出 `C:Users...` | `--target` 绝对路径 bug | cd 到目录用相对路径；删垃圾文件 |
| `status` 连 127.0.0.1 被拒 | 当前进程没有 `AI_MEMORY_SERVER_URL`；`status` 无 `--server-url` | 本进程 export 后再跑 |
| `install-hooks --client` 报 unknown | hooks 选择器是 `--agent` | 换成 `--agent` |
| `install-mcp --client pi` rc 1 | Pi 无原生 mcp.json | 只 `install-hooks --agent pi` |
| `forget-sweep` 真删了页 | 默认非 dry-run | 只报告时加 `--dry-run` |

## 收尾汇报

① 二进制版本前后（含 sha256）；② 15 overlay 还是跳过；③ hooks/MCP 刷了哪些端、zcode 为何跳过；④ 管理块是否只替换 marker 内；⑤ lint/curator 遗留（本机可修 vs 服务器待办）；⑥ 规则仓是否分叉、有没有提交。
