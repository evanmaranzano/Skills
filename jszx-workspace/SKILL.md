---
name: jszx-workspace
description: >
  在 jszx 服务器(主力 15 号机)上开"特权工作区容器":systemd+sshd+内层 docker(dind)、
  cgroup 资源限额(CPU/内存/shm)、数据落 /opt/data 大盘、公网 SSH 经安恒明御防火墙
  DNAT(58.22.5.109)。适用于:演示空间、出租容器、客户独立环境、任何"划一块独立
  资源+公网 SSH"需求。当用户说"开一个工作区/演示空间容器""划独立环境""出租容器"
  "公网 SSH 容器""防火墙加端口映射/DNAT"时使用。含明御防火墙的三个已知坑:
  服务对象字段 ID 与标签错位(端口填反零报错)、DNAT 规则必须排 API域名兜底之前、
  登录验证码对视觉模型极不友好。凭据一律查「服务器信息整理」最新版,不入本 skill。
---

# jszx workspace — 特权工作区容器 + 公网 SSH 配置

2026-10-20 首次完整跑通(molispark-demo 演示空间)。本 skill 是该过程的固化。
前置依赖:SSL VPN 已拨通(10.10.127.x 可达);服务器与防火墙凭据查
`DeskBox\文档\服务器与运维\服务器信息整理<最新日期>.md`(规则:`reference_jszx_server_inventory`)。

## 选址决策(先想清楚再动手)

| 候选 | 何时选 | 红线 |
|---|---|---|
| **15(默认)** | 演示/对外服务,aarch64 可接受 | 它是 app 服务器,别挤占 26566/8443 等既有端口;**主 docker daemon**,dubhe 系在 docker-dubhe daemon,别混 |
| 16(x86_64) | 交付物只有 x86 镜像/二进制 | 根盘常年 98%,一切新数据必须落 /opt/data;GPU 生产机,职责已杂 |
| 17 | 仅当 15/16 都不可用 | GLM-5.3-Flash 生产推理机,保持单一职责 |

架构检查:15/17 是 aarch64——交付镜像须 arm64/multi-arch,先跟交付方确认。

## Part A — 服务器侧(15,经 om_ssh.py root)

用 `scripts/provision.sh`(推送执行或先 put 再 bash),参数:`NAME` `PORT` `CPUS` `MEM` `SHM`。
关键点(脚手架已固化,勿手拼):

- **镜像源必须显式 daocloud**:`FROM docker.m.daocloud.io/library/ubuntu:22.04`。15 主 docker 的 registry-mirror 指向死地址 `192.168.10.201:8083`,裸 `ubuntu:22.04` 拉取 i/o timeout。
- 基础镜像 = ubuntu:22.04 + systemd + openssh + docker.io(内层 dind 自助部署)。SSH 配置 `PermitRootLogin yes` + `PasswordAuthentication yes`,`systemctl enable ssh docker`,`STOPSIGNAL SIGRTMIN+3`。
- 运行参数:`--privileged --cgroupns=private --cpus=N --memory=M --shm-size=S --restart unless-stopped -p <PORT>:22 -v /opt/data/<NAME>:/data -v /opt/data/<NAME>/docker:/var/lib/docker`。**内层 dockerd 数据必须显式挂到 /opt/data**,否则演示方拉镜像吃宿主根盘。
- 端口选择:先 `ss -tln | grep <PORT>`(宿主)再对照防火墙 DNAT 表(第十三节),51741-51745 已占用。选同端口公网映射(公网=内网端口,非 52740 式偏移)。
- 密码:`head -c200 /dev/urandom | tr -dc A-Za-z0-9 | head -c20`,`chpasswd` 设置,存 `/root/.<NAME>-cred`(600)。**回显密码仅进当次对话与凭据文档,禁入记忆/报告正文以外的存储。**
- 验证:`docker exec <NAME> systemctl is-active ssh docker`;`cat /sys/fs/cgroup/cpu.max memory.max`(应为 N*100000 100000 与 M 字节数);宿主 `head -c 40 < /dev/tcp/127.0.0.1/<PORT>` 应见 `SSH-2.0` banner。

## Part B — 防火墙侧(安恒明御 DAS-Gateway-A1,https://10.10.127.254)

入口:策略配置 → NAT转换策略 → 目的NAT。控制策略复用既有 `dnat-to-15`(any→.15 全服务),**无需新建策略**。

⚠️ **登录验证码对视觉模型极不友好(实测 8 连败,位图字体+噪点)**。两条路:
1. **请用户手动登录**(最快,本次实证);
2. 自动化:登录 POST 为 `login_auth.php`(字段 user/pwd=stringtoaescovert(密码)/vldcode/encrypt=1;RSA 公钥在 `/webui/js/rsajs/rsa-security.js`,PKCS1v15,须带 Referer+XHR 头,否则报"请求refer来自非法地址")。验证码 OCR 用 tesseract + PIL LANCZOS 4x 平滑放大 + 阈值 140(管线代码模式见记忆页 project_molispark_demo_space)。

建规则四步(每步都有坑):

1. **建服务对象**:服务下拉旁"新建"菜单按钮 → 自定义服务。**⚠️ 头号坑:表单字段 ID 与显示标签错位——`tcp_src_port_*` 输入框显示为"目的端口"、`tcp_dst_port_*` 显示为"源端口"。按 ID 直填必反!** 判据:保存后对象内容必须是 `TCP目的端口:<P>-<P>源端口:0-65535`(对照 TCP51740/51750)。填反后规则零报错零命中,匹配计数永远 0。
2. **建 DNAT 规则**:新建 → EasyUI combobox **原生 select 赋值不生效**,eval 须注入 `<script>` 在主世界调 `$("#id").combobox("setValue",v)`(evaluate 是隔离世界拿不到 jQuery)。目标值:目的地址 58.22.5.109、服务 TCP<PORT>、接口 ge9、转换类型"端口映射"、转换后IP 10.10.127.15、转换后端口 <PORT>。hidden 校验:`dst_addr/service/trans_if/trans_dst/trans_port` 五值全对再点提交。
3. **调序**:新规则追加在 `API域名`兜底规则(service=any→.15:8443)**之后,必须前移**,否则永不命中。列表页底部"NAT优先级"表单:被移动ID=<新规则ID>、目标位置=目标ID之前、目标位置ID=<兜底规则ID>、提交。显示 ID 序≠匹配序,以此表单为准。
4. **验证命中**:刷新目的NAT列表看该规则"匹配次数">0。设备改动即持久化(无需手动保存;配置维护页只有导入/导出/双备份)。

## Part C — 端到端验证与记录

- 公网验证**必须从 VPN 外**发起(家里直连):paramiko `connect('58.22.5.109', <PORT>, 'root', <PW>)` + exec `hostname; cat /sys/fs/cgroup/cpu.max memory.max`。
- 记录三处:①凭据文档加 DNAT 表行 + 服务器小节条目(密码明文进文档可以,进 skill 不行);②`~/.agents/memory/` 建项目页;③若凭据文档有"飞书云版双写"约定,提醒用户或补同步。
- 清理:含密码的临时脚本用后即删;浏览器标签页释放。

## 回滚

```bash
# 服务器侧
docker rm -f <NAME>; rm -rf /opt/data/<NAME>   # 数据目录确认无人再用后
# 防火墙侧:目的NAT列表勾选该规则→删除;服务对象若引用数=0 一并删(对象管理→服务对象→自定义)
```
