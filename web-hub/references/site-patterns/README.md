# Site Patterns

此目录存放各站点的操作经验。文件名格式：`{domain}.md`

## 内容规范

每个站点经验文件记录：
- 已验证的反爬机制（如 Cloudflare、JS 渲染要求）
- 登录判断逻辑
- 特殊 DOM 结构（Shadow DOM、iframe）
- 可靠的选择器和提取方式
- 已知限制和注意事项

**只记录已验证的事实，不记录猜测。**

## 示例

```
# example.com
- 需要 JS 渲染，WebFetch 无法获取内容
- 登录态通过 Cookie 传递
- 内容在 #main-content 容器中
- 反爬：无明显措施
```
