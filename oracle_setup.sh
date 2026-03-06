#!/bin/bash
# ============================================================
# Oracle Cloud Free Tier — SMC Bot Server Setup
# Run this ONCE on a fresh Ubuntu 22.04 VM
#
# What it does:
#   1. Installs Python 3.11, git, tmux, cloudflared
#   2. Clones the repo and sets up venv
#   3. Creates .env from environment variables
#   4. Installs bots as systemd services (auto-start on reboot)
#   5. Configures a permanent Cloudflare named tunnel
#
# Before running:
#   export ALPACA_API_KEY=...
#   export ALPACA_SECRET_KEY=...
#   export TELEGRAM_BOT_TOKEN=...
#   export TELEGRAM_CHAT_ID=...
#   export ANTHROPIC_API_KEY=...       (optional — for Claude analysis)
#   export CF_TUNNEL_TOKEN=...         (from cloudflare.com after creating tunnel)
#
# Usage:
#   bash oracle_setup.sh
# ============================================================

set -e

REPO="https://github.com/roudy80/smcbot.git"
BOT_DIR="/home/ubuntu/smcbot"
SERVICE_USER="ubuntu"

echo "=== SMC Bot — Oracle Cloud Setup ==="
echo ""

# ---- System packages ----
echo "[1/6] Installing system packages..."
sudo apt update -q
sudo apt install -y python3.11 python3.11-venv python3-pip git tmux curl

# ---- Cloudflared ----
echo "[2/6] Installing cloudflared..."
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | \
    sudo gpg --dearmor -o /usr/share/keyrings/cloudflare-main.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] \
    https://pkg.cloudflare.com/cloudflared focal main" | \
    sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update -q && sudo apt install -y cloudflared

# ---- Clone repo ----
echo "[3/6] Cloning repo..."
if [ -d "$BOT_DIR" ]; then
    git -C "$BOT_DIR" pull
else
    git clone "$REPO" "$BOT_DIR"
fi
cd "$BOT_DIR"

# ---- Python venv ----
echo "[4/6] Setting up Python venv..."
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "Python packages installed."

# ---- .env file ----
echo "[5/6] Creating .env..."
cat > "$BOT_DIR/.env" <<ENV
ALPACA_API_KEY=${ALPACA_API_KEY:?Set ALPACA_API_KEY first}
ALPACA_SECRET_KEY=${ALPACA_SECRET_KEY:?Set ALPACA_SECRET_KEY first}
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:?Set TELEGRAM_BOT_TOKEN first}
TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID:?Set TELEGRAM_CHAT_ID first}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
CRYPTO_SYMBOLS=BTC/USD,ETH/USD
CRYPTO_ALLOC_PCT=10.0
SYMBOLS=SPY,QQQ,NVDA,AAPL,MSFT
ENV
chmod 600 "$BOT_DIR/.env"
echo ".env created."

# ---- systemd services ----
echo "[6/6] Installing systemd services..."

make_service() {
    local name="$1"
    local script="$2"
    cat > "/etc/systemd/system/${name}.service" <<SVC
[Unit]
Description=SMC Bot — $name
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$BOT_DIR
Environment="PATH=$BOT_DIR/venv/bin:/usr/bin:/bin"
ExecStart=$BOT_DIR/venv/bin/python $BOT_DIR/$script
Restart=always
RestartSec=15
StandardOutput=append:$BOT_DIR/logs/${name}.log
StandardError=append:$BOT_DIR/logs/${name}.log

[Install]
WantedBy=multi-user.target
SVC
}

mkdir -p "$BOT_DIR/logs"
sudo bash -c "$(declare -f make_service); make_service smcbot-stocks    bot.py"
sudo bash -c "$(declare -f make_service); make_service smcbot-crypto    crypto_bot.py"
sudo bash -c "$(declare -f make_service); make_service smcbot-dashboard dashboard.py"

# Cloudflare named tunnel (permanent URL — same every reboot)
if [ -n "${CF_TUNNEL_TOKEN:-}" ]; then
    sudo cloudflared service install "$CF_TUNNEL_TOKEN"
    echo "Cloudflare tunnel service installed."
else
    # Fallback: quick tunnel (URL changes on reboot but works now)
    cat > /etc/systemd/system/smcbot-tunnel.service <<TSVC
[Unit]
Description=SMC Bot — Cloudflare Tunnel
After=smcbot-dashboard.service

[Service]
Type=simple
User=$SERVICE_USER
ExecStart=/usr/bin/cloudflared tunnel --url http://localhost:5050
Restart=always
RestartSec=10
StandardOutput=append:$BOT_DIR/logs/tunnel.log
StandardError=append:$BOT_DIR/logs/tunnel.log

[Install]
WantedBy=multi-user.target
TSVC
    echo "Quick tunnel service installed (URL changes on reboot)."
    echo "For a permanent URL: sign up at cloudflare.com (free) and re-run with CF_TUNNEL_TOKEN=..."
fi

sudo systemctl daemon-reload
sudo systemctl enable smcbot-stocks smcbot-crypto smcbot-dashboard
sudo systemctl start  smcbot-stocks smcbot-crypto smcbot-dashboard

[ -f /etc/systemd/system/smcbot-tunnel.service ] && \
    sudo systemctl enable smcbot-tunnel && sudo systemctl start smcbot-tunnel

echo ""
echo "=== DONE ==="
echo ""
echo "All bots running as systemd services (auto-restart on crash, auto-start on reboot)"
echo ""
echo "Status:"
sudo systemctl status smcbot-stocks smcbot-crypto smcbot-dashboard --no-pager -l | grep -E 'Active|PID' || true
echo ""
echo "Phone URL (check logs for Cloudflare URL):"
sleep 3 && grep -o 'https://.*trycloudflare.com' "$BOT_DIR/logs/tunnel.log" 2>/dev/null | tail -1 || \
    echo "  tail -f $BOT_DIR/logs/tunnel.log"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status smcbot-stocks   # check stock bot"
echo "  sudo systemctl status smcbot-crypto   # check crypto bot"
echo "  tail -f $BOT_DIR/logs/bot.log         # live stock logs"
echo "  tail -f $BOT_DIR/logs/crypto_bot.log  # live crypto logs"
echo "  sudo systemctl restart smcbot-stocks  # manual restart"
