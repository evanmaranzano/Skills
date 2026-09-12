---
name: ai-memory-upgrade
user-invocable: true
description: >
  本机生产拓扑的 ai-memory 双端升级（Windows 客户端 + 15 服务器 Docker 容器 overlay）。
  当用户说升级/更新 ai-memory、升到 x.y.z、aimemory 发版、双端升级、重刷 hooks/MCP、
  修 127.0.0.1:49374、install-mcp 丢 Authorization 时使用。不用于 wiki 检索、handoff、
  或上游通用贡献；那些走 ai-memory-retrieval / routing-install。
---

# ai-memory 生产升级（本机拓扑）

本 skill 只覆盖 **这家机器的既有接法**。目标不是“干净重建”，而是 **可回滚、不丢数据、不把 MCP 打回 loopback**。

现场事实以命令输出为准，本页数字会过期。凭据只从权威源读，**永不写入本 skill、对话、日志、记忆**。

## 拓扑（先核对再动手）

| 端 | 位置 | 核对命令 |
|---|---|---|
| Windows 客户端 | `%USERPROFILE%\.local\bin\ai-memory.exe` | `ai-memory --version` |
| 15 容器 | `10.10.127.15` 容器名 `ai-memory` | `docker exec ai-memory ai-memory --version` |
| 数据盘 | `/opt/data/ai-memory` → 容器 `/data` | `docker inspect` 的 Binds |
| 监听 | **HostIp=`10.10.127.15` HostPort=`49374`** | 不是 `0.0.0.0`，也不是 `127.0.0.1` |
| env 真值 | `/opt/data/ai-memory.env-2.0.0`（约 14 行） | 含 `LLM_API_KEY`，**无** `AI_MEMORY_` 前缀 |
| 客户端 data-dir | `%LOCALAPPDATA%\ai-memory\` | `auth-token` 文件在这里 |
| SSH | `~/.agents/skills/video-workflow/scripts/om_ssh.py` | **禁用 sshpass** |

镜像标签经常落后于二进制：`Image=akitaonrails/ai-memory:2.0.2` 而容器内 `--version` 已是 2.1.0/2.2.0，这是 overlay 常态，**不是升级失败**。

## 铁律

1. **默认 overlay，不重建容器。** `docker restart` 不清可写层。`docker rm` / 换新 `docker run` 才会掉回旧镜像。2.0.2→2.1.0 就是 overlay。
2. **Schema 单向。** OKF / DataSchemaAhead 不能降级。升完若 pages=0，先停手查是不是连错实例，不要立刻再升或回滚覆盖数据盘。
3. **内网调用必须旁路 Clash。** 系统 `http_proxy=127.0.0.1:7897`（小写）会让 CLI/`urllib` 打内网变 502，表象像服务器挂了。凡碰 `10.10.127.15`：设 `NO_PROXY`/`no_proxy=10.10.127.15`，并清掉进程里的 `http_proxy`/`HTTP_PROXY`/`https_proxy`/`HTTPS_PROXY`。
4. **GitHub 一律带 Clash。** `$env:HTTPS_PROXY='http://127.0.0.1:7897'`。`gh -D` 在 Windows 必须用 `C:/Users/...` 或 `C:\Users\...`，**不要** Git Bash 的 `/c/Users/...`（会变成字面目录 `C:\c\Users\...`）。
5. **hooks/MCP 必须显式 `--server-url http://10.10.127.15:49374`。** 漏了就会写成 `http://127.0.0.1:49374`。MCP 还要 `--auth-token`（从 data-dir `auth-token` 读，不打印）；漏了会 **删掉 Authorization 头**，客户端 401。
6. **不要按 `AI_MEMORY_*` 过滤环境变量。** 重建容器时必须 `--env-file /opt/data/ai-memory.env-2.0.0` 全文。过滤会丢掉 `LLM_API_KEY`，LLM 静默 401。
7. **凭据不外泄。** token / env-file / SSH 密码只运行时读。检查 MCP 配置时只打印 key 名和字符串长度。

## 标准流程

### 0. 发版与现状

1. GitHub `akitaonrails/ai-memory` 的 Latest release tag（带代理）。
2. 本机 `ai-memory --version`（先 `NO_PROXY`）。
3. 15：`docker inspect ai-memory` 看 Image / Binds / PortBindings / Restart / Env **名字**（不要 dump 值）。
4. 15：`docker exec ai-memory ai-memory --version` 与 `ai-memory status`。
5. 确认 wiki 页数、health。页数是回滚锚点。

资产文件名随 tag 变，到该 release 页核对，不要写死旧文件名：

- Windows：`ai-memory-windows-x86_64.zip` + `.sha256`
- 容器（aarch64）：`ai-memory-linux-aarch64` + `.sha256`

### 1. Windows 客户端

```powershell
$env:HTTPS_PROXY = "http://127.0.0.1:7897"
# gh -D 用 Windows 路径，不要 /c/Users/...
gh release download <tag> -R akitaonrails/ai-memory -p "ai-memory-windows-x86_64.zip*" -D "$env:TEMP\ai-memory-<ver>"
Get-FileHash ...\ai-memory-windows-x86_64.zip -Algorithm SHA256
# 对照 .sha256
Copy-Item $env:USERPROFILE\.local\bin\ai-memory.exe $env:USERPROFILE\.local\bin\ai-memory.exe.bak-<oldver>
Expand-Archive ...\ai-memory-windows-x86_64.zip -DestinationPath ...\extracted -Force
Copy-Item ...\extracted\ai-memory.exe $env:USERPROFILE\.local\bin\ai-memory.exe -Force
```

验证（必须清代理）：

```powershell
$env:NO_PROXY = "10.10.127.15"; $env:no_proxy = "10.10.127.15"
Remove-Item Env:http_proxy,Env:https_proxy,Env:HTTP_PROXY,Env:HTTPS_PROXY -ErrorAction SilentlyContinue
ai-memory --version
ai-memory status
```

`server_url` 应是 `http://10.10.127.15:49374`。若变成 loopback，先修用户环境变量再重刷 hooks。

### 2. 15 容器 overlay（默认升法）

容器 `User=ai-memory`，改 `/usr/local/bin/ai-memory` 必须 **root**。**不要** `docker cp` 直接覆盖正在跑的二进制（file busy / 改了看不见）。

SSH 用 `om_ssh.py` / paramiko，密码只从桌面「服务器信息整理」最新日期版读取。

```bash
# 本机拉 aarch64 二进制（带 Clash），scp 到 15 后：
install -o ai-memory -g ai-memory -m 0755 /tmp/ai-memory-linux-aarch64 /usr/local/bin/ai-memory
# 备份不要写容器 /tmp（restart 可能丢）。放到数据盘：
docker exec -u root ai-memory cp /usr/local/bin/ai-memory /data/backups/ai-memory.bin-<oldver>
docker restart ai-memory
```

`docker exec` 的 `/tmp` 是 **容器内** `/tmp`，不是宿主机 `/tmp`。备份以 `/opt/data/ai-memory/backups/` 为准。

**重启后 health 会 unhealthy 数分钟。** 2.2.0 起 V61–V63 会打满 CPU 做 pages 表迁移（约 8GB sqlite 曾 >2 分钟）。这是正常 backfill，**不要当挂了就回滚**。轮询：

```bash
docker inspect --format '{{.State.Health.Status}}' ai-memory
docker exec ai-memory ai-memory --version
docker exec ai-memory ai-memory status
```

从 **本机** `curl http://127.0.0.1:49374/...` **一定失败**（端口没绑 loopback）。探测用 `http://10.10.127.15:49374/mcp`（无 token → 401 才是活的）。

### 3. 只有这些情况才重建镜像

- 需要新基础镜像/系统库，overlay 不够。
- 有人已经 `docker rm` 了容器，可写层没了。

本机 Docker Desktop 拉 `linux/arm64` → `docker save` → scp → 15 `docker load` → 用 **完整 env-file** 起同名容器（同 bind、同 HostIp、同 restart）。15 自己 `docker pull` 经常超时，不要在 15 上拉 Docker Hub。

重建后立刻核对：`LLM_API_KEY` 在容器 env **名字**里、embedding 维数、页数与升级前一致。

### 4. 重刷六端 hooks + MCP（升级后必做）

漏 `--server-url` 的 `install-mcp --apply` 会把已修好的 MCP 打回 `127.0.0.1` 并丢掉 Authorization。这是 2.2.0 当晚的实锤。

先写 **用户级**（不是进程级）环境变量，避免下次 apply 再回 loopback：

- `AI_MEMORY_SERVER_URL=http://10.10.127.15:49374`

token 从 `%LOCALAPPDATA%\ai-memory\auth-token` 读入变量，**不要 print**。

六个 client：`claude-code` `kimi-code` `codex` `open-code` `zcode` `omp`。

```text
ai-memory install-hooks --client <c> --apply --server-url http://10.10.127.15:49374
ai-memory install-mcp   --client <c> --apply --server-url http://10.10.127.15:49374 --auth-token <from-file>
```

`install-mcp --auth-token` 的帮助原文：省略时用 config loader 解析到的 token；进程里没有 `AI_MEMORY_AUTH_TOKEN` 时等于 **不写 header**。所以生产 apply **显式传文件里的 token**。

2.1.0+ 官方 TS 集成是 `TOKEN = null` + `resolveToken()`（环境变量或 data-dir `auth-token`）。**不要再手工往生成物里写死 TOKEN**（那是 #625 之前的补丁）。

zcode 的 `install-hooks` 在 URL 没变时可能 no-op（上游 #600）。MCP 被改过、hooks 没改时，以文件内容为准，不要只看 exit 0。

改完配置的客户端 **必须重启** 才会连新 MCP。

扫残留（只数次数，不要把 token 打出来）：

- `127.0.0.1:49374` 应为 0（会话日志/bak 除外）
- `10.10.127.15:49374` 应出现在：
  - `~/.claude.json`、`~/.claude/settings.json`
  - `~/.kimi-code/mcp.json`
  - `~/.codex/config.toml`
  - `~/.zcode/cli/config.json`
  - `~/.omp/agent/mcp.json`、`~/.omp/agent/extensions/ai-memory-omp.ts`
  - `~/.config/opencode/opencode.json`、`~/.config/opencode/plugins/ai-memory.ts`

JSON MCP 条目应有 `headers.Authorization`（长度约 71）；Codex 在 `[mcp_servers.ai-memory.http_headers]`。

## 验收

- 双端 `--version` 等于目标 tag。
- 容器 `Health=healthy`，`status` 页数与升级前同量级（不是 0）。
- `/mcp` 无 token → 401；有 Bearer → MCP 握手。
- embedding provider 仍是现场的 Qwen/TEI，不是被重置的默认。
- 六端无 `127.0.0.1:49374`；MCP 有 Authorization 头。
- 镜像标签仍是旧的 **可以**，以二进制 version 为准。

## 坑表（按出现顺序）

| 现象 | 真实原因 | 处理 |
|---|---|---|
| 本机 `curl 127.0.0.1:49374` 失败，以为服务器挂了 | 端口只绑 `10.10.127.15` | 用 `10.10.127.15:49374`；无 token 的 401 表示活着 |
| CLI/python 打 15 返回 502 | 小写 `http_proxy` 走 Clash | `NO_PROXY=10.10.127.15` 并清掉四套 proxy 环境变量 |
| `install-mcp` 后客户端全 401 | apply 未带 `--auth-token`，header 被覆盖删掉 | 从 data-dir 读 token 再 apply；检查 key 存在即可 |
| MCP url 变成 127.0.0.1 | apply 未带 `--server-url`，且用户级 `AI_MEMORY_SERVER_URL` 未设 | 先设用户级环境变量，再六端重刷 |
| overlay 后 `--version` 仍旧 | `docker cp` 覆盖了正在跑的 inode，或没 `-u root` | 拷到 `/tmp` 再 `install`；`docker restart` |
| 备份找不到 | `docker exec` 写的是容器 `/tmp` | 备份到 `/data/backups/`（宿主机 `/opt/data/ai-memory/backups/`） |
| health 一直 unhealthy + CPU 99% | V61–V63 pages 表 backfill | 等；看 sqlite 是否还在写。不要重启循环 |
| 重建后 LLM 全静默 | env 按 `AI_MEMORY_*` 过滤，丢了 `LLM_API_KEY` | `--env-file` 用完整文件 |
| `gh -D /c/Users/...` 下到奇怪目录 | Windows `gh` 不认 Git Bash 路径 | `-D C:/Users/Administrator/AppData/Local/Temp/...` |
| 15 上 `docker pull` 超时 | 内网到 Docker Hub 不通 | 本机 pull `linux/arm64` → save → scp → load |
| 升完检索变差 | #672 的 session-recall / L0 abstract **默认关** | 不要顺手打开；要开先跑黄金集 |
| TS 生成物 `TOKEN = null` | 2.1.0+ 的 `resolveToken()` | 正常；不要手补 |

## 明确不要做

- 不要为了“镜像标签对齐”去 `docker rm` 重建——这会丢掉 overlay，且容易丢 `LLM_API_KEY`。
- 不要在 15 上直接 `docker pull`。
- 不要把 Bearer / env-file / SSH 密码写进 skill、记忆、commit。本仓库是 **public**。
- 不要升级后自动改 retrieval / reranker 默认值。
- 不要用本 skill 改 ai-memory 官方 managed skills（`ai-memory-retrieval` 等带 `<!-- ai-memory-managed: routing-skill -->`）。

## 回滚

客户端：`Copy-Item .local\bin\ai-memory.exe.bak-<oldver> .local\bin\ai-memory.exe`。

服务器 overlay：把 `/opt/data/ai-memory/backups/ai-memory.bin-<oldver>` `install` 回 `/usr/local/bin/ai-memory` 后 `docker restart`。只回二进制，不动 `/opt/data/ai-memory` 数据盘。**禁止**用更旧的 1.x / 未迁 schema 的二进制打开已升级的 wiki。
