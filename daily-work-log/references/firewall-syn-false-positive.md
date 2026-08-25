# 防火墙 SYN 假握手 + 连接测试正确做法（daily-work-log 相关排查的记错坑）

> 背景：安恒明御安全网关 DAS-Gateway-A1（本机房 2026-08-12 新换的防火墙）对公网端口做
> **SYN 代理式假握手**——即使某端口**没有任何 NAT 映射**，TCP connect 也会「成功」（能连上），
> 但**数据不回来**（读 banner 超时 / 断连）。

## 判据：不要用 TCP connect 判断服务可用

错误判据（假阳性重灾区）：
```text
TCP 端口能连上  => 服务开了？
```
在明御防火墙上，`51741` 可以「能连上」，但实际上根本没有任何 DNAT 规则指向它。

正确判据（真实可用）：
1. **SSH**：连接后能读到 `SSH-2.0-…` banner；更进一步用 paramiko 完成完整建连→握手→认证→
   执行命令拿 hostname。**拿到 banner / 登录成功才算通。**
2. **HTTP**：能拿到真实 HTTP 响应（不是空 RST）。
3. 任一 TCP 数据往返成功（读到对端发的字节）。

## 实测方法（用过的、可复用）

- 直接连 + 读 banner（.NET TcpClient 读前 N 字节）：
  - 能读到 `SSH-2.0-OpenSSH_8.9p1…` ⇒ 真 SSH；读不到就 timeout ⇒ 假握手/未映射。
- paramiko 完整登录（脚本化批量）：
  ```python
  import paramiko
  c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
  c.connect(host,port=p,username="root",password=pw,timeout=12,banner_timeout=12,allow_agent=False,look_for_keys=False)
  si,so,se=c.exec_command("hostname; uname -m"); print(so.read().decode())
  ```
- **对照实验**：同时探测几个肯定没映射的随机端口（如 12345/47000/53999）。若它们也「能连上」
  而读不到 banner，坐实「这台防火墙对任意端口假握手」——那之前候选端口的「能连上」就不可信，
  必须重新逐一验 banner。

## 排查链路模板（为什么不通）

当公网连不上而内网正常时，按此定位，别逐项瞎猜：
1. 内网直连容器 SSH 正常吗？（排除容器/sshd/端口监听问题）
2. 广扫候选端口，拿 banner 与否判真伪。
3. 防火墙侧抓包（`tcpdump`），看探测包到底有没有到达目标服务器；零包到达 ⇒ NAT 规则没匹配。
4. 对照一条能用的规则（如 dubhe-mig 的 52740），逐字段比对 NAT（**目的端口别填到源端口**、
   接口 ge9、服务项）与控制策略。
5. 修正后重测，以 banner / 登录成功为最终判据。
