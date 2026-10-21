#!/usr/bin/env bash
# host_forward.sh — 在宿主(15)上建"宿主端口 -> 容器IP:端口" DNAT 转发并固化 systemd
# 2026-10-21 实测固化(模式同 dubhe-staging-3000-forward/molispark-demo-forward)。
# 适用: 服务在容器内层(未用 -p 发布到宿主), 宿主需承接公网 DNAT 流量。
#
# 用法(在目标服务器上执行):
#   NAME=molispark-demo MAPS="3001:172.17.0.6:3000 33001:172.17.0.6:33000" bash host_forward.sh
#
# ⚠️ 脆弱点: 目标容器 IP 是 docker 动态分配, 容器重建后需改本脚本并重跑。
# ⚠️ 执行前自查: ss -tln 确认宿主端口空闲; 宿主到容器IP:端口 curl 可通。
set -euo pipefail

NAME=${NAME:?need NAME}
MAPS=${MAPS:?need MAPS, e.g. "3001:172.17.0.6:3000 33001:172.17.0.6:33000"}

# 0) 宿主端口占用检查
for m in ${MAPS}; do
  hp=${m%%:*}; tgt=${m#*:}; tip=${tgt%%:*}; tp=${tgt##*:}
  if ss -tln | grep -q ":${hp} "; then
    echo "FATAL: host port ${hp} occupied:"; ss -tln | grep ":${hp} "; exit 1
  fi
  if ! curl -s -m 5 -o /dev/null "http://${tip}:${tp}/"; then
    echo "WARN: ${tip}:${tp} 不通(容器侧可能未绑 0.0.0.0, 公网将静默失效, 先修再映射)"
  fi
done

# 1) 生成转发脚本
cat > /usr/local/sbin/${NAME}-forward.sh <<EOF
#!/bin/bash
set -u
add() {
  iptables -t nat -C PREROUTING -p tcp --dport "\$1" -j DNAT --to-destination "\$2" 2>/dev/null || \
  iptables -t nat -A PREROUTING -p tcp --dport "\$1" -j DNAT --to-destination "\$2"
  iptables -t nat -C OUTPUT -o lo -p tcp --dport "\$1" -j DNAT --to-destination "\$2" 2>/dev/null || \
  iptables -t nat -A OUTPUT -o lo -p tcp --dport "\$1" -j DNAT --to-destination "\$2"
  iptables -C DOCKER-USER -p tcp -d "\${2%:*}" --dport "\${2##*:}" -j ACCEPT 2>/dev/null || \
  iptables -I DOCKER-USER -p tcp -d "\${2%:*}" --dport "\${2##*:}" -j ACCEPT
}
EOF
for m in ${MAPS}; do
  hp=${m%%:*}; tgt=${m#*:}
  echo "add ${hp} ${tgt}" >> /usr/local/sbin/${NAME}-forward.sh
done
chmod 755 /usr/local/sbin/${NAME}-forward.sh

# 2) systemd 固化
cat > /etc/systemd/system/${NAME}-forward.service <<EOF
[Unit]
Description=Forward host ports to ${NAME} container (${MAPS})
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/${NAME}-forward.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now ${NAME}-forward.service
systemctl is-active ${NAME}-forward.service

# 3) 本机自检
for m in ${MAPS}; do
  hp=${m%%:*}
  code=$(curl -s -m 8 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${hp}/" || true)
  echo "host 127.0.0.1:${hp} -> HTTP ${code}"
done
echo "OK. NEXT: fw_dnat.py open-port <PORT> --to <宿主内网IP> --desc '...'  (见 SKILL.md)"
