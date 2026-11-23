import os
import time
import json
import ctypes
import sqlite3
import threading
import webbrowser
from datetime import date, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import tkinter as tk
import win32gui
import win32process
import psutil
from PIL import Image, ImageDraw, ImageTk
import pystray

# ==========================================
# BRANDING & CONFIGURATION
# ==========================================
APP_NAME = "ChronoPulse"
APP_TAGLINE = "Windows Dual-Profile Screen Telemetry"
HOST_IP = "127.0.0.2"
PORT = 80
CUSTOM_URL = "http://chronopulse.local"
IDLE_THRESHOLD_SECONDS = 180  # Pause tracking after 3 mins of inactivity
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screentime.db")

USERS = [
    {
        "name": "User 1",
        "initial": "1",
        "tag": "Primary Profile",
        "accent": "#2563EB",
        "badge_bg": "#1E3A8A",
        "badge_fg": "#93C5FD",
    },
    {
        "name": "User 2",
        "initial": "2",
        "tag": "Secondary Profile",
        "accent": "#EAB308",
        "badge_bg": "#422006",
        "badge_fg": "#FFEE00",
    },
]

CURRENT_USER = None
IS_TRACKING = False
CURRENT_APP = "Standby"

# ==========================================
# CUSTOM VECTOR-STYLE LOGO GENERATOR (PIL)
# ==========================================
def generate_brand_logo(size=128):
    """Generates the custom ChronoPulse clock-ring + pulse-bolt emblem."""
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Outer royal-blue rounded squircle base
    pad = int(s * 0.04)
    radius = int(s * 0.26)
    d.rounded_rectangle((pad, pad, s - pad, s - pad), radius=radius, fill="#1D4ED8")

    # Inner deep-navy bezel
    in_pad = int(s * 0.11)
    d.rounded_rectangle(
        (in_pad, in_pad, s - in_pad, s - in_pad),
        radius=int(s * 0.20),
        fill="#0B1120",
        outline="#3B82F6",
        width=int(s * 0.02),
    )

    # Clock dial ring
    ring_pad = int(s * 0.22)
    d.ellipse(
        (ring_pad, ring_pad, s - ring_pad, s - ring_pad),
        outline="#2563EB",
        width=int(s * 0.035),
    )

    # Top & right clock tick accents
    cx, cy = s // 2, s // 2
    tick_w = int(s * 0.03)
    d.line([(cx, int(s * 0.17)), (cx, int(s * 0.25))], fill="#FFEE00", width=tick_w)
    d.line([(int(s * 0.75), cy), (int(s * 0.83), cy)], fill="#93C5FD", width=tick_w)

    # Electric yellow pulse / lightning hand in center
    bolt = [
        (int(s * 0.53), int(s * 0.28)),
        (int(s * 0.39), int(s * 0.52)),
        (int(s * 0.50), int(s * 0.52)),
        (int(s * 0.46), int(s * 0.72)),
        (int(s * 0.62), int(s * 0.47)),
        (int(s * 0.51), int(s * 0.47)),
    ]
    d.polygon(bolt, fill="#FFEE00")

    return img.resize((size, size), Image.Resampling.LANCZOS)

# ==========================================
# DATABASE SETUP (Date-wise only, no timestamps)
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT NOT NULL,
            user_name TEXT NOT NULL,
            app_name TEXT NOT NULL,
            seconds INTEGER NOT NULL,
            UNIQUE(log_date, user_name, app_name)
        )
    """)
    conn.commit()
    conn.close()

def log_usage(user_name, app_name, seconds=1):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO usage_logs (log_date, user_name, app_name, seconds)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(log_date, user_name, app_name)
        DO UPDATE SET seconds = seconds + excluded.seconds
    """, (today, user_name, app_name, seconds))
    conn.commit()
    conn.close()

# ==========================================
# WINDOWS ACTIVE WINDOW & IDLE DETECTION
# ==========================================
class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

def get_idle_seconds():
    try:
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
        return millis / 1000.0
    except Exception:
        return 0

def get_active_app():
    try:
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid)
        return proc.name().replace(".exe", "") or "Unknown"
    except Exception:
        return "System / Desktop"

# ==========================================
# BACKGROUND TRACKER LOOP
# ==========================================
def tracker_loop():
    global CURRENT_APP
    while True:
        time.sleep(1)
        if not IS_TRACKING or not CURRENT_USER:
            CURRENT_APP = "Paused"
            continue
        if get_idle_seconds() >= IDLE_THRESHOLD_SECONDS:
            CURRENT_APP = "Idle (Paused)"
            continue
        app_name = get_active_app()
        CURRENT_APP = app_name
        log_usage(CURRENT_USER, app_name, 1)

# ==========================================
# MODERN BENTO WEB DASHBOARD (ChronoPulse)
# ==========================================
HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ChronoPulse · Screen Telemetry</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect x='2' y='2' width='60' height='60' rx='16' fill='%231D4ED8'/%3E%3Crect x='7' y='7' width='50' height='50' rx='12' fill='%230B1120'/%3E%3Ccircle cx='32' cy='32' r='18' fill='none' stroke='%232563EB' stroke-width='3'/%3E%3Cpolygon points='34,17 24,33 32,33 29,47 40,30 32,30' fill='%23FFEE00'/%3E%3C/svg%3E">
<style>
  :root {
    --bg: #F4F6FA;
    --surface: #FFFFFF;
    --surface-2: #F8FAFC;
    --text: #0B1120;
    --muted: #64748B;
    --border: #E2E8F0;
    --royal: #1D4ED8;
    --royal-soft: #EFF6FF;
    --yellow: #FFEE00;
    --gold: #CA8A04;
    --gold-soft: #FEFCE8;
    --shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.06), 0 4px 10px -6px rgba(15, 23, 42, 0.04);
  }
  [data-theme="dark"] {
    --bg: #070B14;
    --surface: #0F172A;
    --surface-2: #1E293B;
    --text: #F8FAFC;
    --muted: #94A3B8;
    --border: #1E293B;
    --royal: #3B82F6;
    --royal-soft: rgba(37, 99, 235, 0.16);
    --yellow: #FFEE00;
    --gold: #FACC15;
    --gold-soft: rgba(234, 179, 8, 0.14);
    --shadow: 0 12px 30px -6px rgba(0, 0, 0, 0.45);
  }
  * { box-sizing: border-box; font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    transition: background 0.25s ease, color 0.25s ease;
  }
  .topbar {
    background: #0B1120; color: #FFFFFF;
    border-bottom: 2px solid #1D4ED8;
    padding: 15px 32px;
    display: flex; justify-content: space-between; align-items: center;
    position: sticky; top: 0; z-index: 20;
  }
  .brand { display: flex; align-items: center; gap: 13px; }
  .brand-logo { width: 38px; height: 38px; flex-shrink: 0; }
  .brand-title { font-weight: 800; font-size: 1.18rem; letter-spacing: -0.02em; display: flex; align-items: center; gap: 6px; }
  .brand-title span { color: #FFEE00; }
  .brand-sub { font-size: 0.78rem; color: #94A3B8; }
  .live-cluster { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .live-pill {
    display: inline-flex; align-items: center; gap: 8px;
    background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.14);
    padding: 6px 14px; border-radius: 999px; font-size: 0.84rem; font-weight: 600;
  }
  .dot {
    width: 8px; height: 8px; border-radius: 50%; background: #22C55E;
    box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.22);
    animation: pulse 1.8s infinite;
  }
  .dot.paused { background: #F59E0B; box-shadow: none; animation: none; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
  .theme-btn {
    background: #1E293B; color: #F8FAFC; border: 1px solid #334155;
    padding: 7px 13px; border-radius: 9px; font-size: 0.82rem; font-weight: 600;
    cursor: pointer;
  }
  .theme-btn:hover { border-color: #FFEE00; color: #FFEE00; }

  .wrap { max-width: 1120px; margin: 28px auto; padding: 0 24px 48px; }

  .toolbar {
    background: var(--surface); border: 1px solid var(--border);
    box-shadow: var(--shadow); border-radius: 16px;
    padding: 14px 20px; margin-bottom: 24px;
    display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 14px;
  }
  .filter-group { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .seg-btns {
    display: inline-flex; background: var(--surface-2); padding: 4px;
    border-radius: 10px; border: 1px solid var(--border);
  }
  .seg-btn {
    border: none; background: transparent; color: var(--muted);
    padding: 7px 14px; border-radius: 7px; font-weight: 700; font-size: 0.85rem;
    cursor: pointer; transition: all 0.15s;
  }
  .seg-btn.active { background: #1D4ED8; color: #FFFFFF; box-shadow: 0 2px 6px rgba(29,78,216,0.3); }
  input[type="date"] {
    background: var(--surface-2); color: var(--text); border: 1px solid var(--border);
    padding: 8px 12px; border-radius: 10px; font-weight: 600; font-size: 0.88rem;
  }
  .quick-date {
    background: var(--surface-2); color: var(--text); border: 1px solid var(--border);
    padding: 8px 12px; border-radius: 10px; font-weight: 600; font-size: 0.84rem; cursor: pointer;
  }
  .quick-date:hover { border-color: var(--royal); }

  .kpi-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
    gap: 18px; margin-bottom: 24px;
  }
  .kpi {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 16px; padding: 20px 22px; box-shadow: var(--shadow);
    position: relative; overflow: hidden;
  }
  .kpi::after {
    content: ""; position: absolute; top: 0; left: 0; right: 0; height: 4px;
    background: var(--royal);
  }
  .kpi.u1::after { background: #2563EB; }
  .kpi.u2::after { background: #FFEE00; }
  .kpi.total::after { background: linear-gradient(90deg, #2563EB, #FFEE00); }
  .kpi-head { display: flex; justify-content: space-between; align-items: center; }
  .kpi-label { font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }
  .kpi-tag { font-size: 0.75rem; font-weight: 700; padding: 3px 8px; border-radius: 6px; }
  .tag-a { background: var(--royal-soft); color: var(--royal); }
  .tag-v { background: var(--gold-soft); color: var(--gold); }
  .kpi-value { font-size: 1.95rem; font-weight: 800; margin-top: 10px; letter-spacing: -0.03em; }
  .kpi-sub { font-size: 0.82rem; color: var(--muted); margin-top: 4px; }

  .main-grid { display: grid; grid-template-columns: 1.45fr 1fr; gap: 20px; }
  @media (max-width: 860px) { .main-grid { grid-template-columns: 1fr; } }

  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 16px; padding: 22px 24px; box-shadow: var(--shadow);
  }
  .card-title {
    margin: 0 0 18px; font-size: 1.02rem; font-weight: 800;
    display: flex; justify-content: space-between; align-items: center;
  }
  .card-title span { font-size: 0.8rem; font-weight: 600; color: var(--muted); }

  .app-item { margin-bottom: 16px; }
  .app-item:last-child { margin-bottom: 0; }
  .app-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
  .app-left { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 0.93rem; }
  .app-icon {
    width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center;
    font-weight: 800; font-size: 0.8rem;
  }
  .icon-u1 { background: var(--royal-soft); color: var(--royal); }
  .icon-u2 { background: var(--gold-soft); color: var(--gold); }
  .user-chip {
    font-size: 0.72rem; font-weight: 700; padding: 2px 8px; border-radius: 999px;
  }
  .chip-u1 { background: var(--royal-soft); color: var(--royal); }
  .chip-u2 { background: var(--gold-soft); color: var(--gold); }
  .app-right { font-size: 0.88rem; font-weight: 700; font-variant-numeric: tabular-nums; }
  .app-pct { color: var(--muted); font-weight: 600; font-size: 0.8rem; margin-left: 6px; }
  .track { height: 10px; background: var(--surface-2); border-radius: 999px; overflow: hidden; border: 1px solid var(--border); }
  .fill { height: 100%; border-radius: 999px; transition: width 0.35s ease; }

  .split-box { display: flex; align-items: center; gap: 22px; margin-bottom: 22px; }
  .legend { flex: 1; display: flex; flex-direction: column; gap: 12px; }
  .leg-row { display: flex; justify-content: space-between; align-items: center; font-size: 0.9rem; font-weight: 700; }
  .leg-dot { width: 11px; height: 11px; border-radius: 3px; display: inline-block; margin-right: 8px; }

  .week-bars {
    display: grid; grid-template-columns: repeat(7, 1fr); gap: 10px;
    align-items: end; height: 150px; padding-top: 16px;
    border-top: 1px solid var(--border); margin-top: 14px;
  }
  .w-col { display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end; gap: 6px; }
  .w-bar-wrap { width: 100%; max-width: 30px; height: 105px; background: var(--surface-2); border-radius: 8px; display: flex; align-items: flex-end; overflow: hidden; }
  .w-bar { width: 100%; background: linear-gradient(180deg, #2563EB, #1D4ED8); border-radius: 8px; transition: height 0.3s; }
  .w-bar.selected { background: linear-gradient(180deg, #FFEE00, #EAB308); }
  .w-lbl { font-size: 0.72rem; font-weight: 700; color: var(--muted); }
  .empty { text-align: center; padding: 34px 12px; color: var(--muted); font-size: 0.92rem; }
</style>
</head>
<body>

<div class="topbar">
  <div class="brand">
    <svg class="brand-logo" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="2" y="2" width="60" height="60" rx="16" fill="#1D4ED8"/>
      <rect x="7" y="7" width="50" height="50" rx="12" fill="#0B1120" stroke="#3B82F6" stroke-width="1.5"/>
      <circle cx="32" cy="32" r="18" stroke="#2563EB" stroke-width="2.5"/>
      <line x1="32" y1="11" x2="32" y2="16" stroke="#FFEE00" stroke-width="2.5" stroke-linecap="round"/>
      <line x1="48" y1="32" x2="53" y2="32" stroke="#93C5FD" stroke-width="2.5" stroke-linecap="round"/>
      <polygon points="34,18 24,33 32,33 29,46 40,30 32,30" fill="#FFEE00"/>
    </svg>
    <div>
      <div class="brand-title">Chrono<span>Pulse</span></div>
      <div class="brand-sub" id="brandSub">Date-Wise Windows Screen Telemetry</div>
    </div>
  </div>
  <div class="live-cluster">
    <div class="live-pill">
      <span class="dot" id="liveDot"></span>
      <span id="liveStatus">Active: -</span>
    </div>
    <div class="live-pill" style="color:#FFEE00;" id="liveApp">App: -</div>
    <button class="theme-btn" onclick="toggleTheme()" id="themeBtn">Dark Mode</button>
  </div>
</div>

<div class="wrap">
  <div class="toolbar">
    <div class="filter-group">
      <div class="seg-btns" id="userTabs"></div>
    </div>
    <div class="filter-group">
      <button class="quick-date" onclick="shiftDate(-1)">&larr; Prev Day</button>
      <input type="date" id="dateFilter" onchange="loadData()">
      <button class="quick-date" onclick="setToday()">Today</button>
    </div>
  </div>

  <div class="kpi-grid">
    <div class="kpi u1">
      <div class="kpi-head">
        <span class="kpi-label" id="u1Label">User 1</span>
        <span class="kpi-tag tag-a" id="u1Pct">0%</span>
      </div>
      <div class="kpi-value" id="u1Total">0m</div>
      <div class="kpi-sub">Selected date total</div>
    </div>
    <div class="kpi u2">
      <div class="kpi-head">
        <span class="kpi-label" id="u2Label">User 2</span>
        <span class="kpi-tag tag-v" id="u2Pct">0%</span>
      </div>
      <div class="kpi-value" id="u2Total">0m</div>
      <div class="kpi-sub">Selected date total</div>
    </div>
    <div class="kpi total">
      <div class="kpi-head">
        <span class="kpi-label">Combined Screen Time</span>
        <span class="kpi-tag tag-a" id="appCount">0 apps</span>
      </div>
      <div class="kpi-value" id="combinedTotal">0m</div>
      <div class="kpi-sub" id="topAppLabel">Top app: -</div>
    </div>
  </div>

  <div class="main-grid">
    <div class="card">
      <h2 class="card-title">Application Breakdown <span id="filterSubtitle">Showing all users</span></h2>
      <div id="appList"></div>
    </div>

    <div style="display:flex; flex-direction:column; gap:20px;">
      <div class="card">
        <h2 class="card-title">Daily Share <span id="shareSubtitle">Profile split</span></h2>
        <div class="split-box">
          <svg width="116" height="116" viewBox="0 0 36 36">
            <circle cx="18" cy="18" r="14" fill="none" stroke="#E2E8F0" stroke-width="4.5"></circle>
            <circle id="ringU2" cx="18" cy="18" r="14" fill="none" stroke="#EAB308" stroke-width="4.5" stroke-dasharray="100 100" transform="rotate(-90 18 18)"></circle>
            <circle id="ringU1" cx="18" cy="18" r="14" fill="none" stroke="#2563EB" stroke-width="4.5" stroke-dasharray="0 100" transform="rotate(-90 18 18)"></circle>
          </svg>
          <div class="legend">
            <div class="leg-row">
              <span><i class="leg-dot" style="background:#2563EB;"></i><b id="legU1Name">User 1</b></span>
              <span id="legU1">0m</span>
            </div>
            <div class="leg-row">
              <span><i class="leg-dot" style="background:#EAB308;"></i><b id="legU2Name">User 2</b></span>
              <span id="legU2">0m</span>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <h2 class="card-title">7-Day Trend <span>Total daily usage</span></h2>
        <div class="week-bars" id="weekBars"></div>
      </div>
    </div>
  </div>
</div>

<script>
let selectedUser = 'ALL';
let configuredUsers = [];
const dateInput = document.getElementById('dateFilter');
dateInput.valueAsDate = new Date();

function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  document.getElementById('themeBtn').textContent = t === 'dark' ? 'Light Mode' : 'Dark Mode';
  localStorage.setItem('cp_theme', t);
}
applyTheme(localStorage.getItem('cp_theme') || 'light');

function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme');
  applyTheme(cur === 'dark' ? 'light' : 'dark');
}

function setUser(u) {
  selectedUser = u;
  document.querySelectorAll('#userTabs .seg-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.user === u);
  });
  document.getElementById('filterSubtitle').textContent = u === 'ALL' ? 'Showing all users' : `Filtered: ${u}`;
  loadData();
}

function setToday() {
  dateInput.valueAsDate = new Date();
  loadData();
}

function shiftDate(days) {
  const d = new Date(dateInput.value + 'T00:00:00');
  d.setDate(d.getDate() + days);
  dateInput.value = d.toISOString().split('T')[0];
  loadData();
}

function fmt(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function initTabs(users) {
  if (configuredUsers.length) return;
  configuredUsers = users;
  const tabs = document.getElementById('userTabs');
  tabs.innerHTML = `<button class="seg-btn active" data-user="ALL" onclick="setUser('ALL')">Both Users</button>` +
    users.map(u => `<button class="seg-btn" data-user="${u}" onclick="setUser('${u}')">${u}</button>`).join('');
  document.getElementById('brandSub').textContent = `Date-Wise Screen Telemetry · ${users.join(' & ')}`;
  document.getElementById('shareSubtitle').textContent = users.join(' vs ');
  if (users[0]) {
    document.getElementById('u1Label').textContent = users[0];
    document.getElementById('legU1Name').textContent = users[0];
  }
  if (users[1]) {
    document.getElementById('u2Label').textContent = users[1];
    document.getElementById('legU2Name').textContent = users[1];
  }
}

async function loadData() {
  const dt = dateInput.value;
  const res = await fetch(`/api/stats?date=${dt}&user=${encodeURIComponent(selectedUser)}`);
  const data = await res.json();

  initTabs(data.configured_users);
  const u1 = data.configured_users[0] || 'User 1';
  const u2 = data.configured_users[1] || 'User 2';

  const isLive = data.current_user && !data.current_app.includes('Paused');
  document.getElementById('liveDot').className = isLive ? 'dot' : 'dot paused';
  document.getElementById('liveStatus').textContent = data.current_user ? `User: ${data.current_user}` : 'No user selected';
  document.getElementById('liveApp').textContent = `App: ${data.current_app}`;

  const u1Sec = data.user_totals[u1] || 0;
  const u2Sec = data.user_totals[u2] || 0;
  const tot = u1Sec + u2Sec;

  const u1Share = tot > 0 ? Math.round((u1Sec / tot) * 100) : 0;
  const u2Share = tot > 0 ? 100 - u1Share : 0;

  document.getElementById('u1Total').textContent = fmt(u1Sec);
  document.getElementById('u2Total').textContent = fmt(u2Sec);
  document.getElementById('combinedTotal').textContent = fmt(tot);
  document.getElementById('u1Pct').textContent = `${u1Share}%`;
  document.getElementById('u2Pct').textContent = `${u2Share}%`;
  document.getElementById('legU1').textContent = `${fmt(u1Sec)} (${u1Share}%)`;
  document.getElementById('legU2').textContent = `${fmt(u2Sec)} (${u2Share}%)`;

  const circumference = 87.96;
  document.getElementById('ringU1').setAttribute('stroke-dasharray', `${(u1Share / 100) * circumference} ${circumference}`);
  document.getElementById('ringU2').setAttribute('stroke-dasharray', tot > 0 ? `${circumference} ${circumference}` : `0 ${circumference}`);

  document.getElementById('appCount').textContent = `${data.apps.length} apps`;
  document.getElementById('topAppLabel').textContent = data.apps.length ? `Top app: ${data.apps[0].app_name}` : 'Top app: -';

  const list = document.getElementById('appList');
  if (!data.apps.length) {
    list.innerHTML = '<div class="empty">No application usage logged for this date.</div>';
  } else {
    const filteredTotal = data.apps.reduce((sum, x) => sum + x.seconds, 0) || 1;
    const maxSec = data.apps[0].seconds || 1;
    list.innerHTML = data.apps.map(a => {
      const isSecondUser = a.user_name === u2;
      const barPct = Math.max(4, Math.round((a.seconds / maxSec) * 100));
      const sharePct = Math.max(1, Math.round((a.seconds / filteredTotal) * 100));
      const color = isSecondUser ? '#EAB308' : '#2563EB';
      const cls = isSecondUser ? 'u2' : 'u1';
      const initial = a.app_name.charAt(0).toUpperCase();
      return `
        <div class="app-item">
          <div class="app-top">
            <div class="app-left">
              <div class="app-icon icon-${cls}">${initial}</div>
              <span>${a.app_name}</span>
              <span class="user-chip chip-${cls}">${a.user_name}</span>
            </div>
            <div class="app-right">${fmt(a.seconds)}<span class="app-pct">(${sharePct}%)</span></div>
          </div>
          <div class="track"><div class="fill" style="width:${barPct}%; background:${color};"></div></div>
        </div>`;
    }).join('');
  }

  const weekDiv = document.getElementById('weekBars');
  const maxWeek = Math.max(1, ...data.week.map(w => w.seconds));
  weekDiv.innerHTML = data.week.map(w => {
    const hPct = w.seconds > 0 ? Math.max(8, Math.round((w.seconds / maxWeek) * 100)) : 4;
    const isSel = w.date === dt;
    return `
      <div class="w-col" title="${w.date}: ${fmt(w.seconds)}" onclick="dateInput.value='${w.date}'; loadData();" style="cursor:pointer;">
        <div class="w-bar-wrap"><div class="w-bar ${isSel ? 'selected' : ''}" style="height:${hPct}%;"></div></div>
        <div class="w-lbl">${w.label}</div>
      </div>`;
  }).join('');
}

loadData();
setInterval(loadData, 5000);
</script>
</body>
</html>"""

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_DASHBOARD.encode("utf-8"))
        elif parsed.path == "/api/stats":
            qs = parse_qs(parsed.query)
            target_date = qs.get("date", [date.today().isoformat()])[0]
            target_user = qs.get("user", ["ALL"])[0]

            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            c.execute("""
                SELECT user_name, SUM(seconds)
                FROM usage_logs WHERE log_date = ?
                GROUP BY user_name
            """, (target_date,))
            user_totals = {r[0]: r[1] for r in c.fetchall()}

            if target_user == "ALL":
                c.execute("""
                    SELECT app_name, user_name, seconds
                    FROM usage_logs WHERE log_date = ?
                    ORDER BY seconds DESC
                """, (target_date,))
            else:
                c.execute("""
                    SELECT app_name, user_name, seconds
                    FROM usage_logs WHERE log_date = ? AND user_name = ?
                    ORDER BY seconds DESC
                """, (target_date, target_user))
            apps_data = [{"app_name": r[0], "user_name": r[1], "seconds": r[2]} for r in c.fetchall()]

            try:
                base_dt = date.fromisoformat(target_date)
            except ValueError:
                base_dt = date.today()

            week_data = []
            for offset in range(6, -1, -1):
                d_obj = base_dt - timedelta(days=offset)
                d_str = d_obj.isoformat()
                if target_user == "ALL":
                    c.execute("SELECT COALESCE(SUM(seconds), 0) FROM usage_logs WHERE log_date = ?", (d_str,))
                else:
                    c.execute("SELECT COALESCE(SUM(seconds), 0) FROM usage_logs WHERE log_date = ? AND user_name = ?", (d_str, target_user))
                sec = c.fetchone()[0]
                week_data.append({
                    "date": d_str,
                    "label": d_obj.strftime("%a"),
                    "seconds": sec,
                })

            conn.close()

            payload = {
                "configured_users": [u["name"] for u in USERS],
                "current_user": CURRENT_USER,
                "current_app": CURRENT_APP,
                "user_totals": user_totals,
                "apps": apps_data,
                "week": week_data,
            }
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

def start_web_server():
    global PORT, CUSTOM_URL
    try:
        server = HTTPServer((HOST_IP, PORT), DashboardHandler)
    except PermissionError:
        PORT = 8765
        CUSTOM_URL = f"http://chronopulse.local:{PORT}"
        server = HTTPServer((HOST_IP, PORT), DashboardHandler)
    server.serve_forever()

# ==========================================
# CHRONOPULSE WINDOWS DESKTOP UI + TRAY
# ==========================================
class ChronoPulseApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.configure(bg="#1E293B")
        self.root.attributes("-topmost", True)

        self.window_icon_img = ImageTk.PhotoImage(generate_brand_logo(64))
        self.header_logo_img = ImageTk.PhotoImage(generate_brand_logo(26))
        self.mini_logo_img = ImageTk.PhotoImage(generate_brand_logo(22))
        self.root.iconphoto(True, self.window_icon_img)

        self._drag_x = 0
        self._drag_y = 0

        self.show_selector_ui()
        self.setup_tray_icon()

    def center_window(self, w, h):
        ws = self.root.winfo_screenwidth()
        hs = self.root.winfo_screenheight()
        x = (ws // 2) - (w // 2)
        y = (hs // 2) - (h // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def position_bottom_right(self, w, h):
        ws = self.root.winfo_screenwidth()
        hs = self.root.winfo_screenheight()
        x = ws - w - 24
        y = hs - h - 64
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def make_draggable(self, widget):
        widget.bind("<ButtonPress-1>", self._start_drag)
        widget.bind("<B1-Motion>", self._on_drag)

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag(self, event):
        x = self.root.winfo_x() + (event.x - self._drag_x)
        y = self.root.winfo_y() + (event.y - self._drag_y)
        self.root.geometry(f"+{x}+{y}")

    def setup_tray_icon(self):
        tray_logo = generate_brand_logo(64)
        menu = pystray.Menu(
            pystray.MenuItem(f"Open {APP_NAME}", lambda: self.root.after(0, self.show_window), default=True),
            pystray.MenuItem("Open Dashboard", lambda: webbrowser.open(CUSTOM_URL)),
            pystray.MenuItem("Switch User", lambda: self.root.after(0, self.switch_user_from_tray)),
            pystray.MenuItem("Exit Completely", self.quit_app),
        )
        self.tray = pystray.Icon(APP_NAME, tray_logo, f"{APP_NAME} · Screen Monitor", menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def hide_to_tray(self):
        self.root.withdraw()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()

    def switch_user_from_tray(self):
        self.show_window()
        self.switch_user()

    def quit_app(self, icon=None, item=None):
        if hasattr(self, "tray"):
            self.tray.stop()
        self.root.after(0, self.root.destroy)
        os._exit(0)

    def show_selector_ui(self):
        for w in self.root.winfo_children():
            w.destroy()

        self.root.attributes("-topmost", True)
        self.center_window(416, 332)

        outer = tk.Frame(self.root, bg="#0B1120", highlightbackground="#2563EB", highlightthickness=1)
        outer.pack(fill="both", expand=True)

        top = tk.Frame(outer, bg="#0F172A", height=52)
        top.pack(fill="x")
        top.pack_propagate(False)
        self.make_draggable(top)

        logo_lbl = tk.Label(top, image=self.header_logo_img, bg="#0F172A")
        logo_lbl.pack(side="left", padx=(16, 8), pady=12)
        self.make_draggable(logo_lbl)

        title = tk.Label(top, text="CHRONOPULSE", bg="#0F172A", fg="#F8FAFC", font=("Segoe UI", 10, "bold"))
        title.pack(side="left")
        self.make_draggable(title)

        ver = tk.Label(top, text=" · SESSION", bg="#0F172A", fg="#FFEE00", font=("Segoe UI", 9, "bold"))
        ver.pack(side="left")
        self.make_draggable(ver)

        close_btn = tk.Label(top, text="✕", bg="#0F172A", fg="#94A3B8", font=("Segoe UI", 11, "bold"), cursor="hand2", padx=15)
        close_btn.pack(side="right", fill="y")
        close_btn.bind("<Button-1>", lambda e: self.hide_to_tray())
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg="#FFFFFF", bg="#1E293B"))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg="#94A3B8", bg="#0F172A"))

        body = tk.Frame(outer, bg="#0B1120", padx=24, pady=18)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text="Who is using this PC?",
            bg="#0B1120", fg="#F8FAFC", font=("Segoe UI", 16, "bold")
        ).pack(anchor="w")

        tk.Label(
            body, text="Select a profile to start date-wise telemetry",
            bg="#0B1120", fg="#64748B", font=("Segoe UI", 9)
        ).pack(anchor="w", pady=(2, 16))

        for u in USERS:
            self._build_profile_card(body, u)

    def _build_profile_card(self, parent, u):
        card = tk.Frame(
            parent, bg="#111827", highlightbackground="#1E293B",
            highlightthickness=1, padx=14, pady=12, cursor="hand2"
        )
        card.pack(fill="x", pady=6)

        avatar = tk.Label(
            card, text=u["initial"], bg=u["badge_bg"], fg=u["badge_fg"],
            font=("Segoe UI", 13, "bold"), width=3, height=1, pady=4
        )
        avatar.pack(side="left")

        info = tk.Frame(card, bg="#111827")
        info.pack(side="left", padx=12)

        name_lbl = tk.Label(info, text=u["name"], bg="#111827", fg="#F8FAFC", font=("Segoe UI", 12, "bold"))
        name_lbl.pack(anchor="w")

        tag_lbl = tk.Label(info, text=u["tag"], bg="#111827", fg="#64748B", font=("Segoe UI", 8))
        tag_lbl.pack(anchor="w")

        arrow = tk.Label(card, text="Start →", bg="#111827", fg=u["accent"], font=("Segoe UI", 10, "bold"))
        arrow.pack(side="right")

        widgets = [card, avatar, info, name_lbl, tag_lbl, arrow]
        for w in widgets:
            w.bind("<Button-1>", lambda e, name=u["name"]: self.select_user(name))
            w.bind("<Enter>", lambda e, c=card, i=info, n=name_lbl, t=tag_lbl, a=arrow, ac=u["accent"]: (
                c.config(bg="#1E293B", highlightbackground=ac),
                i.config(bg="#1E293B"), n.config(bg="#1E293B"),
                t.config(bg="#1E293B"), a.config(bg="#1E293B")
            ))
            w.bind("<Leave>", lambda e, c=card, i=info, n=name_lbl, t=tag_lbl, a=arrow: (
                c.config(bg="#111827", highlightbackground="#1E293B"),
                i.config(bg="#111827"), n.config(bg="#111827"),
                t.config(bg="#111827"), a.config(bg="#111827")
            ))

    def select_user(self, user_name):
        global CURRENT_USER, IS_TRACKING
        CURRENT_USER = user_name
        IS_TRACKING = True
        self.root.attributes("-topmost", False)
        self.show_mini_widget()

    def show_mini_widget(self):
        for w in self.root.winfo_children():
            w.destroy()

        self.position_bottom_right(356, 174)

        outer = tk.Frame(self.root, bg="#0B1120", highlightbackground="#1D4ED8", highlightthickness=1)
        outer.pack(fill="both", expand=True)

        top = tk.Frame(outer, bg="#1D4ED8", height=44)
        top.pack(fill="x")
        top.pack_propagate(False)
        self.make_draggable(top)

        mini_logo = tk.Label(top, image=self.mini_logo_img, bg="#1D4ED8")
        mini_logo.pack(side="left", padx=(12, 8))
        self.make_draggable(mini_logo)

        user_lbl = tk.Label(
            top, text=f"{APP_NAME} · {CURRENT_USER.upper()}",
            bg="#1D4ED8", fg="#FFEE00", font=("Segoe UI", 9, "bold")
        )
        user_lbl.pack(side="left")
        self.make_draggable(user_lbl)

        hide_btn = tk.Label(top, text="—", bg="#1D4ED8", fg="#FFFFFF", font=("Segoe UI", 11, "bold"), cursor="hand2", padx=12)
        hide_btn.pack(side="right", fill="y")
        hide_btn.bind("<Button-1>", lambda e: self.hide_to_tray())

        body = tk.Frame(outer, bg="#0B1120", padx=16, pady=12)
        body.pack(fill="both", expand=True)

        self.app_lbl = tk.Label(
            body, text="Tracking: ...",
            bg="#0B1120", fg="#F8FAFC", font=("Segoe UI", 11, "bold")
        )
        self.app_lbl.pack(anchor="w")

        tk.Label(
            body, text="Minimize (—) keeps ChronoPulse running in system tray",
            bg="#0B1120", fg="#64748B", font=("Segoe UI", 8)
        ).pack(anchor="w", pady=(2, 12))

        btn_row = tk.Frame(body, bg="#0B1120")
        btn_row.pack(fill="x")

        self._action_btn(btn_row, "Dashboard", "#2563EB", "#FFFFFF", lambda: webbrowser.open(CUSTOM_URL)).pack(side="left", padx=(0, 6))
        self._action_btn(btn_row, "Switch User", "#FFEE00", "#0B1120", self.switch_user).pack(side="left", padx=(0, 6))
        self._action_btn(btn_row, "Exit", "#1E293B", "#F87171", self.quit_app).pack(side="right")

        self.update_status()

    def _action_btn(self, parent, text, bg, fg, cmd):
        return tk.Button(
            parent, text=text, bg=bg, fg=fg,
            activebackground=bg, activeforeground=fg,
            font=("Segoe UI", 9, "bold"), relief="flat",
            padx=11, pady=5, cursor="hand2", bd=0, command=cmd
        )

    def switch_user(self):
        global IS_TRACKING
        IS_TRACKING = False
        self.show_selector_ui()

    def update_status(self):
        if IS_TRACKING:
            self.app_lbl.config(text=f"Active: {CURRENT_APP[:28]}")
            self.root.after(1000, self.update_status)

if __name__ == "__main__":
    init_db()
    threading.Thread(target=tracker_loop, daemon=True).start()
    threading.Thread(target=start_web_server, daemon=True).start()

    root = tk.Tk()
    app = ChronoPulseApp(root)
    root.mainloop()