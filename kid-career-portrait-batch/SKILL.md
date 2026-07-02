---
name: kid-career-portrait-batch
description: "批量生成儿童未来职业照。扫描以'姓名 职业'或'姓名 性别 职业'命名的儿童照片文件夹，调用 gpt-image-2 图像编辑接口，按 2 并发生成 3:4、约 2K 高度的未来真人职业照；输出图片、PPTX、manifest、报告，并可按用户明确要求发布为飞书幻灯片和飞书多维表格、公开分享可阅读。当用户提供儿童照片文件夹、想要批量生成职业梦想照、毕业纪念册职业照、'如果长大后当XX会怎样'类型图片、儿童职业体验照时触发。"
---

# Kid Career Portrait Batch

本 skill 用于批量处理儿童照片，生成“这个孩子长大后的真人职业照”，并把当下真人照与未来职业照整理成 PPTX；如用户明确要求，也可发布到飞书幻灯片和飞书多维表格。

## 必须遵守

先确认用户对输入儿童照片有使用许可。只生成明显成年人形象，不生成性化内容，不在图片上写姓名、学校、Logo、水印或任何文字。不得输出或记录完整 API Key。不得覆盖源图片。

公开分享飞书文档属于权限变更。只有用户在当前轮明确要求“公开分享/可阅读”时，才允许传 `--public-share`，它会进一步调用 `lark-cli ... permission.public patch --yes`。

## 输入约定

文件名支持两种格式：

```text
姓名 职业.jpg
姓名 性别 职业.jpg
```

例子：

```text
小孙 男 宇航员.jpg
小周 女 厨师.png
张三 人工智能工程师.jpg
```

性别可选，支持 `男/女/男孩/女孩/boy/girl/male/female/m/f`，会归一为 `男` 或 `女`。默认空格分隔，也兼容 `_` 和 `-`。

## 默认生成规则

图像接口使用 `POST /v1/images/edits`，不是文生图接口。默认模型 `gpt-image-2`，默认尺寸 `1536x2048`，即 3:4 竖图、约 2K 高度；默认质量 `high`；默认并发 `2`。

API Key 优先从命令行参数读取，其次读环境变量 `IMAGE_API_KEY` / `FALLBACK_IMAGE_API_KEY`，再读本地 `config.yaml`。迁移到新设备时，不要复制含真实 key 的配置到共享位置；推荐在新设备设置环境变量。

Prompt 模板在 `templates/career_portrait_prompt.txt`。当前优先使用字面占位符 `{{职业}}`：构建 prompt 时只替换这个占位符，模板其他内容保持不变。用户随后提供新的 prompt 时，直接覆盖该模板即可。为了兼容旧版本，如果模板里没有 `{{职业}}`，代码仍支持 `{age}`、`{career}`、`{clothing}`、`{scene}` 和 `data/career_map.json`。

## 文件结构

```text
kid-career-portrait-batch/
├── SKILL.md
├── README.md
├── config.example.yaml
├── config.yaml                  # 本地配置，可能含 key；不要主动读取或提交
├── requirements.txt
├── data/career_map.json          # 旧模板兼容
├── templates/
│   ├── career_portrait_prompt.txt
│   └── negative_prompt.txt
└── scripts/
    ├── run.py                    # 主入口：生成图片、PPTX、可选发布飞书
    ├── api_client.py             # OpenAI-compatible image edit 客户端
    ├── parser.py                 # 文件名解析、性别解析、图片扫描
    ├── prompt_builder.py         # prompt 构建，支持 {{职业}}
    ├── ppt_builder.py            # 生成带右图点击出现动画的 PPTX
    ├── lark_publish.py           # 调 lark-cli 发布飞书 PPT/Base
    ├── image_utils.py
    └── report.py
```

## 安装依赖

```bash
pip install -r requirements.txt
```

## 运行方式

只检查解析和 prompt，不调用 API：

```bash
python scripts/run.py --input <照片文件夹> --output <输出文件夹> --dry-run
```

生成未来职业照和本地 PPTX：

```bash
python scripts/run.py --input <照片文件夹> --output <输出文件夹>
```

生成并发布到飞书，且公开分享可阅读：

```bash
python scripts/run.py --input <照片文件夹> --output <输出文件夹> --publish-lark --public-share
```

发布到指定飞书云空间文件夹：

```bash
python scripts/run.py --input <照片文件夹> --output <输出文件夹> --publish-lark --public-share --lark-folder-token <folder_token>
```

## 输出

```text
output/
├── images/                         # 未来职业照
├── logs/run.log
├── logs/failed.json
├── logs/api_errors.jsonl
├── kid-career-portraits.pptx       # 每页一组照片，右侧未来照按空格显示
├── manifest.csv
├── manifest.json
├── report.md
└── lark_publish_result.json        # 仅发布飞书时生成
```

`manifest.csv/json` 字段包括：真名 `name`、性别 `gender`、期望职业 `career`、小孩真人照路径 `input_file`、小孩未来职业照路径 `output_file`、完整 `prompt`、状态和错误信息。

## PPT 规则

每页 PPT 一组照片。左上角小字显示孩子名称和理想职业。左边放小孩当下真人照。右边放未来真人职业照，并写入“放映时按空格/下一步后显示”的动画。飞书导入 PPTX 后是否完整保留动画取决于飞书当前导入器，发布后必须抽查至少一页。

## 飞书输出

`--publish-lark` 会调用 `lark-cli drive +import --type slides`，把本地 PPTX 导入为飞书幻灯片；随后调用 `lark-cli base +base-create` 创建多维表格，字段为真名、性别、期望职业、小孩真人照、小孩未来职业照、prompt、生成状态，并逐条上传图片附件。

`--public-share` 会把飞书幻灯片和飞书多维表格设置为公开分享-可阅读。该参数只应在用户明确要求公开时使用。

## 常见风险

如果本地 `config.yaml` 写了旧的 `output.size`，会覆盖代码默认的 `1536x2048`；不要直接查看或编辑该文件里的 API Key，必要时让用户确认后修改。某些第三方 `gpt-image-2` 网关可能不支持 `1536x2048`，这时才改用它支持的最接近 3:4 尺寸。PPTX 动画可在 PowerPoint 中验证；飞书导入后的动画需要人工抽查。
