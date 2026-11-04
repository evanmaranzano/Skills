# Qwen-Image-2.1 绘本服务端 API 参考

自部署 Qwen-Image-2.1 + 串行网关（服务端源码在本机对应项目 `scripts/server_app_v2.py`，部署于内网 GPU 机器的 docker 容器）。**服务地址不写死在任何文件**——调用时通过 `--base` 或环境变量 `QWEN_IMAGE_BASE` 传入；本机实例地址见本地记忆或项目纪要。

## POST /v1/images（文生图）

```json
{
  "prompt": "...",
  "width": 1024,
  "height": 1360,
  "num_inference_steps": 20,
  "seed": 42,
  "fast": false
}
```

- 响应：`200` 直接返回 PNG 二进制（`image/png`），不是 JSON 包 base64。
- `fast: true` 走加速 LoRA 档（服务端 `models/lora/lora.conf` 决定具体档位：LoRA 文件/steps/cfg/sigmas/scheduler），不传或 false 走原 quality 路径。
- 有用响应头：`X-Mode`（quality/fast）、`X-Elapsed-Sec`（引擎耗时）、`X-Queue-Wait`（排队等待秒数）。

## POST /v1/edits（图生图 / 多参考编辑）

multipart/form-data：

| 字段 | 类型 | 说明 |
|---|---|---|
| `image` | file | 主参考图（绘本流程里永远是定妆照） |
| `image2`, `image3` | file | 可选额外参考图（构图参考等）；多图时服务端以 `image=[...]` 列表进管线 |
| `prompt` | text | 编辑指令 |
| `num_inference_steps` | text | 如 `"20"` |
| `seed` | text | 如 `"42"` |
| `fast` | text | `"true"` 加速档 |

- 响应同上：PNG 二进制 + 相同响应头。
- 注意 form 字段全是字符串；文件字段名必须用 `image`/`image2`/`image3`。

## GET /queue

```json
{"busy": true, "waiting": 2, "total": 3, "last_elapsed": 5.1, "mode": "fast"}
```

## 行为要点

- **全局串行**：底层推理引擎非线程安全，服务端用全局锁把并发请求排队执行（v1 时代并发直接 500）。客户端 timeout 给足（≥300s，视排队人数）。
- **纯加法兼容**：`fast`/`image2`/`image3` 都是可选参数，不带这些参数的旧调用行为不变。
- **换加速档**：改服务端 `models/lora/lora.conf` + `docker restart`，不动代码。
- 官方 Qwen-Image 编辑模式支持 ≤10 张参考图；本服务端开放到 3 张。
- 画像尺寸：绘本竖版用 1024×1360（服务端支持任意宽高，超分辨率档位另查服务端配置）。

## 排查

- 502 且服务端日志无请求 → 客户端被本机系统代理劫持，清 `HTTP_PROXY`/`HTTPS_PROXY`、设 `NO_PROXY=*`。
- 4xx → 参数错误（form 字段类型、文件字段名），看响应体不重试。
- 5xx/超时 → 服务端排队拥挤或重启中，重试 2–3 次，仍失败查 `/queue` 与容器日志。
