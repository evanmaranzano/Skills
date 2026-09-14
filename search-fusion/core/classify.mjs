const TASK_SIGNALS = [
  ["comparison", /\b(vs|versus|compare|comparison)\b|横评|对比|比较|区别|竞品|哪个好/],
  ["tutorial", /\b(how to|tutorial|guide|setup|configure)\b|怎么|教程|指南|配置|搭建/],
  ["factual", /\b(what is|definition|official|documentation|github)\b|是什么|定义|官网|文档|源码/],
  ["exploratory", /./],
];

const FRESHNESS_SIGNALS = [
  ["live", /\b(today|breaking|this week|right now|live)\b|今天|本周|刚刚|突发/],
  ["recent", /\b(latest|recent|current|news|status|update|release)\b|最新|最近|当前|进展|现状|新闻|发布/],
  ["evergreen", /./],
];

const DOMAIN_SIGNALS = [
  ["coding", /\b(api|apis|sdk|github|typescript|python|rust|go|javascript|react|vite|server|database|coding|programming|exa|tavily|firecrawl|openai)\b|代码|编程|开发|报错|接口|文档|仓库|部署/],
  ["academic", /\b(arxiv|paper|research|benchmark|study|algorithm|model)\b|论文|研究|算法|模型/],
  ["china", /中国|国内|大陆|国产|智谱|通义|文心|豆包|月之暗面|哔哩哔哩|小红书|知乎|微博|微信|阿里|腾讯|百度|华为|字节|飞书|\bkimi\b|\bzhipu\b|\bqwen\b|\bdoubao\b|\bdeepseek\b|\bmoonshot\b|\bbilibili\b|\blark\b/i],
  ["news", /\b(news|announcement|press|policy|market)\b|新闻|公告|政策|市场/],
  ["general", /./],
];

export function classifyTask(query) {
  const text = query.toLowerCase();
  for (const [task, pattern] of TASK_SIGNALS) if (pattern.test(text)) return task;
  return "exploratory";
}

export function classifyFreshness(query) {
  const text = query.toLowerCase();
  for (const [freshness, pattern] of FRESHNESS_SIGNALS) if (pattern.test(text)) return freshness;
  return "evergreen";
}

export function classifyDomain(query) {
  const text = query.toLowerCase();
  for (const [domain, pattern] of DOMAIN_SIGNALS) if (pattern.test(text)) return domain;
  return "general";
}

export function classifyDepth(query, options = {}) {
  if (options.depth) return options.depth;
  const text = query.toLowerCase();
  if (/深入|深度|多方验证|交叉验证|横评|benchmark|research|deep|compare|调研/.test(text)) return "deep";
  if (/验证|核验|确认|最新|当前|比较/.test(text)) return "verify";
  if (options.task === "comparison") return "verify";
  return "quick";
}

export function classifyDomains(query) {
  const text = query.toLowerCase();
  const matches = [];
  for (const [domain, pattern] of DOMAIN_SIGNALS) {
    if (domain === "general") continue;
    if (pattern.test(text)) matches.push(domain);
  }
  return matches;
}

export function classifyQuery(query, options = {}) {
  const task = options.task ?? classifyTask(query);
  return {
    task,
    freshness: options.freshness ?? classifyFreshness(query),
    domain: options.domain ?? classifyDomain(query),
    domainTags: classifyDomains(query),
    depth: options.depth ?? classifyDepth(query, { ...options, task }),
    language: /[\u4e00-\u9fff]/.test(query) ? "mixed-or-zh" : "general",
  };
}
