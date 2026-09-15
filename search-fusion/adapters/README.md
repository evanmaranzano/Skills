# Adapters

Search Fusion 的核心不直接绑定任何 harness。每个 adapter 只负责把当前环境的搜索能力转换成统一契约。独立 `direct` adapter 的 API key 使用用户级环境变量，OAuth 使用 `~/.search-fusion/auth.json`；凭据不写入 skill。`omp` 仅是显式选择时才启用的兼容 adapter。

## Contract

```ts
interface SearchAdapter {
  name: string;
  capabilities(): Promise<SearchCapabilities> | SearchCapabilities;
  search(request: SearchRequest): Promise<SearchResponse>;
  fetch?(url: string): Promise<FetchResponse>;
}
```

adapter 返回的 metadata 只允许非敏感字段（model/authMode/requestId/usage 等），不得包含凭据；CLI 输出层还会对 `api key/authorization/bearer/token/secret` 做一次脱敏。

## 三种接入方式

### 方式一：host-orchestrated（零代码，任何 harness 可用）

Agent 自己调用自己的搜索工具，把结果组装成 input JSON 交给 Fusion：

```bash
node scripts/search-fusion.mjs --plan --pretty "要调研的问题"
# … Agent 用本 harness 的搜索工具执行返回的 requests（provider:null 由 Agent 回填）…
node scripts/search-fusion.mjs --input results.json "要调研的问题" --top 8 --pretty
node scripts/search-fusion.mjs --input results.json --next "要调研的问题"
```

input 格式见 `schemas/fusion-input.schema.json`，样例见 `tests/fixtures/host-results.json`。Agent 结果如实声明 provider 身份：单一搜索工具标一个 provider 且 `providerPin:false`（Fusion 落 L1 query-diversification）；多个独立搜索工具各标一个（落 L2/L3）。

### 方式二：外部 adapter 模块（官方扩展点，无需改 skill 代码）

写一个 JS 模块导出 `createAdapter()`（实现上方 contract），再写一份 capabilities JSON 指向它：

```json
{
  "harness": "my-harness",
  "level": "L3",
  "providerPin": true,
  "providers": ["exa", "tavily"],
  "adapter": "/absolute/path/to/my-adapter.mjs"
}
```

```bash
node scripts/search-fusion.mjs --capabilities my-capabilities.json --task comparison "查询"
```

capability 字段说明见 `schemas/capabilities.schema.json`；未提供的角色/排序字段由 `config/provider-defaults.json` 兜底。

### 方式三：内置 adapter

**`--adapter direct`（独立直连，推荐用于无 harness 集成的场景）**

直接以 REST 调用搜索 provider API，或使用 skill 自己的 OAuth token，完全不依赖 harness 登录态：

```bash
node scripts/search-fusion.mjs --doctor        # 首次运行：逐 provider 认证体检 + 配置教程
node scripts/search-fusion.mjs --adapter direct "要调研的问题"
node scripts/search-fusion.mjs --adapter direct --providers exa,tavily "要调研的问题"
```

- 独立直连 provider：exa、gemini、xai、firecrawl、tavily、tinyfish、zai、kimi、codex；兼容保留 brave/jina，另有 duckduckgo keyless 兜底；
- key 类（env key 即用）：exa `EXA_API_KEY`、tavily `TAVILY_API_KEY`、brave `BRAVE_API_KEY`、firecrawl `FIRECRAWL_API_KEY`、tinyfish `TINYFISH_API_KEY`、zai `ZAI_API_KEY`、jina `JINA_API_KEY`、xai `XAI_API_KEY`、gemini `GEMINI_API_KEY`、kimi `KIMI_SEARCH_API_KEY`；xAI OAuth bearer 也可放 `XAI_OAUTH_TOKEN`；
- keyless 兜底：duckduckgo 无需任何配置（best-effort，反爬敏感）；
- **独立 OAuth 登录**：Gemini 使用 `--login antigravity` 或 `--login gemini-cli`；xAI、Kimi、Codex 分别使用 `--login xai`、`--login kimi`、`--login codex`。登录流程和刷新逻辑在 skill 自己的 `core/oauth.mjs` 中，token 存 `~/.search-fusion/auth.json`（skill 目录之外）。
- 认证模式自选：`--auth-mode auto|key|oauth`（默认 auto = env key 优先、oauth 兜底；`key` 只用环境变量；`oauth` 强制走已登录 token）。
- `--doctor` 会显示独立 OAuth 与 env key 的状态；`--auth-mode auto|key|oauth`（默认 auto = env key 优先、OAuth 兜底）可控制选择。

**`--adapter omp`（OMP 兼容模式）**

通过 OMP 的 `runSearchQuery()` 获取结构化结果。这是可选兼容性 adapter，不是核心依赖；direct 模式不会加载它。capability 发现是**动态且 fail-open** 的：

- 池子 = OMP 已知 provider 全集 − `webSearchExclude`，外加 `webSearchOrder` 中配置但全集尚未收录的新 provider（新 provider 自动落 `general` 角色、`unknown` rank 语义，直到 `provider-defaults.json` 描述它）；
- `webSearchOrder` 只决定优先级（autoOrder 前段），未列出的 provider 仍然可用；
- adapter 内部不持有任何凭据，认证由 OMP 完成。

## 池子大 ≠ 每次都用

provider 选择由角色匹配 + 跨 retrieval family 优先驱动，并受预算约束（第一波最多 4 个、总 calls 默认 9）。`autoOrder` 靠前且角色覆盖广的 provider（如 semantic+general 双核）会高频入选——这是角色矩阵的结构性结果，不是硬编码。想让某类 provider 上场，把它在 `webSearchOrder` 中前移，或在 capabilities 中显式声明 roles。

## 当前适配器

| Adapter | 用途 | 说明 |
|---|---|---|
| `host.mjs` | 通用 host-orchestrated 模式 | 由当前 harness/Agent 调用自己的搜索工具，再把结果交给 Fusion |
| `direct.mjs` | 独立直连模式 | 独立 OAuth + 用户级环境变量的 REST 直连 + keyless duckduckgo；`--doctor` 引导配置，新机器零 harness 依赖即可用 |
| `omp-internal.mjs` | OMP 兼容模式 | 通过 OMP 当前可验证的 `runSearchQuery()` 获取结构化结果；它是兼容性 adapter，不是核心依赖 |

## ZCode（无专用 adapter，走方式一）

ZCode 下请使用 host-orchestrated 模式，**不存在也不计划做 `zcode.mjs` 专用 adapter**。原因：adapter 的前提是 harness 暴露可编程入口（如 OMP 的 `runSearchQuery()` 可被 bun import），而 ZCode 没有可 import 的搜索内部 API，也没有 headless CLI——其搜索能力只存在于模型工具调用循环中，搜索的执行者就是 Agent 模型本身。因此 Agent 在闭环中扮演的正是 `createHostAdapter({ search: fn })` 需要注入的那个 `search` 函数。

需要确定性、无人值守的批量搜索调用（benchmark runner、CI）时，用搜索 API 直连（Tavily/Exa REST）或 OMP adapter（bun），不要试图给 ZCode 做 adapter。

## 新增适配器

新增 adapter 时，不要把 harness 专有字段放进核心。只保留：

- provider ID
- URL/title/snippet/date
- provider answer/citations
- latency/model/authMode 等非敏感 metadata
- capability 声明

没有 provider pin 的 harness 仍可使用 `host.mjs`，但应把 `providerPin` 设为 `false`，此时 Fusion 会进入 `query-diversification` 或 `multi-tool-fusion` 模式。
