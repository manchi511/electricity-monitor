#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电费消耗曲线可视化仪表盘生成器
从 query_log.json 读取历史数据，生成交互式 HTML 仪表盘
"""

import json
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "query_log.json"
OUTPUT_FILE = SCRIPT_DIR / "dashboard.html"


def load_history() -> list:
    if not LOG_FILE.exists():
        return []
    try:
        data = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def compute_stats(history: list) -> dict:
    """计算统计数据"""
    if not history:
        return {
            "total_queries": 0,
            "avg_daily_consumption": 0,
            "estimated_days": 0,
            "max_power": 0,
            "min_power": 0,
            "total_consumed": 0,
        }

    valid = [h for h in history if h.get("power_num") is not None]
    if not valid:
        return {"total_queries": len(history), "avg_daily_consumption": 0, "estimated_days": 0,
                "max_power": 0, "min_power": 0, "total_consumed": 0}

    # 按时间排序
    valid.sort(key=lambda x: x["time"])

    max_power = max(h["power_num"] for h in valid)
    min_power = min(h["power_num"] for h in valid)

    # 按天汇总：每次查询间的消耗量归入查询发生的当天
    daily_map = {}
    prev_power = None
    for h in valid:
        dt = datetime.strptime(h["time"][:19] if len(h["time"]) >= 19 else h["time"][:16],
                               "%Y-%m-%d %H:%M:%S" if len(h["time"]) >= 19 else "%Y-%m-%d %H:%M")
        curr_date = dt.strftime("%Y-%m-%d")
        if prev_power is not None:
            diff = prev_power - h["power_num"]
            if diff > 0:
                if curr_date not in daily_map:
                    daily_map[curr_date] = 0
                daily_map[curr_date] += diff
        prev_power = h["power_num"]

    # 计算日均用电：用总消耗 / 跨越天数（更准确）
    first_dt = datetime.strptime(valid[0]["time"][:19] if len(valid[0]["time"]) >= 19 else valid[0]["time"][:16],
                                  "%Y-%m-%d %H:%M:%S" if len(valid[0]["time"]) >= 19 else "%Y-%m-%d %H:%M")
    last_dt = datetime.strptime(valid[-1]["time"][:19] if len(valid[-1]["time"]) >= 19 else valid[-1]["time"][:16],
                                 "%Y-%m-%d %H:%M:%S" if len(valid[-1]["time"]) >= 19 else "%Y-%m-%d %H:%M")
    total_consumed_val = valid[0]["power_num"] - valid[-1]["power_num"]
    if total_consumed_val < 0:
        total_consumed_val = 0  # 可能中间有充值

    days_span = (last_dt - first_dt).total_seconds() / 86400
    if days_span >= 1 and total_consumed_val > 0:
        avg_daily = total_consumed_val / days_span
    elif daily_map:
        avg_daily = sum(daily_map.values()) / len(daily_map)
    else:
        avg_daily = 0

    # 预估剩余天数
    latest = valid[-1]
    estimated_days = int(latest["power_num"] / avg_daily) if avg_daily > 0 else 0

    return {
        "total_queries": len(history),
        "avg_daily_consumption": round(avg_daily, 2),
        "estimated_days": estimated_days,
        "max_power": round(max_power, 2),
        "min_power": round(min_power, 2),
        "total_consumed": round(total_consumed_val, 2),
        "daily_map": daily_map,
    }


def generate_html(history: list, stats: dict) -> str:
    """生成完整的 HTML 仪表盘"""

    # 准备图表数据
    labels = []
    power_data = []
    balance_data = []
    consumption_data = []  # 每次查询间的消耗

    prev_power = None
    for h in history:
        time_str = h.get("time", "")
        # 简化时间显示
        short_time = time_str[5:16] if len(time_str) >= 16 else time_str  # MM-DD HH:MM
        labels.append(short_time)

        p = h.get("power_num")
        b = h.get("balance_num")
        power_data.append(p)
        balance_data.append(b)

        if prev_power is not None and p is not None:
            consumed = round(prev_power - p, 2)
            consumption_data.append(consumed if consumed > 0 else 0)
        else:
            consumption_data.append(0)
        prev_power = p

    # 最新数据
    latest = history[-1] if history else {}
    current_power = latest.get("power_num", 0)
    current_balance = latest.get("balance_num", 0)
    current_subsidy = latest.get("subsidy_num", 0)
    current_power_raw = latest.get("power_raw", "—")
    current_balance_raw = latest.get("balance_raw", "—")
    current_subsidy_raw = latest.get("subsidy_raw", "—")
    room = latest.get("custRechNo", "—")
    query_time = latest.get("time", "—")

    # 状态判断
    power_status = "normal" if current_power and current_power >= 20 else "warning"
    balance_status = "normal" if current_balance and current_balance >= 10 else "warning"

    # 每日消耗数据
    daily_map = stats.get("daily_map", {})
    daily_labels = list(daily_map.keys())
    daily_values = [round(v, 2) for v in daily_map.values()]

    # JSON 数据
    chart_labels = json.dumps(labels, ensure_ascii=False)
    chart_power = json.dumps(power_data)
    chart_balance = json.dumps(balance_data)
    chart_consumption = json.dumps(consumption_data)
    chart_daily_labels = json.dumps(daily_labels, ensure_ascii=False)
    chart_daily_values = json.dumps(daily_values)

    avg_daily = stats.get("avg_daily_consumption", 0)
    estimated_days = stats.get("estimated_days", 0)
    total_consumed = stats.get("total_consumed", 0)
    total_queries = stats.get("total_queries", 0)
    max_power = stats.get("max_power", 0)
    min_power = stats.get("min_power", 0)

    power_pct = min(current_power or 0, 100)
    balance_pct = min((current_balance or 0) * 2, 100)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="theme-color" content="#667eea">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="电费监控">
<link rel="manifest" href="./manifest.json">
<link rel="apple-touch-icon" href="./icons/apple-touch-icon.png">
<link rel="icon" type="image/png" href="./icons/icon-192.png">
<title>⚡ 电费监控 - {room}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', sans-serif;
    background: #f0f2f5;
    color: #1a1a2e;
    min-height: 100vh;
  }}

  /* 顶部导航 */
  .nav {{
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    padding: 20px 32px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    box-shadow: 0 2px 12px rgba(0,0,0,0.15);
  }}
  .nav-left {{ display: flex; align-items: center; gap: 12px; }}
  .nav-logo {{ font-size: 28px; }}
  .nav-title {{ color: #fff; font-size: 22px; font-weight: 700; }}
  .nav-sub {{ color: rgba(255,255,255,0.7); font-size: 13px; margin-top: 2px; }}
  .nav-right {{ text-align: right; color: rgba(255,255,255,0.9); }}
  .nav-time {{ font-size: 14px; }}
  .nav-room {{ font-size: 13px; opacity: 0.7; }}

  /* 警告横幅 */
  .banner {{
    padding: 12px 32px;
    text-align: center;
    font-size: 14px;
    font-weight: 600;
    display: none;
  }}
  .banner.warn {{ background: #fff3cd; color: #856404; border-bottom: 1px solid #ffeaa7; display: block; }}
  .banner.danger {{ background: #f8d7da; color: #721c24; border-bottom: 1px solid #f5c6cb; display: block; }}

  /* 主体 */
  .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}

  /* 卡片行 */
  .card-row {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-bottom: 24px; }}

  .card {{
    background: #fff;
    border-radius: 16px;
    padding: 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    transition: transform 0.2s, box-shadow 0.2s;
  }}
  .card:hover {{ transform: translateY(-2px); box-shadow: 0 4px 16px rgba(0,0,0,0.12); }}

  .card-label {{ font-size: 14px; color: #6b7280; margin-bottom: 8px; }}
  .card-value {{ font-size: 42px; font-weight: 800; line-height: 1.1; }}
  .card-value.green {{ color: #22c55e; }}
  .card-value.blue {{ color: #3b82f6; }}
  .card-value.orange {{ color: #f59e0b; }}
  .card-value.red {{ color: #ef4444; }}

  .card-bar {{
    margin-top: 12px;
    height: 8px;
    background: #f1f5f9;
    border-radius: 4px;
    overflow: hidden;
  }}
  .card-bar-fill {{
    height: 100%;
    border-radius: 4px;
    transition: width 0.6s ease;
  }}

  .card-tag {{
    margin-top: 8px;
    font-size: 12px;
    font-weight: 600;
  }}
  .card-tag.ok {{ color: #22c55e; }}
  .card-tag.warn {{ color: #ef4444; }}

  /* 统计行 */
  .stats-row {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 24px;
  }}
  .stat-item {{
    background: #fff;
    border-radius: 12px;
    padding: 18px;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }}
  .stat-label {{ font-size: 12px; color: #9ca3af; margin-bottom: 6px; }}
  .stat-value {{ font-size: 24px; font-weight: 700; color: #1a1a2e; }}
  .stat-unit {{ font-size: 13px; color: #9ca3af; font-weight: 400; }}

  /* 图表容器 */
  .chart-container {{
    background: #fff;
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }}
  .chart-title {{
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .chart-wrapper {{
    position: relative;
    height: 320px;
  }}

  .chart-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 24px;
  }}

  /* 历史表格 */
  .table-container {{
    background: #fff;
    border-radius: 16px;
    padding: 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }}
  .table-title {{
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 16px;
  }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ text-align: left; padding: 10px 12px; font-size: 13px; color: #6b7280; border-bottom: 2px solid #f0f2f5; }}
  td {{ padding: 10px 12px; font-size: 14px; border-bottom: 1px solid #f0f2f5; }}
  tr:hover td {{ background: #f8f9fc; }}
  .td-power {{ font-weight: 600; }}
  .consumed {{ color: #ef4444; font-weight: 600; }}

  /* 响应式 */
  @media (max-width: 768px) {{
    .card-row, .stats-row, .chart-grid {{ grid-template-columns: 1fr; }}
    .nav {{ flex-direction: column; gap: 8px; text-align: center; }}
  }}

  /* 刷新提示 */
  .footer {{
    text-align: center;
    padding: 16px;
    color: #9ca3af;
    font-size: 12px;
  }}

  /* 刷新按钮 */
  .refresh-btn {{
    background: rgba(255,255,255,0.2);
    border: 1px solid rgba(255,255,255,0.3);
    color: #fff;
    padding: 8px 18px;
    border-radius: 20px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-top: 6px;
  }}
  .refresh-btn:hover {{ background: rgba(255,255,255,0.3); }}
  .refresh-btn:active {{ transform: scale(0.95); }}
  .refresh-btn.loading {{ opacity: 0.6; pointer-events: none; }}
  .refresh-btn .spinner {{
    display: inline-block;
    width: 14px; height: 14px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
  }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}

  /* 刷新成功提示 */
  .toast {{
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%) translateY(100px);
    background: #1a1a2e;
    color: #fff;
    padding: 12px 28px;
    border-radius: 24px;
    font-size: 14px;
    font-weight: 600;
    box-shadow: 0 4px 20px rgba(0,0,0,0.2);
    transition: transform 0.3s ease;
    z-index: 9999;
  }}
  .toast.show {{ transform: translateX(-50%) translateY(0); }}
</style>
</head>
<body>

<!-- 顶部导航 -->
<div class="nav">
  <div class="nav-left">
    <span class="nav-logo">⚡</span>
    <div>
      <div class="nav-title">电费监控仪表盘</div>
      <div class="nav-sub">大连东软信息学院 · 软件园校区三期</div>
    </div>
  </div>
  <div class="nav-right">
    <div class="nav-time">🕐 {query_time}</div>
    <div class="nav-room">🏠 {room}</div>
    <button class="refresh-btn" id="refreshBtn" onclick="handleRefresh()">
      <span id="refreshIcon">🔄</span> <span id="refreshText">刷新查询</span>
    </button>
  </div>
</div>

<!-- 警告横幅 -->
{'<div class="banner danger">⚠️ 电量仅剩 ' + current_power_raw + '，余额仅剩 ' + current_balance_raw + '，请尽快充值！</div>' if power_status == 'warning' and balance_status == 'warning' else '<div class="banner warn">⚠️ ' + ('电量偏低' if power_status == 'warning' else '') + (' · 余额偏低' if balance_status == 'warning' else '') + '，请关注！</div>' if power_status == 'warning' or balance_status == 'warning' else ''}

<div class="container">
  <!-- 三张主数据卡片 -->
  <div class="card-row">
    <div class="card">
      <div class="card-label">⚡ 剩余电量</div>
      <div class="card-value {'green' if power_status == 'normal' else 'red'}">{current_power_raw}</div>
      <div class="card-bar">
        <div class="card-bar-fill" style="width: {power_pct}%; background: {'#22c55e' if power_status == 'normal' else '#ef4444'};"></div>
      </div>
      <div class="card-tag {'ok' if power_status == 'normal' else 'warn'}">
        {'✅ 电量充足' if power_status == 'normal' else '⚠️ 电量偏低，请充值'}
      </div>
    </div>

    <div class="card">
      <div class="card-label">💰 当前余额</div>
      <div class="card-value {'blue' if balance_status == 'normal' else 'red'}">{current_balance_raw}</div>
      <div class="card-bar">
        <div class="card-bar-fill" style="width: {balance_pct}%; background: {'#3b82f6' if balance_status == 'normal' else '#ef4444'};"></div>
      </div>
      <div class="card-tag {'ok' if balance_status == 'normal' else 'warn'}">
        {'✅ 余额正常' if balance_status == 'normal' else '⚠️ 余额偏低，请充值'}
      </div>
    </div>

    <div class="card">
      <div class="card-label">🎁 剩余补助</div>
      <div class="card-value orange">{current_subsidy_raw}</div>
      <div class="card-bar">
        <div class="card-bar-fill" style="width: {min(current_subsidy or 0, 100)}%; background: #f59e0b;"></div>
      </div>
      <div class="card-tag {'ok' if current_subsidy and current_subsidy > 0 else ''}" style="color: #9ca3af;">
        {'✅ 有补助' if current_subsidy and current_subsidy > 0 else '暂无补助'}
      </div>
    </div>
  </div>

  <!-- 统计概览 -->
  <div class="stats-row">
    <div class="stat-item">
      <div class="stat-label">📊 日均用电</div>
      <div class="stat-value">{avg_daily}<span class="stat-unit"> 度/天</span></div>
    </div>
    <div class="stat-item">
      <div class="stat-label">📅 预估可用</div>
      <div class="stat-value" style="color: {'#22c55e' if estimated_days > 3 else '#ef4444'}">{estimated_days}<span class="stat-unit"> 天</span></div>
    </div>
    <div class="stat-item">
      <div class="stat-label">⚡ 累计消耗</div>
      <div class="stat-value">{total_consumed}<span class="stat-unit"> 度</span></div>
    </div>
    <div class="stat-item">
      <div class="stat-label">📋 查询次数</div>
      <div class="stat-value">{total_queries}<span class="stat-unit"> 次</span></div>
    </div>
  </div>

  <!-- 电量消耗曲线 -->
  <div class="chart-container">
    <div class="chart-title">📉 电量消耗曲线</div>
    <div class="chart-wrapper">
      <canvas id="powerChart"></canvas>
    </div>
  </div>

  <!-- 双图：余额趋势 + 每次消耗 -->
  <div class="chart-grid">
    <div class="chart-container">
      <div class="chart-title">💰 余额变化趋势</div>
      <div class="chart-wrapper">
        <canvas id="balanceChart"></canvas>
      </div>
    </div>
    <div class="chart-container">
      <div class="chart-title">⚡ 区间用电量</div>
      <div class="chart-wrapper">
        <canvas id="consumptionChart"></canvas>
      </div>
    </div>
  </div>

  <!-- 每日消耗柱状图 -->
  <div class="chart-container">
    <div class="chart-title">📊 每日用电量统计</div>
    <div class="chart-wrapper" style="height: 260px;">
      <canvas id="dailyChart"></canvas>
    </div>
  </div>

  <!-- 历史记录表格 -->
  <div class="table-container">
    <div class="table-title">📋 历史查询记录</div>
    <table>
      <thead>
        <tr>
          <th>查询时间</th>
          <th>寝室号</th>
          <th>剩余电量</th>
          <th>当前余额</th>
          <th>区间消耗</th>
        </tr>
      </thead>
      <tbody id="historyTable">
      </tbody>
    </table>
  </div>

  <div class="footer">
    自动生成于 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} · 数据来源：大连东软信息学院电费查询系统
  </div>
</div>

<script>
const chartLabels = {chart_labels};
const powerData = {chart_power};
const balanceData = {chart_balance};
const consumptionData = {chart_consumption};
const dailyLabels = {chart_daily_labels};
const dailyValues = {chart_daily_values};

Chart.defaults.font.family = "'Microsoft YaHei', sans-serif";
Chart.defaults.color = '#6b7280';

// 电量消耗曲线
new Chart(document.getElementById('powerChart'), {{
  type: 'line',
  data: {{
    labels: chartLabels,
    datasets: [{{
      label: '剩余电量 (度)',
      data: powerData,
      borderColor: '#667eea',
      backgroundColor: 'rgba(102,126,234,0.1)',
      borderWidth: 2.5,
      fill: true,
      tension: 0.3,
      pointRadius: 4,
      pointHoverRadius: 7,
      pointBackgroundColor: '#667eea',
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: true, position: 'top' }},
      tooltip: {{
        callbacks: {{
          label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y + ' 度'
        }}
      }}
    }},
    scales: {{
      y: {{
        beginAtZero: true,
        title: {{ display: true, text: '剩余电量 (度)' }}
      }}
    }}
  }}
}});

// 余额趋势
new Chart(document.getElementById('balanceChart'), {{
  type: 'line',
  data: {{
    labels: chartLabels,
    datasets: [{{
      label: '余额 (元)',
      data: balanceData,
      borderColor: '#3b82f6',
      backgroundColor: 'rgba(59,130,246,0.1)',
      borderWidth: 2.5,
      fill: true,
      tension: 0.3,
      pointRadius: 4,
      pointHoverRadius: 7,
      pointBackgroundColor: '#3b82f6',
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: true, position: 'top' }},
      tooltip: {{
        callbacks: {{
          label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y + ' 元'
        }}
      }}
    }},
    scales: {{
      y: {{
        beginAtZero: true,
        title: {{ display: true, text: '余额 (元)' }}
      }}
    }}
  }}
}});

// 区间消耗
new Chart(document.getElementById('consumptionChart'), {{
  type: 'bar',
  data: {{
    labels: chartLabels,
    datasets: [{{
      label: '区间用电 (度)',
      data: consumptionData,
      backgroundColor: consumptionData.map(v => v > 3 ? '#ef4444' : v > 1 ? '#f59e0b' : '#22c55e'),
      borderRadius: 6,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: true, position: 'top' }},
      tooltip: {{
        callbacks: {{
          label: ctx => '消耗: ' + ctx.parsed.y + ' 度'
        }}
      }}
    }},
    scales: {{
      y: {{
        beginAtZero: true,
        title: {{ display: true, text: '用电量 (度)' }}
      }}
    }}
  }}
}});

// 每日消耗
new Chart(document.getElementById('dailyChart'), {{
  type: 'bar',
  data: {{
    labels: dailyLabels,
    datasets: [{{
      label: '每日用电 (度)',
      data: dailyValues,
      backgroundColor: '#667eea',
      borderRadius: 8,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: true, position: 'top' }},
      tooltip: {{
        callbacks: {{
          label: ctx => '日用电: ' + ctx.parsed.y + ' 度'
        }}
      }}
    }},
    scales: {{
      y: {{
        beginAtZero: true,
        title: {{ display: true, text: '用电量 (度)' }}
      }}
    }}
  }}
}});

// 历史表格
const historyData = {json.dumps(history[-20:], ensure_ascii=False)};
const tbody = document.getElementById('historyTable');
let prevP = null;
historyData.reverse().forEach(h => {{
  let consumed = '';
  if (prevP !== null && h.power_num !== null) {{
    const diff = Math.round((prevP - h.power_num) * 100) / 100;
    if (diff > 0) consumed = '<span class="consumed">-' + diff + ' 度</span>';
    else if (diff < 0) consumed = '<span style="color:#22c55e">+' + Math.abs(diff).toFixed(2) + ' 度</span>';
    else consumed = '—';
  }} else {{
    consumed = '—';
  }}
  tbody.innerHTML += '<tr>' +
    '<td>' + (h.time || '') + '</td>' +
    '<td>' + (h.custRechNo || '') + '</td>' +
    '<td class="td-power">' + (h.power_raw || '—') + '</td>' +
    '<td>' + (h.balance_raw || '—') + '</td>' +
    '<td>' + consumed + '</td>' +
    '</tr>';
  prevP = h.power_num;
}});
</script>

<!-- Service Worker 注册 -->
<script>
if ('serviceWorker' in navigator) {{
  window.addEventListener('load', function() {{
    navigator.serviceWorker.register('./sw.js').catch(function(e) {{
      console.log('SW registration failed:', e);
    }});
  }});
}}

// 刷新查询
function handleRefresh() {{
  // GitHub Pages 模式：跳转到 Actions 手动触发
  if (window.location.hostname.indexOf('github.io') !== -1) {{
    showToast('🔄 跳转到手动更新页面...');
    setTimeout(function() {{
      window.open('https://github.com/manchi511/electricity-monitor/actions/workflows/update.yml', '_blank');
    }}, 500);
    return;
  }}
  // 本地服务器模式：调用 API
  var btn = document.getElementById('refreshBtn');
  var icon = document.getElementById('refreshIcon');
  var text = document.getElementById('refreshText');
  btn.classList.add('loading');
  icon.innerHTML = '<span class="spinner"></span>';
  text.textContent = '查询中...';

  fetch('./api/query', {{ method: 'POST' }})
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
      if (data.success) {{
        showToast('✅ 查询成功！页面刷新中...');
        setTimeout(function() {{ window.location.reload(); }}, 1000);
      }} else {{
        showToast('❌ 查询失败: ' + (data.error || '未知错误'));
        btn.classList.remove('loading');
        icon.textContent = '🔄';
        text.textContent = '刷新查询';
      }}
    }})
    .catch(function(err) {{
      showToast('❌ 网络错误，请确认服务正在运行');
      btn.classList.remove('loading');
      icon.textContent = '🔄';
      text.textContent = '刷新查询';
    }});
}}

// 页面加载时检测 GitHub Pages，更新按钮文字
(function() {{
  if (window.location.hostname.indexOf('github.io') !== -1) {{
    var t = document.getElementById('refreshText');
    var b = document.getElementById('refreshBtn');
    if (t) t.textContent = '手动更新';
    if (b) b.title = '点击跳转到 GitHub Actions 手动触发更新';
  }}
}})();

// Toast 提示
function showToast(msg) {{
  var existing = document.querySelector('.toast');
  if (existing) existing.remove();
  var toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(function() {{ toast.classList.add('show'); }}, 10);
  setTimeout(function() {{
    toast.classList.remove('show');
    setTimeout(function() {{ toast.remove(); }}, 300);
  }}, 3000);
}}

// 每 5 分钟自动刷新页面（获取最新仪表盘数据）
setTimeout(function() {{ window.location.reload(); }}, 5 * 60 * 1000);
</script>

</body>
</html>"""

    return html


def main():
    history = load_history()
    if not history:
        print("[WARN] query_log.json 为空或不存在，生成空仪表盘")

    stats = compute_stats(history)
    html = generate_html(history, stats)

    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"[OK] 仪表盘已生成: {OUTPUT_FILE}")
    print(f"  - 历史记录: {len(history)} 条")
    print(f"  - 日均用电: {stats.get('avg_daily_consumption', 0)} 度/天")
    print(f"  - 预估可用: {stats.get('estimated_days', 0)} 天")
    print(f"  - 累计消耗: {stats.get('total_consumed', 0)} 度")


if __name__ == "__main__":
    main()
