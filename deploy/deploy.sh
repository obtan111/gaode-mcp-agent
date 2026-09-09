#!/usr/bin/env bash
# ============================================================
#  AI 旅行助手 - 云服务器一键部署脚本（Ubuntu 22.04 / 24.04）
#
#  前置条件：
#    1. 已把项目 clone/上传到 /opt/ai-travel（含 deploy/ 目录）
#    2. 已把 .env 放到 /opt/ai-travel/.env（含 Supabase/DeepSeek/智谱/高德密钥，
#       密钥不入库，请通过 scp/sftp 单独上传）
#    3. 域名 A 记录已解析到本服务器公网 IP，且已完成 ICP 备案
#
#  用法：sudo DOMAIN=api.yourdomain.com bash deploy/deploy.sh
# ============================================================
set -euo pipefail

APP_DIR="/opt/ai-travel"
# 域名必填：改成你自己的备案域名
DOMAIN="${DOMAIN:-}"
if [ -z "$DOMAIN" ]; then
  echo "[ERROR] 请传入域名，例如：sudo DOMAIN=api.example.com bash deploy/deploy.sh"
  exit 1
fi

echo "===== [1/6] 安装 Python 3.11 ====="
apt-get update -y
apt-get install -y software-properties-common curl
add-apt-repository -y ppa:deadsnakes/ppa
apt-get update -y
apt-get install -y python3.11 python3.11-venv python3.11-dev

echo "===== [2/6] 创建虚拟环境并安装依赖 ====="
cd "$APP_DIR"
python3.11 -m venv venv
./venv/bin/pip install --upgrade pip
# 国内加速镜像；海外服务器可去掉 -i 参数
./venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

echo "===== [3/6] 检查 .env ====="
if [ ! -f "$APP_DIR/.env" ]; then
  echo "[ERROR] 缺少 $APP_DIR/.env，请先上传（含 Supabase/DeepSeek/智谱/高德 密钥）"
  exit 1
fi

echo "===== [4/6] 安装 systemd 服务（开机自启 + 崩溃拉起） ====="
cp "$APP_DIR/deploy/ai-travel.service" /etc/systemd/system/ai-travel.service
systemctl daemon-reload
systemctl enable ai-travel
systemctl restart ai-travel
sleep 6
if curl -sf http://127.0.0.1:8100/openapi.json > /dev/null; then
  echo "[OK] 后端已启动：http://127.0.0.1:8100"
else
  echo "[WARN] 后端未就绪，查看日志：journalctl -u ai-travel -n 50"
fi

echo "===== [5/6] 安装 Caddy 并配置 HTTPS/WSS ====="
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update -y
apt-get install -y caddy
sed "s/api\.example\.com/$DOMAIN/g" "$APP_DIR/deploy/Caddyfile" > /etc/caddy/Caddyfile
systemctl reload caddy

echo "===== [6/6] 部署完成 ====="
echo "  HTTPS  : https://$DOMAIN/openapi.json"
echo "  WSS    : wss://$DOMAIN/api/chat/ws"
echo "  日志    : journalctl -u ai-travel -f"
echo ""
echo "  接下来（小程序侧）："
echo "  1. miniprogram/utils/config.js 把 ENV 改为 'prod'，域名换成 $DOMAIN，重新上传"
echo "  2. 微信公众平台 -> 开发管理 -> 开发设置 -> 服务器域名："
echo "       request/uploadFile : https://$DOMAIN"
echo "       socket             : wss://$DOMAIN"
echo "  3. 开发者工具 -> 上传 -> 版本管理 -> 设为体验版 -> 扫码"
