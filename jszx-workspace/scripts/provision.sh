#!/usr/bin/env bash
# jszx 服务器(15 主 docker)特权工作区容器创建脚本 —— 在目标服务器上执行
# 用法: NAME=molispark-demo PORT=51745 CPUS=8 MEM=16g SHM=2g bash provision.sh
# 推送执行(本机): 见 SKILL.md Part A;凭据经 om_ssh.py,密码不落本脚本
set -euo pipefail

NAME=${NAME:?need NAME} PORT=${PORT:?need PORT} CPUS=${CPUS:-8} MEM=${MEM:-16g} SHM=${SHM:-2g}
ROOT=/opt/data/${NAME}

# 0) 端口占用检查(防火墙 DNAT 表需人工另查,见 SKILL.md Part B)
if ss -tln | grep -q ":${PORT} "; then echo "FATAL: port ${PORT} occupied"; ss -tln | grep ":${PORT} "; exit 1; fi

# 1) 目录与 Dockerfile(daocloud 源:15 主 docker 的 registry-mirror 是死地址)
mkdir -p ${ROOT}/build ${ROOT}/docker
if [ ! -f ${ROOT}/build/Dockerfile ]; then
cat > ${ROOT}/build/Dockerfile <<'EOF'
FROM docker.m.daocloud.io/library/ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive TZ=Asia/Shanghai
RUN apt-get update && apt-get install -y --no-install-recommends \
    systemd systemd-sysv openssh-server sudo docker.io \
    vim less curl wget git jq unzip tar htop lsof procps \
    net-tools iproute2 iputils-ping dnsutils ca-certificates tzdata \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config \
    && sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config \
    && systemctl enable ssh.service docker.service
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
EOF
fi

# 2) 构建镜像
docker build -t ${NAME}-base:systemd ${ROOT}/build

# 3) 运行容器:privileged+systemd+dind;内层 docker 数据显式落 /opt/data
docker run -d --name ${NAME} \
  --privileged --cgroupns=private \
  --cpus=${CPUS} --memory=${MEM} --shm-size=${SHM} \
  --restart unless-stopped \
  -p ${PORT}:22 \
  -v ${ROOT}:/data \
  -v ${ROOT}/docker:/var/lib/docker \
  ${NAME}-base:systemd

# 4) 等待容器内 systemd 就绪(竞态修复:set -e 下单次 is-active 若在 systemd 未起时失败,
#    脚本会在设密码前中止,留下 root 锁定的容器;重试至 ~45s,失败则 dump 日志退出)
READY=0
for i in $(seq 1 8); do
  if docker exec ${NAME} systemctl is-active --quiet ssh docker 2>/dev/null; then READY=1; break; fi
  sleep 5
done
[ ${READY} -eq 1 ] || { echo "FATAL: systemd in ${NAME} not ready after 45s"; docker logs --tail 30 ${NAME}; exit 1; }

# 5) root 密码(随机 20 位;存服务器 /root/.<NAME>-cred 600;回显一次供登记凭据文档)
PW=$(head -c200 /dev/urandom | tr -dc A-Za-z0-9 | head -c20)
echo "root:${PW}" | docker exec -i ${NAME} chpasswd
echo "${PW}" > /root/.${NAME}-cred && chmod 600 /root/.${NAME}-cred

# 6) 自检
echo "--- cpu.max / memory.max ---"
docker exec ${NAME} cat /sys/fs/cgroup/cpu.max /sys/fs/cgroup/memory.max
echo "--- ssh banner(本机回环) ---"
timeout 5 bash -c "exec 3<>/dev/tcp/127.0.0.1/${PORT} && head -c 40 <&3"; echo
echo "OK. password: ${PW}"
echo "NEXT: 防火墙开公网(脚本化): export FW_PASS='...'; scripts/fw_dnat.py open-port ${PORT} --to 10.10.127.15 --desc '${NAME}-ssh'"
