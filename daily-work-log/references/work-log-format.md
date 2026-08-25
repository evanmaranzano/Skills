# 工作日志格式参考（daily-work-log 的写作蓝本）

> 唯一正式目标文档：《工作日志》
> `https://my.feishu.cn/docx/B7vjd31ukoYMBmx1Dk9c7A8Jnzd`

## 文档结构

```
# 工作总览                     ← 月度维护，本 Skill 日常不碰
## 关键里程碑
## 产出统计
# YYYY 年 M 月                ← 月份 h1（h1 下一段是月度小结加粗引导段，日常不碰）
## M 月 D 日                  ← 每日 h2
- 条目 1
- **高光主线条目。**正文扩写…
## M 月 D 日
- …
```

## 单条条目的骨架（扩写原则）

一条 = 一个可独立交付的工作单元。扩全「**动机 → 做法 → 产出 → 效果**」：

- 动机：用户为什么提这个需求 / 背景。
- 做法：具体操作步骤、排查手段、工具链。
- 产出：交付的东西（容器、文档、脚本、修复、表格）。
- 效果：实测结果、性能数字、经验教训（用会话里真实出现的数字，不编造）。

## 既有条目示例（摘自习近几日的原文，照这个风格扩写）

**8 月 24 日**（高光加粗 + 长尾细节的典型）：
> - **Molispark Design 每日额度分发上线：默认每人每天 10 条视频。**users 表新增
>   daily_limit（-1 不限 / 0 禁止 / 缺省用全局默认），quota_usage 按人按天独立记账；提交时
>   原子扣减防并发超领，超限返回 429；任务失败（引擎故障/OOM/超时）与排队中删除一律退回
>   当天额度；…E2E 实测扣减、超限 429、排队删除退回、两人排队公平排序全部通过。
> - 更新 DNS 解析：新增 www.molispark.cn 记录。（低频小项，一句带过）

**8 月 25 日**（含 <cite> 挂链的典型）：
> - **dubhe 客户三套新容器搭建并交付。**…三套环境交付信息整理为飞书文档
>   <cite doc-id="Ny89dyeM2orA3kxH8UGc8708nMg" file-type="docx" title="dubhe 容器环境与访问信息（jszx15）" type="doc"></cite>。
> - **修复 qwen38-vllm 前缀缓存「不命中」根因。**…本地 memory、桌面文档、飞书 Base 均已回写。
>   （这条是更新既有权威源，不挂 cite）

## <cite> 挂链写法（重要）

落成飞书文档的条目才挂。从 `drive +search` 的 `url` / `entity_type` 取 token 和类型：

```xml
<!-- docx / wiki 底层 docx -->
<cite doc-id="<token>" file-type="docx" title="<文档标题>" type="doc"></cite>
<!-- 电子表格 / Base / 多维表格 -->
<cite doc-id="<token>" file-type="sheets" title="<标题>" type="doc"></cite>
<cite doc-id="<token>" file-type="bitable" title="<标题>" type="doc"></cite>
```

- `doc-id` = 文档 URL 路径里的 token（`drive +search` 返回的 `token`）。
- `file-type`：docx / sheets / bitable / slides / wiki…（与 `--doc-types` 对应）。
- 拿不到 token 时写占位 `【挂链：<文档名>，token 待补】`，最后提示用户。
- **只有落成飞书文档的挂**。纯更新桌面 md / 本地产物 / 例行改既有权威源不挂（参照
  8-24 qwen38 条目只写「回写服务器信息」）。

## 多工具去重示例

同一「dubhe 三容器公网 SSH 排查」会在 opencode/claudecode/kimicode 各出现一次 →
归并为**一条**「dubhe 三容器公网 SSH 排查并在防火墙侧打通」，子步骤并进正文，不按工具分条。
