# jszx workspace — 特权工作区容器 + 公网端口开放

jszx 内网两类任务：A=新开会用工作区容器（10-20 固化），B=已有服务开公网端口（10-21 固化，分钟级）。

前置：SSL VPN 已拨通（10.10.127.x 可达）；服务器/防火墙凭据查
`DeskBox\文档\服务器与运维\服务器信息整理<最新日期>.md`（规则 `reference_jszx_server_inventory`）。

**凭据解析约定（2026-10-21 起，jszx 系脚本统一）**：按序取 `环境变量 → ~/.config/jszx/creds.env(600) → DeskBox 权威文档 grep`。高频凭据（防火墙 admin、15 root SSH）集中在 creds.env，轮换后 DeskBox 文档仍是权威源、本文件需同步；**禁止**把凭据塞进 ~/.bashrc 全局（子进程继承会泄漏）或写进 skill/记忆/报告。creds.env 变量命名：`FW_*`（防火墙）、`JSZX<N>_ROOT_PASS`（N 号机 root SSH）。

依赖（本机 WSL）：`pip install requests pycryptodome pillow` + 系统 `tesseract`。

## 选址决策（先想清楚再动手）

| 候选 | 何时选 | 红线 |
|---|---|---|
| **15（默认）** | 演示/对外服务，aarch64 可接受 | app 服务器，别挤占既有端口；**主 docker daemon**，dubhe 系在 docker-dubhe daemon（`docker -H unix:///var/run/docker-dubhe.sock`），别混 |
| 16（x86_64） | 交付物只有 x86 镜像/二进制 | 根盘常年 98%，新数据必须落 /opt/data；GPU 生产机 |
| 17 | 仅当 15/16 都不可用 | GLM-5.3-Flash 生产推理机，保持单一职责 |

架构检查：15/17 是 aarch64——交付镜像须 arm64/multi-arch，先跟交付方确认。

---

## 场景 B：已有服务开公网端口（**首选脚本化路线**）

10-21 实测全程 ~10 分钟，无浏览器。三步：

### 1. 冲突检查（双重，缺一不可）

- 宿主：`ss -tln | grep ':<PORT> '`——被别的服务（如 dubhe-token 33000）占了就不能用同端口
- 防火墙：`fw_dnat.py list`——查公网端口是否已有 DNAT 规则（文档可能漏记，以防火墙实况为准）
- 冲突就换相邻端口（如 33000→33001）并向用户说明缘由；**不要动占用方的在跑业务**

### 2. 服务器侧（只在需要时）

服务已发布到宿主（`docker ps` 有 `-p`）→ 跳过。否则（如服务在 demo/workspace 容器的内层 docker、或绑了 127.0.0.1）：

- **宿主转发模板** `scripts/host_forward.sh`（推到服务器执行）：
  `NAME=<容器名> MAPS="<宿主端口>:<容器IP>:<容器端口> [...]" bash host_forward.sh`
  自带宿主端口占用检查、容器连通性预检、systemd oneshot 固化（PREROUTING/OUTPUT DNAT + DOCKER-USER 放行）。
- **不改客户/交付方的服务配置**（compose、绑定地址等）。若容器内服务只绑 127.0.0.1 导致宿主 curl 容器 IP 不通，把问题清单反馈给对方自己改——10-21 用户明确要求。
- ⚠️ 容器 IP 是 docker 动态分配，容器重建后宿主转发目标 IP 要同步改（脚本 IP 写死）。

### 3. 防火墙（一条命令）

```bash
export FW_HOST=https://10.10.127.254 FW_USER=admin FW_PASS='<凭据文档里的密码>'
scripts/fw_dnat.py open-port <公网端口> --to <宿主内网IP> --desc '<描述>'
# = 冲突检查 → 建服务对象 TCP<PORT> → 建 DNAT → 移到"API域名"兜底规则前 → 报规则ID
```

单项操作（排障用）：`list` / `services` / `add-service` / `add-dnat` / `move-before` / `delete` / `watch`。

### 4. 验证（必须 VPN 外发起）

本机 curl 公网地址（VPN 只推 10.10.127.0/24 路由，公网 IP 走本地宽带=真实外网）：
`curl -s --noproxy '*' -m 10 http://58.22.5.109:<PORT>/` 看 HTTP 码 + 响应头归属（如 X-Molispark-Version 分辨后端）；再 `fw_dnat.py watch <规则ID>` 看匹配计数涨。

### 5. 记录

①凭据文档：DNAT 表加行 + 服务器小节条目（写明链路三跳、宿主转发单元名、脆弱点）；②`~/.agents/memory/` 更新项目页；③飞书云版双写（docx + Base「端口映射」表）——提醒或补同步。

---

## 场景 A：新工作区容器（10-20 固化）

用 `scripts/provision.sh`（推送执行或先 put 再 bash），参数：`NAME PORT CPUS MEM SHM`。

- **镜像源必须显式 daocloud**：`FROM docker.m.daocloud.io/library/ubuntu:22.04`。15 主 docker 的 registry-mirror 指向死地址 `192.168.10.201:8083`，裸 `ubuntu:22.04` 拉取 i/o timeout。
- 基础镜像 = ubuntu:22.04 + systemd + openssh + docker.io；`PermitRootLogin yes` + `PasswordAuthentication yes`，`systemctl enable ssh docker`，`STOPSIGNAL SIGRTMIN+3`。
- 运行参数：`--privileged --cgroupns=private --cpus=N --memory=M --shm-size=S --restart unless-stopped -p <PORT>:22 -v /opt/data/<NAME>:/data -v /opt/data/<NAME>/docker:/var/lib/docker`。**内层 dockerd 数据必须显式挂到 /opt/data**，否则演示方拉镜像吃宿主根盘。
- 端口：先宿主 `ss -tln | grep <PORT>` 再 `fw_dnat.py list` 对照，51741-51745 已占用；同端口公网映射（非 52740 式偏移）。
- 密码：随机 20 位，`chpasswd` 设置，存服务器 `/root/.<NAME>-cred`(600)；回显密码仅进当次对话与凭据文档，禁入记忆/报告正文以外的存储。
- 验证：`docker exec <NAME> systemctl is-active ssh docker`；`cat /sys/fs/cgroup/cpu.max memory.max`；宿主 `head -c 40 < /dev/tcp/127.0.0.1/<PORT>` 见 `SSH-2.0` banner。
- 公网：`scripts/fw_dnat.py open-port <PORT> --to 10.10.127.15 --desc '<NAME>-ssh'`。
- 公网验证必须 VPN 外：paramiko `connect('58.22.5.109', <PORT>, 'root', <PW>)` + exec `hostname; cat /sys/fs/cgroup/cpu.max memory.max`。

---

## 防火墙 API 速查（脚本已封装，手工排障时才需要）

设备：安恒明御 DAS-Gateway-A1，webui `https://10.10.127.254`。控制策略复用 `dnat-to-15`/`dnat-to-16`（any→宿主全服务），**无需新建**。

1. **登录**：POST `login_auth.php`，字段 `user`/`pwd`/`vldcode`/`encrypt=1`；`pwd=stringtoaescovert(密码)` = RSA PKCS1v15（公钥在 `/webui/js/rsajs/rsa-security.js`，页面公开内容）。须带 Referer + `X-Requested-With: XMLHttpRequest`，否则报"请求refer来自非法地址"。验证码 `/php/common/checknum_creat.php?module=config_authnum`：tesseract + PIL 灰度/LANCZOS 4x 放大/阈值 140/psm 7-8-6 管线可靠（10-21 一次过；此前裸读图 8 连败）。浏览器路线降级为兜底（请用户手动登录后接管）。
2. **服务对象**：POST `?g=obj_service_custom_add`（**form 无 action、target=iframe，不是 addsave URL**）；`service_items` = JSON 数组字符串 `[{"type":"tcp","source":"0-65535","destination":"<P>-<P>"}]`；提交成功特征 = 下一次 `?g=net_dnat_add` 下拉里出现对象名。**⚠️ 头号坑：表单字段 ID 与显示标签错位**——`tcp_src_port_*` 输入框显示为"目的端口"（其值最终进 destination）、`tcp_dst_port_*` 显示为"源端口"。判据：对象内容必须是 `TCP目的端口:<P>-<P> 源端口:0-65535`。填反零报错零命中。另坑：tcp 源端口 end 框的 name 是 `src_port_end`（不是 tcp_src_port_end）。
3. **DNAT 规则**：POST `?g=net_dnat_add`（同样无 action）带 `submit_post=net_dnat_addsave` + 该页 fresh `token`。字段：`enable=1 addr_type=0 src_addr=any dst_addr=58.22.5.109 service=TCP<P> trans_if=ge9 trans_type=2 trans_dst=<宿主IP> trans_port=<P> description=...`。
4. **调序**：DNAT 按**列表顺序匹配**（显示 ID 序≠匹配序），`API域名`兜底（service=any→.15:8443）必须排最后，新规则默认追加在兜底后**永不命中**。调序：POST `?g=net_dnat_show`，参数 `directval=1`(目标ID之前)`/id/dst_id/submit_post=net_nat_priority`。
5. **验证命中**：`?g=net_dnat_jsondata`（**固定 20 条/页，必须翻页**）看规则 `match_count` 增长。改动即持久化（配置维护页只有导入/导出/双备份）。
6. **删除**：GET `?g=net_dnat_delete&id=<规则ID>&pro_type=0`；服务对象引用数=0 时在对象管理页删。

## 回滚

```bash
# 服务器侧（工作区容器）
docker rm -f <NAME>; rm -rf /opt/data/<NAME>   # 数据目录确认无人再用后
# 服务器侧（宿主转发）
systemctl disable --now <NAME>-forward.service; rm -f /usr/local/sbin/<NAME>-forward.sh
# 防火墙侧
scripts/fw_dnat.py delete <规则ID>   # 服务对象引用数=0 后再在页面上删
```

## 附：历史经验（来自 10-20 浏览器路线，已过时但排障可参考）

- EasyUI combobox 原生 select 赋值不生效，浏览器里须注入 `<script>` 调 `$("#id").combobox("setValue",v)`（evaluate 隔离世界拿不到 jQuery）。
- 15 上 python paramiko 会话嵌套 nohup 偶发挂死，长命令拆独立短调用。
