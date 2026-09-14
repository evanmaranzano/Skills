# Mini Eval — search-fusion 最小评测（FRAMES 官方子集）

目的：在接入正式评测框架（Inspect AI + SimpleQA/BrowseComp/FRAMES 全量）之前，用权威数据集的小样本验证评测链路端到端可行——题集加载 → 检索执行 → 融合 → 答案综合 → 判分 → 报告。**不自出题**，题目全部来自官方数据集。

## 题源：google/frames-benchmark（Google 官方）

- FRAMES test 集 824 题，multi-hop 事实检索，每题自带官方 `Answer`、`reasoning_types`（factuality / retrieval / reasoning 维度标注）和 `wiki_links`（官方参考来源）。
- 匿名可拉（非 gated）；SimpleQA 为 gated 数据集，留给 Inspect AI 官方实现阶段。
- 抽样：固定步长 `offsets = [0,82,164,246,328,410,492,574,656,738]`（824/10），落盘 `queries-frames-mini.json`，可复现。扩题 = 改 stride 重抽，规则透明。

## 预算红线（防烧额度）

| 后端 | 成本 | 用途 |
|---|---|---|
| ZCode 内置 WebSearch（host-orchestrated） | 平台提供，不烧 API key 额度 | mini eval 默认后端 |
| OMP adapter（bun）/ Tavily·Exa REST 直连 | 烧对应 key 额度 | 仅正式 benchmark 用，跑前先查额度 |

硬顶：**每题 ≤ 4 次底层 search call**（比 benchmark profile 的 5 次更紧）、**每题 ≤ 2 次页面抓取**。预算内未覆盖就记 `not-answered`，不追加。

## 流程（host-orchestrated）

1. 取 `queries-frames-mini.json` 一题的 `prompt`；
2. `node scripts/search-fusion.mjs --plan "<prompt>"` 取 facets（provider:null 由 host 回填）；
3. host 用自己的搜索工具执行各 facet，按 `tests/fixtures/host-results.json` 格式写 input（如实声明单一 provider，`providerPin:false`）；
4. `node scripts/search-fusion.mjs --input results.json "<prompt>" --top 5` 融合；
5. host 按 SKILL.md「最终综合」给出带引用答案：先看 `status`/`coverage.gaps`，必要时抓取至多 2 个 Top 来源读正文；
6. 判分：对照官方 `Answer` 做字符串严格匹配优先、语义等价需引用检索到的来源 URL 佐证，不得用 host 参数知识直接判；
7. 结果写入 `results/results-<date>.json`。

## 判分与指标

- `answer-exact` / `answer-wrong` / `not-answered`（gaps 非空或证据不足）；
- accuracy = answer-exact / 总题数；附每题 `underlyingSearchCalls`（融合输出 `runManifest.cost`）与 gaps。

## 扩展与升级

- 本轮仅实测前 3 题（链路验证），其余 7 题随时可跑；
- 正式评测：Inspect AI（UK AISI）有 SimpleQA/BrowseComp 官方实现，FRAMES 用本文件同款官方数据集写自定义 task；runner 由 Python 驱动时搜索后端换成 API 直连或 OMP adapter；
- 更进一步：xbench-DeepSearch（红杉官方，最新题库 100 题开源但加密，需其 xbench-evals 框架解密运行），作为榜单级进阶。
