---
name: rules-memory-refresh
description: 例行更新本机规则与记忆系统（rules/memory/AGENTS.md/ai-memory 客户端/lark-cli/skills）。触发词：更新规则与记忆系统、同步规则仓、刷新记忆路由、规则体检、rules refresh、memory refresh、更新本机规则、升级 ai-memory 客户端、升级 lark-cli。当用户要求把 ~/.agents 规则/记忆、各 harness 的 AGENTS.md 管理块、ai-memory hooks、lark-cli skills 等「规则与记忆基础设施」同步到最新时使用。
---

# rules-memory-refresh — 规则与记忆系统例行更新

> 本机的「规则与记忆」分布在四层：`~/.agents/rules/`（可移植规则）、`~/.agents/memory/`（人工策划记忆 + MEMORY.md 索引）、各 harness 的 AGENTS.md 软链（权威源 `~/.agents/AGENTS.md`，ai-memory 管理块在其中）、ai-memory 服务端（10.10.127.15:49374）。本 skill 把四层一次性对齐到最新。

## 适用范围与边界

- **只更新基础设施，不碰项目记忆内容**：不写 wiki 页、不合并 observation、不 prune stale memory（那是 neat-freak / ai-memory-learning-maintenance 的活）。
- **公司机路径**：规则仓 = `C:\Users\26566\.agents`（git 仓，remote = github.com/evanmaranzano/agent-memory）；家庭机 = `C:\Users\Administrator\.agents`，流程相同。
- **凭据**：GitHub push 走 `HTTPS_PROXY=http://127.0.0.1:7897`；ai-memory Bearer token 在用户级环境变量 `AI_MEMORY_AUTH_TOKEN`，不要打印。
- 全部操作本机可逆（git commit 前可 diff；二进制升级留 `.bak-<旧版>` 备份）。

## 流程总览

```
1. 盘点版本        ai-memory --version / status · lark-cli --version / doctor · winget upgrade
2. 升级二进制      ai-memory（GitHub release zip + sha256）· lark-cli（同上；lark-cli update 自检非 npm 安装时须手动）
3. 刷新路由        ai-memory install-instructions（AGENTS.md 管理块 + managed skills）
4. 刷新 hooks      ai-memory install-hooks --agent <名> --apply（zcode 除外！）
5. 健康检查        ai-memory lint --no-llm · curator · forget-sweep · embed --dry-run
6. 同步记忆        更新 ~/.agents/memory 中版本事实 → git add/commit/push
```

## 1. 盘点版本

```bash
ai-memory --version          # 本机客户端
ai-memory status             # 服务器版本 + pages/sessions/observations/embeddings 计数
lark-cli --version
lark-cli doctor              # 含 cli_update 检查（pass=最新 / warn=有新版）
winget upgrade               # 顺手看 harness 本体（ZCode/Kimi 等）有无更新，但只报告不代装
```

对照 GitHub 最新 release 决定是否升级：

```bash
# 需代理
curl -s https://api.github.com/repos/akitaonrails/ai-memory/releases/latest | grep tag_name
curl -s https://api.github.com/repos/larksuite/cli/releases/latest | grep tag_name
```

## 2. 升级二进制

两个二进制都不走 winget（查无包），一律手动换 exe。**先备份再覆盖**：

```bash
# ai-memory（公司机）
curl -sL -o C:/tmp/aim.zip https://github.com/akitaonrails/ai-memory/releases/download/v<VER>/ai-memory-windows-x86_64.zip
curl -sL https://github.com/akitaonrails/ai-memory/releases/download/v<VER>/ai-memory-windows-x86_64.zip.sha256
sha256sum C:/tmp/aim.zip    # 必须与 .sha256 文件一致
unzip -o -d C:/tmp/aim C:/tmp/aim.zip
cp C:\Users\26566\.local\bin\ai-memory.exe C:\Users\26566\.local\bin\ai-memory.exe.bak-<旧版>
cp C:/tmp/aim/ai-memory.exe C:\Users\26566\.local\bin\ai-memory.exe
ai-memory --version && ai-memory status

# lark-cli —— `lark-cli update` 对非 npm 安装只打印提示不干活，须手动下载
curl -s https://api.github.com/repos/larksuite/cli/releases/latest   # assets 里找 lark-cli-<VER>-windows-amd64.zip
curl -L -o C:/tmp/lark.zip <browser_download_url>
sha256sum C:/tmp/lark.zip   # 比对 release 的 checksums.txt
unzip -o -d C:/tmp/lark C:/tmp/lark.zip
cp C:/tmp/lark/lark-cli.exe C:\Users\26566\AppData\Local\lark-cli\lark-cli.exe
lark-cli doctor    # cli_update 应变 pass
```

⚠️ **MSYS/Git Bash 路径坑**：`curl -o C:\tmp\x.zip` 里的反斜杠会被吃掉成 `C:tmpx.zip`，写文件用 `C:/tmp/x.zip` 正斜杠；`unzip` 同理。下完用 `glob C:\tmp\*.zip` 确认真实落点。

## 3. 刷新 ai-memory 路由（AGENTS.md 管理块 + managed skills）

```bash
# 权威 AGENTS.md 在 ~/.omp/agent/AGENTS.md（软链自此）。⚠️ 必须先 cd 再用相对路径：
cd C:\Users\26566\.omp\agent
ai-memory install-instructions --target AGENTS.md --skills-scope global --skills-agent both
```

- 幂等：只替换 `<!-- ai-memory:start -->` ~ `<!-- ai-memory:end -->` 之间内容，其余用户内容不动。
- skills 装到 `~/.claude/skills/ai-memory-*/` 和 `~/.agents/skills/ai-memory-*/`（后者与 `~/.claude/skills` 有软链关系，详见 `reference_skills_symlink_structure`）。
- **⚠️ 已知 bug（≤2.2.1）**：`--target` 传绝对 Windows 路径会被当相对路径，在 cwd 创建 `C:Users26566.ompagentAGENTS.md` 垃圾文件。中招后删掉该文件，cd 到目标目录重跑。

## 4. 刷新 hooks

**升级 ai-memory 客户端后必须重刷**（hooks 由旧版生成，版本错配会静默丢捕获）：

```bash
ai-memory install-hooks --agent claude-code --apply
ai-memory install-hooks --agent kimi-code --apply
ai-memory install-hooks --agent pi --apply      # 重写 ~/.pi/agent/extensions/ai-memory-pi.ts
ai-memory install-hooks --agent omp --apply     # 重写 ~/.omp/agent/extensions/ai-memory-omp.ts
# open-code 如装有：--agent open-code --apply
```

- **⚠️ zcode 永不走 install-hooks --apply**：官方模板只做「转发 payload」，无跨事件 session-id 状态维护（2.2.1 实测 `hook-state/` 目录不被官方路径创建），且会在已有 wrapper 旁追加重复 hook 造成双写（09-14 已清理，备份 `config.json.bak-pre-cleanup-20260914`）。zcode 用 `~/.zcode/hooks/ai-memory-zcode.ps1` 手动 pwsh wrapper（09-14 修正版：stop 不删状态文件、仅 SessionEnd 闭合、带 id 事件同步状态文件），详见 `reference_ai_memory_local.md` ZCode 节。
- **TS 扩展补丁（历史）**：≤2.1.0 生成的 omp/pi/opencode 扩展有 `TOKEN=null` + `fetchHandoff` 不校验 `response.ok` bug，需手动打补丁；**PR #625 已合并，≥2.2.1 生成模板自带修复，补丁已退役**。验证法：grep 扩展里的 `resolveToken` 应有 env→auth-token 文件回读、`fetchHandoff` 应有 `if (!response.ok) return undefined;`。
- 刷完后 pi/omp 需重启才加载新扩展。

## 5. 健康检查（只读，发现的问题只报告不乱修）

```bash
ai-memory lint --no-llm --dry-run   # 规则版死链/重复检查（带 LLM 的版本 300s 超时跑不完，跳过）
ai-memory curator                   # 保守策展报告（dangling link 等 warning）
ai-memory forget-sweep              # 保留策略清扫（expired/TTL 页），输出应为 0 evicted 才算健康
ai-memory embed --dry-run           # 本机桶 embedding 缺失检查
```

注意 `ai-memory status` 里 `embeddings: N rows; M latest pages missing` 是**服务器全库**口径，客户端 `embed` 只作用本机项目桶（dry-run 显示 0 属正常），服务器侧缺失须在服务器上 `docker exec ai-memory ai-memory embed` 回填。

## 6. 同步记忆并推送

把版本事实写回 memory（只改事实，不改结构）：

- `reference_ai_memory_local.md`：服务器/客户端版本行、数据计数行、版本历史节追加一条。
- `MEMORY.md`：索引里对应条目一句话同步。
- 若某 harness 有行为变化（如补丁退役），更新对应 `reference_*.md`。

然后：

```bash
cd C:\Users\26566\.agents
git status --short          # 确认没有混入无关改动
git diff                    # 过一遍
git add -A && git commit -m "docs(memory): <日期+摘要>"
HTTPS_PROXY=http://127.0.0.1:7897 git push
```

## 收尾汇报要素

按层汇报：①规则仓 commit 哈希与改动文件；②二进制版本前后对照（含 sha256 校验结论）；③hooks 刷新了哪些 agent、zcode 为何跳过；④lint/curator 遗留问题（区分「本机可修」与「服务器侧待办」）；⑤家庭机版本差距提醒。

## 家庭机差异提醒

- 路径 `26566` → `Administrator`；家庭机 ai-memory 客户端通常落后（以 `reference_ai_memory_local.md` 记录为准），升级后同样重刷 hooks（家庭机有六端：claude/codex/kimi/zcode/open-code/omp，zcode 同样跳过）。
- 家庭机 omp/opencode TS 扩展补丁在 ≥2.2.1 升级后同样退役。
