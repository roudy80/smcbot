"""
Lightweight web dashboard — open in any browser on any device.
Shows live trade log, equity curve, and bot status.
Run: python dashboard.py  (then open http://localhost:5050)
"""

import json
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from logger import load_all

PORT = 5050


def build_metrics(records):
    trades   = [r for r in records if r["event"] == "close"]
    signals  = [r for r in records if r["event"] == "signal"]
    killed   = any(r["event"] == "kill_switch" for r in records)
    wins     = [t for t in trades if t["outcome"] == "win"]
    losses   = [t for t in trades if t["outcome"] == "loss"]
    pnl      = sum(t["pnl"] for t in trades)
    win_rate = round(len(wins) / len(trades) * 100, 1) if trades else 0
    return {
        "signals": len(signals), "trades": len(trades),
        "wins": len(wins), "losses": len(losses),
        "win_rate": win_rate, "pnl": round(pnl, 2),
        "killed": killed,
    }


def build_equity(records):
    trades = [r for r in records if r["event"] == "close"]
    equity, points = 0, []
    for t in trades:
        equity += t["pnl"]
        points.append({"ts": t["ts"][:16], "equity": round(equity, 2)})
    return points


def render_html(records):
    m  = build_metrics(records)
    eq = build_equity(records)
    trades = [r for r in records if r["event"] == "close"][-20:][::-1]

    status_color = "#e74c3c" if m["killed"] else "#2ecc71"
    status_text  = "KILL SWITCH FIRED" if m["killed"] else "RUNNING"
    pnl_color    = "#2ecc71" if m["pnl"] >= 0 else "#e74c3c"
    pnl_str      = f"+${m['pnl']:.2f}" if m["pnl"] >= 0 else f"-${abs(m['pnl']):.2f}"

    eq_labels = json.dumps([p["ts"]    for p in eq])
    eq_values = json.dumps([p["equity"] for p in eq])

    rows = ""
    for t in trades:
        color  = "#2ecc71" if t["outcome"] == "win" else "#e74c3c"
        pnl_s  = f"+${t['pnl']:.2f}" if t["pnl"] >= 0 else f"-${abs(t['pnl']):.2f}"
        rows  += f"""<tr>
            <td>{t['ts'][:16]}</td>
            <td>{t.get('symbol','—')}</td>
            <td>{t.get('direction','—').upper()}</td>
            <td style="color:{color};font-weight:bold">{t['outcome'].upper()}</td>
            <td style="color:{color}">{pnl_s}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SMC Bot Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0d1117;color:#e6edf3;font-family:system-ui,sans-serif;padding:16px}}
  h1{{font-size:1.4rem;margin-bottom:16px;color:#58a6ff}}
  .status{{display:inline-block;padding:4px 12px;border-radius:20px;
    background:{status_color}22;color:{status_color};font-weight:bold;
    border:1px solid {status_color};margin-bottom:16px;font-size:0.85rem}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:20px}}
  .card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;text-align:center}}
  .card .val{{font-size:1.8rem;font-weight:bold;margin:4px 0}}
  .card .lbl{{font-size:0.75rem;color:#8b949e;text-transform:uppercase}}
  .chart-box{{background:#161b22;border:1px solid #30363d;border-radius:8px;
    padding:16px;margin-bottom:20px;height:220px}}
  table{{width:100%;border-collapse:collapse;background:#161b22;
    border:1px solid #30363d;border-radius:8px;overflow:hidden;font-size:0.85rem}}
  th{{background:#21262d;padding:10px;text-align:left;color:#8b949e;font-weight:600}}
  td{{padding:10px;border-top:1px solid #21262d}}
  .refresh{{color:#8b949e;font-size:0.75rem;margin-bottom:12px}}
  @media(max-width:480px){{.card .val{{font-size:1.4rem}}}}
</style>
</head><body>
<h1>SMC Bot — Paper Trading</h1>
<div class="status">● {status_text}</div>
<p class="refresh">Last updated: {datetime.now().strftime('%H:%M:%S')} · <a href="/" style="color:#58a6ff">Refresh</a></p>

<div class="grid">
  <div class="card"><div class="val">{m['signals']}</div><div class="lbl">Signals</div></div>
  <div class="card"><div class="val">{m['trades']}</div><div class="lbl">Trades</div></div>
  <div class="card"><div class="val">{m['win_rate']}%</div><div class="lbl">Win Rate</div></div>
  <div class="card"><div class="val" style="color:{pnl_color}">{pnl_str}</div><div class="lbl">P&amp;L</div></div>
  <div class="card"><div class="val" style="color:#2ecc71">{m['wins']}</div><div class="lbl">Wins</div></div>
  <div class="card"><div class="val" style="color:#e74c3c">{m['losses']}</div><div class="lbl">Losses</div></div>
</div>

<div class="chart-box">
  <canvas id="eq"></canvas>
</div>

<table>
  <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Result</th><th>P&amp;L</th></tr></thead>
  <tbody>{rows if rows else '<tr><td colspan="5" style="text-align:center;color:#8b949e;padding:24px">No trades yet</td></tr>'}</tbody>
</table>

<script>
new Chart(document.getElementById('eq'),{{
  type:'line',
  data:{{
    labels:{eq_labels},
    datasets:[{{
      label:'Equity ($)',
      data:{eq_values},
      borderColor:'#58a6ff',
      backgroundColor:'#58a6ff22',
      fill:true,
      tension:0.3,
      pointRadius:2
    }}]
  }},
  options:{{
    responsive:true,maintainAspectRatio:false,
    plugins:{{legend:{{display:false}}}},
    scales:{{
      x:{{ticks:{{color:'#8b949e',maxTicksLimit:6}},grid:{{color:'#21262d'}}}},
      y:{{ticks:{{color:'#8b949e'}},grid:{{color:'#21262d'}}}}
    }}
  }}
}});
// Auto-refresh every 30 seconds
setTimeout(()=>location.reload(), 30000);
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        records = load_all()
        html    = render_html(records).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", len(html))
        self.end_headers()
        self.wfile.write(html)

    def log_message(self, *args):
        pass  # suppress noisy access logs


def main():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Dashboard running at http://localhost:{PORT}")
    print("Open that URL in your browser. Refreshes every 30 seconds.")
    print("Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
