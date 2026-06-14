"""Monitoring endpoints: Prometheus metrics (no deps) + HTML dashboard."""

from __future__ import annotations

import time
from typing import Any

_METRICS: dict[str, Any] = {}
_start_time = time.time()


def record_metric(
    name: str,
    value: float,
    labels: dict[str, str] | None = None,
    help_text: str = "",
    metric_type: str = "gauge",
) -> None:
    """Record a metric value for Prometheus exposition."""
    key = (name, tuple(sorted(labels.items())) if labels else ())
    _METRICS[key] = {
        "name": name,
        "value": value,
        "labels": labels or {},
        "help": help_text,
        "type": metric_type,
    }


def collect_metrics_text() -> str:
    """Render collected metrics in Prometheus exposition format."""
    lines: list[str] = []
    seen_help: set[str] = set()
    for key, rec in sorted(_METRICS.items(), key=lambda x: x[0][0]):
        name = rec["name"]
        if name not in seen_help and rec["help"]:
            lines.append(f"# HELP {name} {rec['help']}")
            lines.append(f"# TYPE {name} {rec['type']}")
            seen_help.add(name)
        label_str = ""
        if rec["labels"]:
            parts = [f'{k}="{v}"' for k, v in sorted(rec["labels"].items())]
            label_str = "{" + ",".join(parts) + "}"
        lines.append(f"{name}{label_str} {rec['value']}")
    lines.append("# HELP process_uptime_seconds Process uptime in seconds")
    lines.append("# TYPE process_uptime_seconds gauge")
    lines.append(f"process_uptime_seconds {time.time() - _start_time}")
    return "\n".join(lines) + "\n"


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Energy-Aware Task Router — Dashboard</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0d1117;color:#c9d1d9;padding:2rem}
  h1{font-size:1.5rem;margin-bottom:.5rem;color:#58a6ff}
  .status{display:inline-block;padding:.25rem .75rem;border-radius:999px;font-size:.8rem;font-weight:600}
  .status.healthy{background:#238636;color:#fff}
  .status.degraded{background:#d29922;color:#fff}
  .status.unhealthy{background:#da3633;color:#fff}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem;margin-top:1.5rem}
  .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1.25rem}
  .card h2{font-size:.9rem;text-transform:uppercase;color:#8b949e;letter-spacing:.05em;margin-bottom:.75rem}
  .card .value{font-size:2rem;font-weight:700;color:#f0f6fc}
  .card .sub{font-size:.8rem;color:#8b949e;margin-top:.25rem}
  .table{width:100%;border-collapse:collapse;margin-top:1rem}
  .table th,.table td{text-align:left;padding:.5rem .75rem;border-bottom:1px solid #21262d;font-size:.85rem}
  .table th{color:#8b949e;font-weight:600;text-transform:uppercase;font-size:.75rem}
  .badge{display:inline-block;padding:.15rem .5rem;border-radius:999px;font-size:.75rem}
  .badge.ok{background:#238636;color:#fff}
  .badge.error{background:#da3633;color:#fff}
  .badge.degraded{background:#d29922;color:#fff}
  .meta{margin-top:.5rem;font-size:.8rem;color:#484f58}
  .refresh{margin-top:1rem;font-size:.8rem;color:#484f58}
  .error-state{color:#f85149;padding:1rem}
</style>
</head>
<body>
<h1>&#9889; Energy-Aware Task Router</h1>
<div id="app">
  <div class="status" id="overall-status" data-status="loading">Loading...</div>
  <div class="grid" id="cards"></div>
  <table class="table" id="components-table">
    <thead><tr><th>Component</th><th>Status</th><th>Detail</th></tr></thead>
    <tbody id="components-body"></tbody>
  </table>
  <div class="meta" id="meta"></div>
</div>
<div class="refresh" id="refresh-note">Auto-refreshing every 30s</div>
<script>
async function refresh(){
  try{
    const r=await fetch('/health');const d=await r.json();
    const s=d.status||'unknown';
    const el=document.getElementById('overall-status');
    el.textContent=s.toUpperCase();el.className='status '+s;
    const cards=document.getElementById('cards');cards.innerHTML='';
    const cardData=[
      ['Version',d.version,''],
      ['Uptime',(d.uptime_seconds?Math.floor(d.uptime_seconds)+'s':'-'),''],
      ['Components',Object.keys(d.components||{}).length+' tracked',''],
    ];
    cardData.forEach(([label,val,sub])=>{
      const c=document.createElement('div');c.className='card';
      c.innerHTML='<h2>'+label+'</h2><div class="value">'+val+'</div>'+(sub?'<div class="sub">'+sub+'</div>':'');
      cards.appendChild(c);
    });
    const tb=document.getElementById('components-body');tb.innerHTML='';
    for(const[comp,info]of Object.entries(d.components||{})){
      const tr=document.createElement('tr');
      const st=info.status||'unknown';
      tr.innerHTML='<td>'+comp+'</td><td><span class="badge '+st+'">'+st+'</span></td><td>'+(info.detail||'')+'</td>';
      tb.appendChild(tr);
    }
    const m=document.getElementById('meta');
    m.textContent='Last updated: '+new Date().toLocaleString();
  }catch(e){
    document.getElementById('app').innerHTML='<div class="error-state">&#9888; Failed to fetch health data: '+e.message+'</div>';
  }
}
refresh();setInterval(refresh,30000);
</script>
</body>
</html>
"""


def dashboard_html() -> str:
    """Return the dashboard HTML page."""
    return DASHBOARD_HTML
