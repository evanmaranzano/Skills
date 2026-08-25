# lark-cli 写飞书文档避坑（daily-work-log 阶段 3 必读）

> 今天实际踩过的坑，全部影响「写工作日志」这一步的成败。

## 1. 不要在 PowerShell 内联带引号 / 尖括号的 XML

`--content '<p>…<cite doc-id="…" …>…'` 里的 `\"` 在双引号 shell 里会被拆裂成多个位置参数
（报 `positional arguments are not supported`），`<` 会触发 PowerShell `ParserError: '<' operator
is reserved for future use`。

**正确做法**：把 XML/JSON 写到 cwd（当前工作目录）下的临时文件，再 `--content @file.xml` 传入：
```powershell
# 用 Write 工具写 C:\Users\26566\<something>.xml（UTF-8）
lark-cli docs +update --doc <DOC> --as user --command append --content "@something.xml"
Remove-Item "C:\Users\26566\something.xml"
```
绝对路径会被拒（`--file must be relative path within the current directory`），必须用 cwd 相对 `@名字.xml`。

## 2. --json 不支持 stdin `-`，要 `@相对路径.json`

`base +record-upsert --json -` 报 `invalid JSON object near byte 1`。用 `--json @rel.json`
（cwd 相对路径）。复杂 / 含引号的 payload 一律走文件。

## 3. block 生命周期（改完不要盲目复用旧 id）

- `append` / `block_insert_after`：新内容是新 block id；想再改需重新 fetch。
- `block_replace` / `block_delete` / `overwrite`：受影响旧 id 失效。
- `str_replace`：简单行内替换 id 通常不变；但跨行/大段改后继续 block 操作要重新 fetch。

## 4. str_replace 叠加会产出重复段（重灾区）

连续两次 `str_replace` 替换同一段，第二次会基于第一次的结果再替换，导致**重复**
（如今天 dubhe 条目出现 `整理为飞书文档<cite>…</cite>整理为飞书文档<cite>…</cite>`）。
**能用一次 `block_replace` 整块重写，就不要拆两次 `str_replace`**。改错整条就取该 li 的
block id 用 `block_replace` 替换整条，最稳。

## 5. 取 block id

`docs +fetch --doc <DOC> --scope section --start-block-id <h2 id> --detail with-ids`
（**必须 XML 格式**；`--detail with-ids` 配 `--doc-format markdown` 会被忽略并返回 markdown）。
顶层 `<li id="…">` / `<h2 id="…">` 都要从这里拿。

## 6. JSON 信封判断

成功看 `ok == true`（进程退 0），**不要看 `code == 0`**（成功无顶层 code，`code` 只在错误信封的
`error` 里）。傻判 `code==0` 会把成功当成失败。

## 7. 连读大文档用局部 scope

工作日志 doc 很大（几百 revision、长正文）。fetch 用 `--scope outline` / `--scope section --start-block-id <h2>` /
`--scope keyword` 局部拉，别整篇 `--scope` 全量。`--scope` 可选值只有
`full/outline/range/keyword/section`，**没有 `simple`**。

## 8. 串行写同一文档

多个对同一 doc 的写（尤其 `append` / `block_*`）串行执行，避免 revision 冲突 / 并发覆盖。
