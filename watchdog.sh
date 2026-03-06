#!/bin/bash
# Watchdog: keeps bot.py, crypto_bot.py, and dashboard.py running.
# If any crash, it restarts with a 10-second delay.
# Usage: bash watchdog.sh   (runs in foreground, Ctrl+C to stop)

cd "$(dirname "$0")"
source venv/bin/activate 2>/dev/null || true

LOG_DIR="logs"
mkdir -p "$LOG_DIR"

start_process() {
    local name="$1"
    local script="$2"
    local logfile="$LOG_DIR/${name}.log"

    if pgrep -f "python.*${script}" > /dev/null 2>&1; then
        echo "[watchdog] $name already running"
        return
    fi

    echo "[watchdog] Starting $name..."
    nohup python "$script" >> "$logfile" 2>&1 &
    echo "[watchdog] $name started (PID $!), logging to $logfile"
}

echo "[watchdog] Starting all bots at $(date)"
start_process "bot"          "bot.py"
start_process "crypto_bot"   "crypto_bot.py"
start_process "dashboard"    "dashboard.py"

echo "[watchdog] All processes started. Monitoring every 30s..."
echo "[watchdog] Press Ctrl+C to stop the watchdog (bots keep running)"

while true; do
    sleep 30

    for entry in "bot:bot.py" "crypto_bot:crypto_bot.py" "dashboard:dashboard.py"; do
        name="${entry%%:*}"
        script="${entry##*:}"
        logfile="$LOG_DIR/${name}.log"

        if ! pgrep -f "python.*${script}" > /dev/null 2>&1; then
            echo "[watchdog] $(date) — $name crashed! Restarting in 10s..."
            sleep 10
            nohup python "$script" >> "$logfile" 2>&1 &
            echo "[watchdog] $name restarted (PID $!)"
        fi
    done
done
