# Search Fusion 架构与设计说明

## 1. 定位

`search-fusion` 是一个 harness-agnostic 的深度搜索编排与证据融合 Skill。核心不绑定 OMP、Pi、Claude Code、Codex、OpenCode 或任何特定搜索 provider；harness 只负责暴露当前可用的搜索能力，核心负责规划、融合、排序和证据覆盖判断。

`ARCHITECTURE.md` 是设计说明，不是运行时必需文件；真正被 harness 加载的是 `SKILL.md` 和代码。

```text
普通 web search
    ↓
host native search
    ↓
不进入 Search Fusion

深入调研 / 横评 / 最新情况 / 多方验证
    ↓
search-fusion
    ↓
capability discovery
    ↓
task / freshness / domain / depth 分类
    ↓
query decomposition
    ↓
provider 或 query 并行
    ↓
URL canonicalization + dedupe
    ↓
Unweighted RRF
    ↓
provenance + freshness + relevance + diversity
    ↓
读取 Top sources
    ↓
带引用综合
```

## 2. 目录结构

```text
search-fusion/
├── SKILL.md
├── ARCHITECTURE.md   # 可选设计文档，不参与运行时加载
├── core/
│   ├── contract.mjs
│   ├── capabilities.mjs
│   ├── classify.mjs
│   ├── decompose.mjs
│   ├── normalize.mjs
│   ├── fuse.mjs
│   ├── rerank.mjs
│   ├── coverage.mjs
│   └── plan.mjs
├── adapters/
│   ├── README.md
│   ├── host.mjs
│   └── omp-internal.mjs
├── schemas/
│   ├── capabilities.schema.json
│   └── search-result.schema.json
├── scripts/
│   └── search-fusion.mjs
└── tests/
    ├── core.test.mjs
    ├── host-adapter.test.mjs
    └── fixtures/
        └── host-results.json
```

外部依赖不属于核心文件：

```text
~/.omp/agent/config.yml
~/.agents/rules/tool-search-routing.md
```

它们只影响 OMP adapter 或路由提示，不影响 Search Fusion core。

## 3. 核心边界

核心模块只认识统一搜索契约，不认识任何 harness 专有 API。

```ts
interface SearchAdapter {
  capabilities(): Promise<SearchCapabilities>;
  search(request: SearchRequest): Promise<SearchResponse>;
  fetch?(url: string): Promise<FetchResponse>;
}
```

统一 source：

```ts
interface SearchSource {
  url: string;
  title?: string;
  snippet?: string;
  publishedAt?: string;
  ageSeconds?: number;
  author?: string;
}
```

`runSearchQuery()`、`result.details.response`、OMP provider ID 等内容只能存在于 adapter，不进入 core。

## 4. Capability negotiation

Search Fusion 不按 harness 名称分支，而是读取能力声明：

```json
{
  "harness": "fixture-host",
  "level": "L3",
  "providerPin": true,
  "parallelSearch": true,
  "structuredSources": true,
  "fetch": false,
  "providers": ["exa", "gemini", "xai"],
  "autoOrder": ["exa", "gemini", "xai"],
  "roles": {
    "exa": ["semantic", "developer"],
    "gemini": ["general", "fresh"],
    "xai": ["fresh", "social"]
  },
  "rankSemantics": {
    "exa": "ranked",
    "gemini": "citation-order"
  }
}
```

能力等级：

首轮 provider 数由 `maxInitialProviders` 控制（默认 3）；证据覆盖不足时，fallback 波次最多再消耗 `maxFallbackCalls` 次调用（默认 2），全程使用的 unique provider 不超过 `maxProviders = maxInitialProviders + maxFallbackCalls`。

预算模型统一为 `SearchBudget`：`wallClockMs`、`perCallTimeoutMs`、`maxInitialProviders`、`maxProviders`、`maxSubqueries`、`maxSearchCalls`、`maxFallbackCalls`。每次调度统一扣减；默认 profile 为首轮 3 providers / 最多 4 subqueries / 9 search calls，wall clock 按 depth 分层。

能力声明包含 `retrievalFamilies`，用于区分 provider 品牌与底层检索族；例如 `gemini` 和 `startpage` 都归入 `google`，避免把高度相关的检索路径误当作多路独立证据。

默认全局搜索预算按任务深度分层：`quick=90s`、`verify=150s`、`deep=180s`；调用方仍可用 `--timeout-ms` 显式覆盖。超时返回 `status: "partial"` 与已完成的 attempts，不丢弃已成功结果。

| 等级 | Host 能力 | Fusion 行为 |
|---|---|---|
| L3 Full Fusion | provider pin + structured sources | 多 provider 并行 + RRF |
| L2 Multi-tool | 多个独立 search tool | 每个 tool 当 provider |
| L1 Generic Search | 只有一个搜索能力 | query diversification |
| L0 No Search | 无搜索能力 | 明确报错 |

## 5. Provider role，而不是 provider 品牌

核心策略使用 provider role：

```text
semantic
general
fresh
developer
academic
china
social
fallback
```

典型路由：

```text
coding + recent  → semantic + developer + fresh
china + recent   → china + general + fresh
academic         → academic + semantic + general
```

具体 provider 由 adapter 声明的 roles 决定。核心不再硬编码 `exa/gemini/xai`。

## 6. Intent 维度

意图不再只有一个枚举，而是拆成正交维度：

```json
{
  "task": "comparison",
  "freshness": "recent",
  "domain": "coding",
  "depth": "deep",
  "language": "mixed-or-zh"
}
```

维度：

- `task`: `lookup | factual | comparison | tutorial | exploratory`
- `freshness`: `evergreen | recent | live`
- `domain`: `general | coding | academic | news | china`
- `depth`: `quick | verify | deep`

这样同一个查询可以同时是：

```text
comparison + recent + coding + deep
```

## 7. Query decomposition

`decomposeQuery()` 生成结构化 facet，而不是再对每个 provider 做笛卡尔积：

```text
base          → 原查询，broad-recall
official      → documentation / source code，developer
recent        → latest update，fresh
comparison-*  → 拆对象能力，semantic
```

执行分三波，coverage 足够则提前停：

```text
Wave 1 breadth   原查询 × 选中的 providers（优先不同 retrievalFamily）
Wave 2 facets    每个额外 facet × 1 个匹配 requiredRoles 的 provider
Wave 3 fallback  预留最多 2 次 call
```

同一 URL 的 RRF 按 retrievalFamily 取最大贡献，不再把 Gemini 和 Startpage 当成两路独立检索。
`providerSupport` 仍是命中工具数，`familySupport` 才是相对独立检索族数。

默认限制：

```text
maxSubqueries = 3
maxSearchCalls = 9
```

## 8. Unweighted RRF 和 rank semantics

当前默认不使用 provider 品牌权重。原因是：

- provider 先验已经体现在 capability plan
- “provider 平均质量”不等于“某条 source 质量”
- 品牌权重会在 RRF 中重复施加偏见

RRF 对所有 provider 使用相同的 top-1 贡献 `BASE = 1/61`，再用不同 slope 衰减。这样 citation-order 更平坦，但不会把 Gemini/xAI 的第一条 citation 系统性降权到 ranked 的一半：

$$
RRF(d) = \sum_i BASE \cdot \frac{k_i + 1}{k_i + rank_i + 1}
$$

`rankSemantics` 只决定衰减斜率，不决定 provider 权重：

| 语义 | k | 用途 |
|---|---:|---|
| ranked | 60 | 传统 SERP 排序 |
| citation-order | 120 | grounding/答案引用顺序 |
| unknown | flat（恒为 BASE） | 未知排序语义 |

同一 provider 对同一 canonical URL 只保留最高 RRF 贡献，避免 `provider × subquery` 的重复命中被误当成多路独立共识。

这样 Gemini、xAI、Codex 这类 citation-order provider 不会被当成严格 SERP rank，也不会在 top-1 上被隐式降权。

## 9. URL 规范化与去重

`normalizeUrl()` 做以下处理：

1. 删除 fragment。
2. 统一 protocol/hostname 小写。
3. 删除 `www.`。
4. 删除默认端口 `80/443`。
5. 删除明确 tracking 参数：`utm_*`、`fbclid`、`gclid`、`mc_cid`、`mc_eid`、`igshid`、`dclid`。
6. 不删除 `ref`、`source`、`id`、`page`、`v`。
7. 排序 query 参数。
8. 去掉结尾多余 `/`。

排序时使用 canonical URL；引用时保留 `citationUrl`，因此 fragment 可以保留给最终引用定位。

## 10. Provenance / Source role

authority 不再只是域名信誉，而是来源角色：

```text
primary_standard
primary_paper
primary_official
code
official_docs
independent_benchmark
news_reporting
community
aggregator
unknown
```

示例：

- `ietf.org` / `w3.org` → `primary_standard`
- `arxiv.org` → `primary_paper`
- `github.com` / `gitlab.com` → `code`（代码托管，不自动等于厂商一手来源）
- 官方文档和厂商主站 → `primary_official` / `official_docs`
- `community.*`、`forums.*` 等用户托管子域优先判为 `community`，不因父域是厂商域名就升级
- `benchmark` / `evals` 字样只在 hostname/path 上提示「疑似评测」，URL query 参数不参与判定
- HN / Reddit / Zhihu → `community`
- 技术媒体 → `news_reporting`

域名只决定来源角色；是否为当前研究对象的一手来源由实体覆盖检查另行把关。

## 11. Freshness

- `ageSeconds`
- ISO 或常见日期
- 相对时间，如 `2 days ago`

未来日期（发布时间晚于 `asOf`）不奖励，固定给 0.3 并影响 evidence 覆盖。同一 URL 的多个日期观测取较新者，输入换序不改变结果。回放可用 `--as-of` 冻结评估时间；snippet 中提到的年份不再作为新鲜度依据。

无日期时按任务类型处理：

```text
recent/live  → 0.2，且不满足 evidence 时效要求
evergreen    → 0.5
```

## 12. Relevance gate

关键词覆盖率仍保留，但只承担低权重相关性信号和离题惩罚，不作为主排序决定因素。原因是 Exa/Gemini 等 provider 已经完成语义召回，字面 overlap 对中文、同义词和缩写不稳。

## 13. 最终排序

分数权重按意图分层（`scoreProfileFor`，权重总和恒为 1）：

| profile | 触发 | rrf | provenance | freshness | relevance |
|---|---|---|---|---|---|
| default | 其他 | 0.62 | 0.18 | 0.14 | 0.06 |
| live | freshness=live | 0.46 | 0.14 | 0.34 | 0.06 |
| recent | freshness=recent | 0.52 | 0.16 | 0.26 | 0.06 |
| academic | academic 域 | 0.52 | 0.30 | 0.10 | 0.08 |
| primary | factual / tutorial | 0.56 | 0.24 | 0.12 | 0.08 |

```js
score =
  w.rrf        * normalizedRrf
+ w.provenance * provenance
+ w.freshness  * freshness
+ w.relevance  * relevance
```

`providerSupport` 和 `providerSupportRatio` 保留为 metadata，不进入最终分数，避免重复奖励“多个 provider 命中同一 URL”。输出随附 `scoring: { name, weights }`。

## 14. Coverage 拆分：retrieval 与 evidence

覆盖检查拆成两层，只有都达标才允许提前结束：

```text
retrieval   候选池规模：相关 URL 数、域名数、检索族数、primary source 数
evidence    研究维度：comparison 各实体、recent/live 的时间窗内带日期证据
```

retrieval 阈值随 depth 分层：quick 放宽（URL -2、域名 -1），deep 收紧（URL +2、域名 +1、factual/tutorial 的 primary source +1）。

实体抽取支持 2–4 个比较对象（`A vs B vs C`、`A、B 和 C`），实体匹配对连字符、空格、点不敏感（`GPT-5` 命中 `GPT5`）。comparison 叠加 recent/live 时，实体 facet 附带 windowDays：每个实体都必须有窗口内带日期的来源才算 covered。

- `factual` / `tutorial`：retrieval 仍要求至少 1 个 primary source
- `comparison`：evidence 要求两个实体的标题/摘要命中；缺一侧就继续检索或报告缺口
- `recent` / `live`：必须存在可解析日期且落在时间窗（recent 90d / live 7d）内的来源；未知日期与未来日期不计入
- 离题来源（relevance = 0）只展示不计数

提前结束的条件是 `retrieval.sufficient && evidence.sufficient`；预算耗尽而未达标时返回 `status/stopReason` 与 `gaps`，不用无关页面凑数。Top-K 多样性裁剪后另附 `coverage.delivery` 复核最终交付。

## 15. Diversity rerank

- 默认每个 domain 最多 2 条
- 优先覆盖不同 source role
- 再按原分数填充剩余槽位

目标输出更接近：

```text
官方文档
+ GitHub / 源码
+ 独立 benchmark
+ 论文
+ 新闻或社区讨论
```

而不是 Top 8 全部集中在同一域名。

## 16. 执行模式

### Host-orchestrated

最通用，支持完整「计划—执行—反馈」闭环：

```text
Harness Agent
  → search-fusion --plan "问题"              # 输出带 ID 的 requests 与预算
  → 用当前环境搜索工具执行 requests
  → 写入 normalized results JSON
  → search-fusion --input results.json "问题"     # 融合 + coverage
  → search-fusion --input results.json --next "问题"  # 缺口对应的待执行 requests
  → 循环直到 coverage.sufficient 或预算耗尽
```

输出包含 `status`（complete/partial）、`stopReason`（coverage-satisfied / budget-exhausted / deadline）与 `gaps`。正文抓取与阅读由 host 负责，脚本只负责编排、融合与覆盖判断。

适合 Claude Code、Codex、OpenCode、Pi、OMP 等只要能调用工具并执行脚本的环境。

### Adapter-orchestrated

确定性自动化：

```bash
bun scripts/search-fusion.mjs --adapter omp "深入调研问题"
```

当前包含 `adapters/omp-internal.mjs`，它是兼容性 adapter，不是核心依赖。

## 17. 观测与全局 deadline

provider 遥测闭环回排序：`core/reliability.mjs` 把每次 adapter 运行的 attempts 记入 `~/.search-fusion/provider-stats.json`（成功率、429/超时/鉴权分类、EWMA 延迟、连续失败）。后续运行的 `autoOrder` 与 fallback 波次按 reliability 重排（分数差异小于容差时保持静态顺序，避免抖动）；本次运行内 429/鉴权失败的 provider 不再重试，facet/fallback 改派健康 provider。缓存命中（`fromCache`）的 attempt 不进入统计。

搜索响应缓存：`core/cache.mjs` 按 `sha256(provider + 规范化 query)` 存到 `~/.search-fusion/cache/`，TTL 为 evergreen 7 天 / recent 1 小时 / live 不缓存；`--no-cache` 关闭。命中不计入 `runManifest.cost.underlyingSearchCalls`（单列 `cachedCalls`），benchmark `search-api` profile 强制禁用缓存。

Host-orchestrated 多轮闭环可用 `--session <file>` 累计历史 attempts（按 `provider::query` 去重），host 每轮只需写本轮新结果。

## 17.1 观测字段

输出保留：

```text
providerLatencyMs
providerErrorType
requestedProvider / actualProvider
facetId / wave
uniqueCanonicalUrls / offTopicSources
familySupport / familySupportRatio
authMode
elapsedMs
```

adapter-orchestrated 从启动起计算单一 `deadlineAt`，覆盖 capabilities 发现与所有波次；每次调度前检查剩余时间，单次调用另受 `perCallTimeoutMs` 约束。超时不丢弃已完成结果：输出 `status: "partial"`、已完成 attempts 与缺口。

## 18. 验证

运行：

```bash
node tests/core.test.mjs
node tests/host-adapter.test.mjs
node tests/search_fusion.test.mjs
node tests/replay.test.mjs
node tests/property.test.mjs
node tests/review-repro.test.mjs
node tests/leaderboard.test.mjs
node tests/direct-adapter.test.mjs
node tests/optimization.test.mjs
```

在线三臂测评（single / multi-query / fusion，快照可用 `--input` 回放）：

```bash
bun benchmarks/run.mjs            # benchmarks/queries.json 全部
bun benchmarks/run.mjs <id,id>    # 只跑指定查询
```

Host 输入模式示例：

```bash
bun scripts/search-fusion.mjs \
  --input tests/fixtures/host-results.json \
  --top 8 \
  --pretty \
  "current OpenAI API documentation"
```

## 19. 设计来源

检索分层、意图分类、URL 去重和 freshness 思路参考 `blessonism/search-skills`。本实现把核心重构为 harness-agnostic 的搜索编排与证据融合层；harness 专有调用全部隔离在 adapters 中。
