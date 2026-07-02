# Kid Career Portrait Batch

批量生成儿童未来职业照。扫描以「姓名 职业」或「姓名 性别 职业」命名的儿童照片，调用 OpenAI-compatible 的 `gpt-image-2` 图像编辑接口，把每张照片生成 3:4、约 2K 高度的未来真人职业照，并输出图片、PPTX、manifest、报告。需要时可继续调用 `lark-cli` 把 PPTX 导入飞书幻灯片、创建飞书多维表格并设置公开可读。

## 输入要求

推荐文件名：

```text
小孙 男 宇航员.jpg
小周 女 厨师.png
张三 人工智能工程师.jpg
```

性别可选；缺失时多维表格的「性别」字段为空。默认用空格分隔，也兼容 `_` 和 `-`。

## 快速开始

```bash
pip install -r requirements.txt
```

Windows PowerShell 设置 key：

```powershell
$env:IMAGE_API_KEY="sk-你的主接口key"
$env:FALLBACK_IMAGE_API_KEY="sk-你的回退接口key"
```


如需配置主接口和回退接口的 key，推荐用环境变量，不要把真实 key 写进要迁移/分享的文件：

```powershell
$env:IMAGE_API_KEY="sk-packyapi-key"
$env:FALLBACK_IMAGE_API_KEY="sk-change2pro-key"
```

主接口默认是 `https://api-slb.packyapi.com`，回退接口默认是 `https://api.change2pro.com`，模型均为 `gpt-image-2`。

只检查解析和 prompt，不调用 API：

```bash
python scripts/run.py --input ./kidtest --output ./output --dry-run
```

生成图片和本地 PPTX：

```bash
python scripts/run.py --input ./kidtest --output ./output
```

生成后发布到飞书，并把飞书 PPT 与多维表格设置为公开分享-可阅读：

```bash
python scripts/run.py --input ./kidtest --output ./output --publish-lark --public-share
```

如要写入指定飞书云空间文件夹：

```bash
python scripts/run.py --input ./kidtest --output ./output --publish-lark --public-share --lark-folder-token <folder_token>
```

`--public-share` 会调用 `lark-cli drive permission.public patch --yes`，只应在用户当前明确要求公开分享时使用。

## 关键默认值

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--model` | `gpt-image-2` | 图像编辑模型 |
| `--size` | `1536x2048` | 3:4，约 2K 高度 |
| `--quality` | `high` | 高质量输出 |
| `--concurrency` | `2` | 两张并发 |
| `--prompt-template` | `templates/career_portrait_prompt.txt` | 固定 prompt 模板 |
| `--ppt-name` | `kid-career-portraits.pptx` | 本地 PPTX 文件名 |
| `--publish-lark` | false | 导入飞书 PPT、创建飞书 Base |
| `--public-share` | false | 将飞书 PPT/Base 设置为公开可读 |

## Prompt 模板

当前模板使用字面占位符 `{{职业}}`。构建 prompt 时只替换 `{{职业}}`，其他文本保持不变。用户提供新的 prompt 后，直接覆盖 `templates/career_portrait_prompt.txt` 即可。

兼容旧模板：如果模板不含 `{{职业}}`，仍支持旧的 `{age}`、`{career}`、`{clothing}`、`{scene}` 格式和 `data/career_map.json` 职业映射。

## 输出结构

```text
output/
├── images/                         # 未来职业照
├── logs/
│   ├── run.log
│   ├── failed.json
│   └── api_errors.jsonl
├── kid-career-portraits.pptx       # 每页一名孩子，右侧未来照按空格显示
├── manifest.csv                    # 含真名、性别、职业、prompt、图片路径、状态
├── manifest.json
├── lark_publish_result.json        # 仅 --publish-lark 时生成
└── report.md
```

## PPT 规则

每页一组照片。左上角小字显示「姓名｜理想职业：职业」；左侧是当前真人照；右侧是未来职业照。PPTX 写入了“按下一步/空格后显示右侧图片”的动画。

注意：本地 PPTX 动画按 PowerPoint Open XML 写入。飞书导入 PPTX 后是否完整保留动画，取决于飞书当前导入器；发布后应抽查一页放映效果。

## 飞书输出

`--publish-lark` 会执行两类操作：

1. `lark-cli drive +import --type slides` 导入本地 PPTX 为飞书幻灯片。
2. `lark-cli base +base-create` 创建多维表格，字段包括真名、性别、期望职业、小孩真人照、小孩未来职业照、prompt、生成状态；然后逐条上传两张照片到附件字段。

`--public-share` 会把 slides 和 bitable 设置为 `anyone_readable` 且允许外部访问。该操作是高风险权限变更，必须有明确公开分享需求。

## 安全注意

处理儿童照片前确认已获得照片使用许可。输出只生成成年人职业照，不生成性化内容，不在图片上添加姓名、水印、学校名或其他文字。日志不输出完整 API Key，不覆盖源图片。
