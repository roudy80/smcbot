"""
SMC Bot Live Dashboard
Accessible from Chromebook at: http://localhost:5050
Auto-refreshes every 15 seconds.
Shows: account value, open positions, P&L, signals, upcoming FVG zones, trade history.
"""

import json
import requests
from pathlib import Path
from datetime import datetime, date
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 5050

# Alpaca credentials loaded directly to avoid circular import issues
from dotenv import load_dotenv
import os
load_dotenv()
ALPACA_KEY    = os.getenv("ALPACA_API_KEY","")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY","")
ALPACA_BASE   = "https://paper-api.alpaca.markets"


def alpaca(path):
    try:
        r = requests.get(f"{ALPACA_BASE}{path}",
            headers={"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET},
            timeout=5)
        return r.json() if r.status_code == 200 else {}
    except:
        return {}


def load_logs():
    f = Path("logs/trades.jsonl")
    if not f.exists(): return []
    return [json.loads(l) for l in f.read_text().strip().split("\n") if l.strip()]

def load_crypto_logs():
    f = Path("logs/crypto_trades.jsonl")
    if not f.exists(): return []
    return [json.loads(l) for l in f.read_text().strip().split("\n") if l.strip()]


def load_watchlist():
    f = Path("logs/watchlist.json")
    if not f.exists(): return []
    try: return json.loads(f.read_text())
    except: return []


def fmt_pnl(v):
    s = f"+${v:.2f}" if v >= 0 else f"-${abs(v):.2f}"
    c = "#2ecc71" if v >= 0 else "#e74c3c"
    return s, c


def build_page():
    # --- Live Alpaca data ---
    acct      = alpaca("/v2/account")
    positions = alpaca("/v2/positions") or []
    orders    = alpaca("/v2/orders?status=open&limit=10") or []

    port_val    = float(acct.get("portfolio_value", 0))
    cash        = float(acct.get("cash", 0))
    day_pnl     = float(acct.get("equity", port_val)) - float(acct.get("last_equity", port_val))
    invested    = sum(float(p.get("market_value", 0)) for p in positions)

    # --- Trade log ---
    records  = load_logs()
    trades   = [r for r in records if r["event"] == "close"]
    signals  = [r for r in records if r["event"] == "signal"]
    wins     = [t for t in trades if t["outcome"] == "win"]
    losses   = [t for t in trades if t["outcome"] == "loss"]
    total_pnl = sum(t["pnl"] for t in trades)
    win_rate  = round(len(wins)/len(trades)*100, 1) if trades else 0

    # Equity curve
    eq, eq_labels, eq_vals = 0, [], []
    for t in trades:
        eq += t["pnl"]
        eq_labels.append(t["ts"][:16])
        eq_vals.append(round(eq, 2))

    # Kill switch
    killed = any(r["event"] == "kill_switch" for r in records)
    status_color = "#e74c3c" if killed else "#2ecc71"
    status_text  = "KILL SWITCH — HALTED" if killed else "● LIVE"

    dpnl_s, dpnl_c = fmt_pnl(day_pnl)
    tpnl_s, tpnl_c = fmt_pnl(total_pnl)

    # --- Open positions rows ---
    pos_rows = ""
    if positions:
        for p in positions:
            unrl  = float(p.get("unrealized_pl", 0))
            ps, pc = fmt_pnl(unrl)
            side  = p.get("side","").upper()
            qty   = p.get("qty","")
            sym   = p.get("symbol","")
            price = float(p.get("current_price", 0))
            avg   = float(p.get("avg_entry_price", 0))
            pos_rows += f"""<tr>
                <td><b>{sym}</b></td><td>{side}</td><td>{qty}</td>
                <td>${avg:.2f}</td><td>${price:.2f}</td>
                <td style="color:{pc};font-weight:bold">{ps}</td>
            </tr>"""
    else:
        pos_rows = '<tr><td colspan="6" style="text-align:center;color:#8b949e;padding:16px">No open positions</td></tr>'

    # --- Open orders rows ---
    ord_rows = ""
    if orders:
        for o in orders:
            sym  = o.get("symbol","")
            side = o.get("side","").upper()
            qty  = o.get("qty","")
            lp   = o.get("limit_price","—")
            typ  = o.get("type","")
            ord_rows += f"<tr><td><b>{sym}</b></td><td>{side}</td><td>{qty}</td><td>{typ}</td><td>${lp}</td></tr>"
    else:
        ord_rows = '<tr><td colspan="5" style="text-align:center;color:#8b949e;padding:12px">No pending orders</td></tr>'

    # --- Watchlist (upcoming FVG zones) ---
    watchlist = load_watchlist()
    watch_rows = ""
    if watchlist:
        for w in watchlist:
            dist_s = f"{w.get('dist_pct',0):.2f}%"
            dc     = "#f39c12" if abs(w.get('dist_pct',99)) < 0.5 else "#8b949e"
            watch_rows += f"""<tr>
                <td><b>{w.get('symbol','')}</b></td>
                <td style="color:{'#2ecc71' if w.get('direction')=='bull' else '#e74c3c'}">{w.get('direction','').upper()}</td>
                <td>${w.get('bot',0):.2f} – ${w.get('top',0):.2f}</td>
                <td style="color:{dc}">{dist_s} away</td>
                <td>{w.get('mss_dir','—').upper()}</td>
            </tr>"""
    else:
        watch_rows = '<tr><td colspan="5" style="text-align:center;color:#8b949e;padding:12px">Scanning for FVG zones...</td></tr>'

    # --- Recent signals ---
    recent_sigs = signals[-8:][::-1]
    sig_rows = ""
    for s in recent_sigs:
        d = s.get("direction","").upper()
        dc = "#2ecc71" if d == "LONG" else "#e74c3c"
        sig_rows += f"""<tr>
            <td>{s.get('ts','')[:16]}</td>
            <td><b>{s.get('symbol','')}</b></td>
            <td style="color:{dc}">{d}</td>
            <td>${s.get('entry',0):.2f}</td>
            <td style="color:#e74c3c">${s.get('stop_loss',0):.2f}</td>
            <td style="color:#2ecc71">${s.get('take_profit',0):.2f}</td>
        </tr>"""
    if not sig_rows:
        sig_rows = '<tr><td colspan="6" style="text-align:center;color:#8b949e;padding:12px">No signals yet today</td></tr>'

    # --- Recent closed trades ---
    recent_trades = trades[-10:][::-1]
    trade_rows = ""
    for t in recent_trades:
        oc = "#2ecc71" if t["outcome"] == "win" else "#e74c3c"
        ps, pc = fmt_pnl(t["pnl"])
        trade_rows += f"""<tr>
            <td>{t.get('ts','')[:16]}</td>
            <td><b>{t.get('symbol','')}</b></td>
            <td>{t.get('direction','').upper()}</td>
            <td style="color:{oc};font-weight:bold">{t['outcome'].upper()}</td>
            <td style="color:{pc}">{ps}</td>
        </tr>"""
    if not trade_rows:
        trade_rows = '<tr><td colspan="5" style="text-align:center;color:#8b949e;padding:16px">No closed trades yet</td></tr>'

    # --- Crypto section ---
    crypto_records = load_crypto_logs()
    c_trades  = [r for r in crypto_records if r["event"] == "close"]
    c_signals = [r for r in crypto_records if r["event"] == "signal"]
    c_wins    = [t for t in c_trades if t.get("outcome") == "win"]
    c_losses  = [t for t in c_trades if t.get("outcome") == "loss"]
    c_pnl     = sum(t.get("pnl", 0) for t in c_trades)
    c_wr      = round(len(c_wins)/len(c_trades)*100,1) if c_trades else 0
    c_pnl_s, c_pnl_c = fmt_pnl(c_pnl)

    crypto_positions = [p for p in positions
                        if any(p.get("symbol","").startswith(c) for c in ["BTC","ETH","SOL"])]

    c_pos_rows = ""
    for p in crypto_positions:
        unrl = float(p.get("unrealized_pl",0))
        ps,pc = fmt_pnl(unrl)
        c_pos_rows += f"<tr><td><b>{p.get('symbol')}</b></td><td>{p.get('side','').upper()}</td><td>${float(p.get('market_value',0)):,.2f}</td><td style='color:{pc}'>{ps}</td></tr>"
    if not c_pos_rows:
        c_pos_rows = '<tr><td colspan="4" style="text-align:center;color:#8b949e;padding:12px">No open crypto positions</td></tr>'

    c_sig_rows = ""
    for s in c_signals[-6:][::-1]:
        dc = "#2ecc71" if s.get("direction")=="long" else "#e74c3c"
        c_sig_rows += f"<tr><td>{s.get('ts','')[:16]}</td><td><b>{s.get('symbol','')}</b></td><td style='color:{dc}'>{s.get('direction','').upper()}</td><td>${s.get('entry',0):,.2f}</td><td>${s.get('notional',0):.0f} notional</td></tr>"
    if not c_sig_rows:
        c_sig_rows = '<tr><td colspan="5" style="text-align:center;color:#8b949e;padding:12px">No crypto signals yet</td></tr>'

    # Crypto equity curve
    ceq, ceq_labels, ceq_vals = 0, [], []
    for t in c_trades:
        ceq += t.get("pnl",0)
        ceq_labels.append(t["ts"][:16])
        ceq_vals.append(round(ceq,2))

    eq_labels_js  = json.dumps(eq_labels)
    eq_vals_js    = json.dumps(eq_vals)
    ceq_labels_js = json.dumps(ceq_labels)
    ceq_vals_js   = json.dumps(ceq_vals)
    now           = datetime.now().strftime("%b %d %I:%M:%S %p")

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SMC Bot</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d1117;color:#e6edf3;font-family:system-ui,sans-serif;padding:12px;font-size:14px}}
h2{{font-size:1rem;color:#8b949e;margin:16px 0 8px;text-transform:uppercase;letter-spacing:.05em}}
h1{{font-size:1.2rem;color:#58a6ff;margin-bottom:4px}}
.topbar{{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px}}
.status{{padding:4px 12px;border-radius:20px;background:{status_color}22;color:{status_color};
  border:1px solid {status_color};font-size:.8rem;font-weight:bold}}
.refresh{{color:#8b949e;font-size:.75rem}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:4px}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;text-align:center}}
.card .val{{font-size:1.5rem;font-weight:bold;margin:4px 0}}
.card .lbl{{font-size:.7rem;color:#8b949e;text-transform:uppercase}}
.chart-box{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;height:200px;margin-bottom:4px}}
table{{width:100%;border-collapse:collapse;background:#161b22;border:1px solid #30363d;
  border-radius:8px;overflow:hidden;margin-bottom:4px}}
th{{background:#21262d;padding:9px 10px;text-align:left;color:#8b949e;font-size:.75rem;text-transform:uppercase}}
td{{padding:9px 10px;border-top:1px solid #21262d;font-size:.85rem}}
.sect{{margin-bottom:16px}}
a{{color:#58a6ff}}
@media(max-width:500px){{.card .val{{font-size:1.2rem}}td,th{{padding:7px 8px;font-size:.78rem}}}}
</style>
</head><body>

<div class="topbar">
  <div><h1>SMC Bot — Paper Trading</h1>
  <span class="refresh">Updated {now} · <a href="/">Refresh</a></span></div>
  <div class="status">{status_text}</div>
</div>

<div class="grid">
  <div class="card"><div class="val">${port_val:,.2f}</div><div class="lbl">Account Value</div></div>
  <div class="card"><div class="val" style="color:{dpnl_c}">{dpnl_s}</div><div class="lbl">Today's P&amp;L</div></div>
  <div class="card"><div class="val" style="color:{tpnl_c}">{tpnl_s}</div><div class="lbl">Total P&amp;L</div></div>
  <div class="card"><div class="val">${invested:,.2f}</div><div class="lbl">Invested</div></div>
  <div class="card"><div class="val">{win_rate}%</div><div class="lbl">Win Rate</div></div>
  <div class="card"><div class="val">{len(trades)}</div><div class="lbl">Total Trades</div></div>
</div>

<div class="sect">
<h2>Equity Curve</h2>
<div class="chart-box"><canvas id="eq"></canvas></div>
</div>

<div class="sect">
<h2>Open Positions ({len(positions)})</h2>
<table><thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Avg Entry</th><th>Price</th><th>Unreal P&amp;L</th></tr></thead>
<tbody>{pos_rows}</tbody></table>
</div>

<div class="sect">
<h2>Upcoming FVG Zones Being Watched</h2>
<table><thead><tr><th>Symbol</th><th>Direction</th><th>Zone</th><th>Distance</th><th>M5 Bias</th></tr></thead>
<tbody>{watch_rows}</tbody></table>
</div>

<div class="sect">
<h2>Pending Orders ({len(orders)})</h2>
<table><thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Type</th><th>Limit</th></tr></thead>
<tbody>{ord_rows}</tbody></table>
</div>

<div class="sect">
<h2>Recent Signals</h2>
<table><thead><tr><th>Time</th><th>Symbol</th><th>Dir</th><th>Entry</th><th>Stop</th><th>Target</th></tr></thead>
<tbody>{sig_rows}</tbody></table>
</div>

<div class="sect">
<h2>Trade History — Stocks</h2>
<table><thead><tr><th>Time</th><th>Symbol</th><th>Dir</th><th>Result</th><th>P&amp;L</th></tr></thead>
<tbody>{trade_rows}</tbody></table>
</div>

<hr style="border-color:#30363d;margin:24px 0">

<div class="sect">
<h2 style="color:#f39c12">Crypto Trading — BTC / ETH (24/7)</h2>
<div class="grid" style="margin-bottom:12px">
  <div class="card"><div class="val" style="color:{c_pnl_c}">{c_pnl_s}</div><div class="lbl">Crypto P&amp;L</div></div>
  <div class="card"><div class="val">{c_wr}%</div><div class="lbl">Crypto Win Rate</div></div>
  <div class="card"><div class="val">{len(c_trades)}</div><div class="lbl">Crypto Trades</div></div>
  <div class="card"><div class="val">{len(c_signals)}</div><div class="lbl">Crypto Signals</div></div>
</div>
<div class="chart-box" style="height:160px"><canvas id="ceq"></canvas></div>
</div>

<div class="sect">
<h2>Crypto Positions</h2>
<table><thead><tr><th>Symbol</th><th>Side</th><th>Value</th><th>Unreal P&amp;L</th></tr></thead>
<tbody>{c_pos_rows}</tbody></table>
</div>

<div class="sect">
<h2>Crypto Signals</h2>
<table><thead><tr><th>Time</th><th>Symbol</th><th>Dir</th><th>Entry</th><th>Size</th></tr></thead>
<tbody>{c_sig_rows}</tbody></table>
</div>

<script>
new Chart(document.getElementById('eq'),{{
  type:'line',
  data:{{labels:{eq_labels_js},datasets:[{{
    label:'P&L ($)',data:{eq_vals_js},
    borderColor:'#58a6ff',backgroundColor:'#58a6ff18',
    fill:true,tension:0.3,pointRadius:2,borderWidth:2
  }}]}},
  options:{{responsive:true,maintainAspectRatio:false,
    plugins:{{legend:{{display:false}}}},
    scales:{{
      x:{{ticks:{{color:'#8b949e',maxTicksLimit:5}},grid:{{color:'#21262d'}}}},
      y:{{ticks:{{color:'#8b949e',callback:v=>'$'+v}},grid:{{color:'#21262d'}}}}
    }}
  }}
}});
new Chart(document.getElementById('ceq'),{{
  type:'line',
  data:{{labels:{ceq_labels_js},datasets:[{{
    label:'Crypto P&L ($)',data:{ceq_vals_js},
    borderColor:'#f39c12',backgroundColor:'#f39c1218',
    fill:true,tension:0.3,pointRadius:2,borderWidth:2
  }}]}},
  options:{{responsive:true,maintainAspectRatio:false,
    plugins:{{legend:{{display:false}}}},
    scales:{{
      x:{{ticks:{{color:'#8b949e',maxTicksLimit:4}},grid:{{color:'#21262d'}}}},
      y:{{ticks:{{color:'#8b949e',callback:v=>'$'+v}},grid:{{color:'#21262d'}}}}
    }}
  }}
}});
setTimeout(()=>location.reload(), 15000);
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        html = build_page().encode()
        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length", len(html))
        self.end_headers()
        self.wfile.write(html)
    def log_message(self,*a): pass


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Dashboard: http://localhost:{PORT}")
    server.serve_forever()
