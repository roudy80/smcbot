#!/bin/bash
# Start everything: bots + dashboard + cloudflare tunnel + watchdog
# Run once when you open your Chromebook. Everything restarts automatically.

cd "$(dirname "$0")"
source venv/bin/activate 2>/dev/null || true

mkdir -p logs

echo "=== SMC Trading Bot ==="
echo "Starting services..."

# Kill any stale processes first
pkill -f "python.*bot.py"       2>/dev/null
pkill -f "python.*crypto_bot.py" 2>/dev/null
pkill -f "python.*dashboard.py" 2>/dev/null
pkill -f "cloudflared tunnel"   2>/dev/null
sleep 2

# Start dashboard
nohup python dashboard.py >> logs/dashboard.log 2>&1 &
echo "Dashboard started → http://localhost:5050"

# Start Cloudflare tunnel (public phone URL)
if command -v cloudflared &>/dev/null; then
    nohup cloudflared tunnel --url http://localhost:5050 >> logs/tunnel.log 2>&1 &
    sleep 3
    TUNNEL_URL=$(grep -o 'https://.*trycloudflare.com' logs/tunnel.log | tail -1)
    echo "Phone URL: $TUNNEL_URL"
else
    echo "cloudflared not installed — dashboard at localhost:5050 only"
fi

# Start watchdog (starts bots + monitors them)
bash watchdog.sh &
WATCHDOG_PID=$!
echo "Watchdog PID: $WATCHDOG_PID"

echo ""
echo "All running. Logs in ./logs/"
echo "  tail -f logs/bot.log          # stock bot"
echo "  tail -f logs/crypto_bot.log   # crypto bot"
echo "  tail -f logs/dashboard.log    # dashboard"
echo ""
echo "To stop everything: pkill -f 'python.*bot' && pkill -f cloudflared"
