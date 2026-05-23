#!/usr/bin/env bash
# 在云服务器上安装并启用 coturn（Alibaba Cloud Linux / RHEL 系）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONF_SRC="$ROOT/deploy/coturn/turnserver.conf"
if [[ ! -f "$CONF_SRC" ]]; then
  CONF_SRC="$ROOT/deploy/coturn/turnserver.conf.example"
  echo "未找到 turnserver.conf，使用 example 模板（请先编辑 IP/账号）"
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请使用 root 或 sudo 运行: sudo bash deploy/coturn/install.sh"
  exit 1
fi

if ! command -v turnserver >/dev/null 2>&1; then
  yum install -y coturn
fi

if [[ -f /etc/coturn/turnserver.conf && ! -f /etc/coturn/turnserver.conf.bak ]]; then
  cp /etc/coturn/turnserver.conf /etc/coturn/turnserver.conf.bak
fi

cp "$CONF_SRC" /etc/coturn/turnserver.conf
mkdir -p /var/log/coturn
chown coturn:coturn /var/log/coturn

systemctl enable coturn
systemctl restart coturn
systemctl --no-pager status coturn

echo ""
echo "coturn 已启动。请确认云安全组已放行："
echo "  - 3478/udp, 3478/tcp"
echo "  - 49152-65535/udp"
echo ""
ss -ulnp | grep turnserver || true
ss -tlnp | grep turnserver || true
