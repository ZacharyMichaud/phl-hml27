"""Shared page shell for the site: the tab bar, the base styles and a few script helpers.

Every page is one self-contained HTML file. index.html is a small loader that fetches the page named
by ?p= with a fresh query string, so GitHub Pages' 10-minute cache never shows a stale page.
"""
import datetime
import json

TEAM_NAMES = {"ANA": "Anaheim", "BOS": "Boston", "BUF": "Buffalo", "CAR": "Carolina", "CBJ": "Columbus", "CGY": "Calgary",
              "CHI": "Chicago", "COL": "Colorado", "DAL": "Dallas", "DET": "Detroit", "EDM": "Edmonton", "FLA": "Florida",
              "LAK": "Los Angeles", "MIN": "Minnesota", "MTL": "Montreal", "NJD": "New Jersey", "NSH": "Nashville",
              "NYI": "NY Islanders", "NYR": "NY Rangers", "OTT": "Ottawa", "PHI": "Philadelphia", "PIT": "Pittsburgh",
              "SEA": "Seattle", "SJS": "San Jose", "STL": "St. Louis", "TBL": "Tampa Bay", "TOR": "Toronto", "UTA": "Utah",
              "VAN": "Vancouver", "VGK": "Vegas", "WPG": "Winnipeg", "WSH": "Washington"}

# (key, file, tab label). The first one is the default page; its key never appears in a link.
PAGES = [("trades", "report.html", "Trades"), ("value", "value.html", "Team value"), ("cap", "cap.html", "Cap"),
         ("standings", "standings.html", "Standings"), ("stats", "stats.html", "Player stats"), ("progression", "progression.html", "Progression")]

NAV_CSS = """
  .nav { display: flex; align-items: baseline; gap: 0 20px; margin: 0 0 22px; border-bottom: 1px solid var(--line); font-size: 14px; overflow-x: auto; scrollbar-width: none; }
  .nav::-webkit-scrollbar { display: none; }
  .nav a { color: var(--ink-soft); text-decoration: none; padding: 8px 0 9px; border-bottom: 2px solid transparent; white-space: nowrap; }
  .nav a:hover { color: var(--ink); }
  .nav a[aria-current="page"] { color: var(--ink); font-weight: 700; border-bottom-color: var(--ink); }
  .nav .brand { color: var(--ink); font-weight: 800; letter-spacing: .06em; margin-right: 4px; }
"""


def nav(active):
    links = "".join(f'<a href="./{"" if i == 0 else "?p=" + key}"{" aria-current=" + chr(34) + "page" + chr(34) if key == active else ""}>{label}</a>'
                    for i, (key, _, label) in enumerate(PAGES))
    return f'<nav class="nav" aria-label="Pages"><span class="brand">PHL</span>{links}</nav>'


CSS = """
  :root {
    color-scheme: light dark;
    --ice: #f2f6f9; --paper: #ffffff; --ink: #11203a; --ink-soft: #5b6b82; --line: #d6dfe8; --line-strong: #aebbcb;
    --blue: #1d5fa6; --blue-soft: #dbe8f7; --red: #b4121c; --red-soft: #f8dcdc; --stamp: #b4121c; --hover: #e9f0f8;
    --bar: #7f8ea3; --track: #e3eaf1;
    --sans: "Helvetica Neue", Helvetica, Arial, "Segoe UI", Roboto, sans-serif;
    padding-top: env(safe-area-inset-top, 0px); padding-bottom: env(safe-area-inset-bottom, 0px);
  }
  @media (prefers-color-scheme: dark) { :root {
    --ice: #0e1726; --paper: #15213a; --ink: #edf2f8; --ink-soft: #9fb0c6; --line: #2a3850; --line-strong: #46587a;
    --blue: #6aa6ee; --blue-soft: #1c3458; --red: #f0636b; --red-soft: #4b1f24; --stamp: #f0636b; --hover: #1d2d4a;
    --bar: #5d7090; --track: #1f2c45;
  } }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--ice); color: var(--ink); font-family: var(--sans); font-size: 15px; line-height: 1.45; -webkit-text-size-adjust: 100%; }
  a { color: var(--blue); }
  .wrap { max-width: 1120px; margin: 0 auto; padding: 16px 16px 48px; }
  h1 { font-size: clamp(30px, 5vw, 46px); font-weight: 800; letter-spacing: -0.02em; line-height: 1.05; margin: 0 0 8px; }
  h2 { font-size: 20px; font-weight: 700; letter-spacing: -0.01em; margin: 0; }
  h3 { font-size: 15px; font-weight: 700; margin: 22px 0 6px; }
  p { margin: 0; max-width: 70ch; }
  .lede { color: var(--ink-soft); font-size: 16px; }
  .meta { color: var(--ink-soft); font-size: 13px; margin-top: 6px; }
  section { margin-top: 40px; }
  .head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 8px 16px; padding-bottom: 10px; border-bottom: 2px solid var(--ink); margin-bottom: 12px; }
  .note { color: var(--ink-soft); font-size: 13px; }
  .scroll { overflow: auto; max-height: 76vh; border-bottom: 1px solid var(--line); }
  .scroll.tall { max-height: none; }
  table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
  th, td { padding: 7px 10px; text-align: left; border-bottom: 1px solid var(--line); vertical-align: middle; white-space: nowrap; }
  th { position: sticky; top: 0; z-index: 1; background: var(--ice); color: var(--ink-soft); font-weight: 600; font-size: 13px; }
  th.sortable { cursor: pointer; user-select: none; }
  th.sortable:hover { color: var(--ink); }
  th[aria-sort="ascending"]::after { content: " \\2191"; } th[aria-sort="descending"]::after { content: " \\2193"; }
  .num, th.num { text-align: right; }
  tr.pick { cursor: pointer; } tr.pick:hover td { background: var(--hover); }
  tr.me td { background: var(--blue-soft); }
  tr.cut td { border-bottom: 2px solid var(--ink-soft); }
  tr.sub td { color: var(--ink-soft); font-size: 13px; font-weight: 600; background: var(--ice); padding-top: 12px; }
  tr.sum td { font-weight: 700; border-top: 1px solid var(--line-strong); }
  .sec { display: table-cell; }
  @media (max-width: 760px) { .sec, .wide { display: none; } th, td { padding: 7px 6px; } }
  .grade { display: inline-block; min-width: 2.2em; font-weight: 800; letter-spacing: 0.02em; }
  .g-a, .g-b { color: var(--blue); } .g-d, .g-f { color: var(--red); } .g-x { color: var(--ink-soft); font-weight: 600; }
  .up { color: var(--blue); } .down { color: var(--red); } .soft { color: var(--ink-soft); }
  .team-head { display: flex; flex-wrap: wrap; align-items: center; gap: 16px 28px; }
  .stamp { width: 112px; height: 112px; border: 4px solid var(--stamp); color: var(--stamp); border-radius: 50%; display: grid; place-items: center; font-size: 46px; font-weight: 900; letter-spacing: -0.02em; transform: rotate(-8deg); flex: none; }
  .team-title h2 { font-size: 30px; font-weight: 800; letter-spacing: -0.02em; }
  .team-title .gm { color: var(--ink-soft); font-size: 15px; }
  select, input[type="search"] { font: inherit; color: var(--ink); background: var(--paper); border: 1px solid var(--line-strong); border-radius: 4px; padding: 6px 10px; max-width: 100%; }
  .team-title select { margin-top: 10px; }
  .figures { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 9rem), 1fr)); gap: 0 24px; margin: 22px 0 14px; border-top: 1px solid var(--line); }
  .figures div { padding: 10px 0; border-bottom: 1px solid var(--line); }
  .figures .l { color: var(--ink-soft); font-size: 13px; }
  .figures .v { font-size: 26px; font-weight: 700; letter-spacing: -0.01em; font-variant-numeric: tabular-nums; }
  .figures .s { color: var(--ink-soft); font-size: 13px; }
  .tools { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; margin-bottom: 10px; }
  .tools input[type="search"] { width: min(100%, 22rem); }
  .seg { display: inline-flex; border: 1px solid var(--line-strong); border-radius: 4px; overflow: hidden; }
  .seg button { font: inherit; font-size: 14px; color: var(--ink-soft); background: var(--paper); border: 0; border-right: 1px solid var(--line-strong); padding: 6px 12px; cursor: pointer; }
  .seg button:last-child { border-right: 0; }
  .seg button:hover { color: var(--ink); }
  .seg button[aria-pressed="true"] { background: var(--ink); color: var(--paper); font-weight: 600; }
  .tag { display: inline-block; padding: 0 5px; border: 1px solid var(--line-strong); border-radius: 3px; color: var(--ink-soft); font-size: 11px; font-weight: 600; line-height: 16px; vertical-align: 1px; }
  .pot { display: inline-block; padding: 0 6px; border-radius: 3px; font-size: 12px; font-weight: 700; line-height: 18px; vertical-align: 1px; white-space: nowrap; color: #fff; }
  .pot.m0 { background: #2f6fd6; } .pot.m1 { background: #2b8a3e; } .pot.m2 { background: #e8890c; color: #2b1700; }
  .pot.m3 { background: #d03b3b; } .pot.m4 { background: #7f1d1d; } .pot.m5 { background: #6f7a89; }
  /* Bars: thin, rounded at the data end, on a quiet track. */
  .meter { position: relative; display: inline-block; vertical-align: middle; width: 100%; min-width: 5rem; height: 8px; border-radius: 4px; background: var(--track); overflow: hidden; }
  .meter i { position: absolute; top: 0; bottom: 0; left: 0; background: var(--bar); border-radius: 0 4px 4px 0; }
  .meter i.blue { background: var(--blue); } .meter i.red { background: var(--red); }
  .dbar { position: relative; display: inline-block; vertical-align: middle; width: 100%; min-width: 6rem; height: 8px; }
  .dbar i { position: absolute; top: 0; bottom: 0; }
  .dbar .pos { background: var(--blue); border-radius: 0 4px 4px 0; } .dbar .neg { background: var(--red); border-radius: 4px 0 0 4px; }
  .dbar .zero { top: -3px; bottom: -3px; width: 1px; margin-left: -0.5px; background: var(--ink-soft); }
  @media (forced-colors: active) { .meter i, .dbar .pos, .dbar .neg { background: CanvasText; } }
  .chart { position: relative; }
  .chart svg { display: block; width: 100%; height: auto; }
  .tip { position: absolute; pointer-events: none; background: var(--paper); color: var(--ink); border: 1px solid var(--line-strong); border-radius: 4px; padding: 6px 9px; font-size: 13px; white-space: nowrap; box-shadow: 0 4px 14px rgba(0,0,0,.18); z-index: 3; }
  .tip .t { color: var(--ink-soft); }
  .empty { color: var(--ink-soft); padding: 16px 0; }
  .method p { margin-bottom: 10px; }
  .method b { font-weight: 700; }
  .foot { margin-top: 48px; padding-top: 14px; border-top: 1px solid var(--line); color: var(--ink-soft); font-size: 13px; }
  :focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
"""

# Script helpers every page gets: element lookup, escaping, formats, team routing by #CODE, sortable tables.
JS = r"""
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const D = JSON.parse($('data').textContent);
  const fmtDate = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString('en-CA', {year: 'numeric', month: 'short', day: 'numeric'});
  const money = (x) => { if (x == null) return ''; const a = Math.abs(x), s = x < 0 ? '−' : ''; return a >= 1e6 ? s + '$' + (a / 1e6).toFixed(a % 1e5 ? (a % 1e4 ? 3 : 2) : 1).replace(/(\.\d*?[1-9])0+$/, '$1') + 'M' : s + '$' + Math.round(a / 1000) + 'K'; };
  const mil = (x) => (x < 0 ? '−' : '') + '$' + (Math.abs(x) / 1e6).toFixed(1) + 'M';
  const signed = (x, d) => (x > 0 ? '+' : x < 0 ? '−' : '') + Math.abs(x).toLocaleString('en-CA', {minimumFractionDigits: d || 0, maximumFractionDigits: d || 0});
  const cls = (x) => x > 0 ? 'up' : x < 0 ? 'down' : 'soft';
  const gradeCls = (g) => 'g-' + (g ? g[0].toLowerCase() : 'x');
  { const nav = document.querySelector('.nav'), cur = nav && nav.querySelector('[aria-current]'); if (cur) nav.scrollLeft = Math.max(0, cur.offsetLeft - nav.offsetLeft - 60); }  // keep the open tab in view on a phone
  $('as-of') && ($('as-of').textContent = fmtDate(D.asOf));
  $('built') && ($('built').textContent = fmtDate(D.built));
  // The picked team lives in the address bar as #CGY, so a team's view can be shared.
  const teamCodes = new Set((D.teams || []).map((t) => t.code || t.team));
  const hashTeam = () => { const h = (location.hash || '').slice(1).toUpperCase(); return teamCodes.has(h) ? h : null; };
  const setHashTeam = (code) => history.replaceState(null, '', '#' + code);
  function fillTeams(sel, picked, names) {
    sel.innerHTML = [...teamCodes].sort().map((c) => `<option value="${c}"${c === picked ? ' selected' : ''}>${c} · ${esc(names[c] || c)}</option>`).join('');
  }
  // Click a header to sort; data-k names the row field, data-d its first direction.
  function sortable(table, state, draw) {
    const heads = [...table.querySelectorAll('th[data-k]')];
    const mark = () => heads.forEach((th) => { th.classList.add('sortable'); th.setAttribute('aria-sort', th.dataset.k === state.k ? (state.d > 0 ? 'ascending' : 'descending') : 'none'); });
    heads.forEach((th) => { th.tabIndex = 0; const go = () => { const k = th.dataset.k; state.d = state.k === k ? -state.d : (th.dataset.d === 'asc' ? 1 : -1); state.k = k; mark(); draw(); };
      th.addEventListener('click', go); th.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } }); });
    mark();
  }
  const by = (state) => (a, b) => { const x = a[state.k], y = b[state.k]; return (typeof x === 'string' || typeof y === 'string' ? String(x).localeCompare(String(y)) : (x == null ? -1e99 : x) - (y == null ? -1e99 : y)) * state.d; };
  // One tooltip per chart: show(html, evt) follows the pointer inside the chart box.
  function tooltip(box) {
    const tip = document.createElement('div'); tip.className = 'tip'; tip.hidden = true; box.appendChild(tip);
    return { show(html, e) { tip.innerHTML = html; tip.hidden = false; const r = box.getBoundingClientRect(); let x = e.clientX - r.left + 12, y = e.clientY - r.top + 12;
        if (x + tip.offsetWidth > r.width) x = Math.max(0, e.clientX - r.left - tip.offsetWidth - 12); tip.style.left = x + 'px'; tip.style.top = y + 'px'; }, hide() { tip.hidden = true; } };
  }
"""

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__TITLE__</title>
<meta name="description" content="__DESC__">
<style>__CSS__</style>
</head>
<body>
<div class="wrap">
  __NAV__
__BODY__
  <footer class="foot">Calgary Flames front office, HLM27 sim league. Built from the official league saves.</footer>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
(function () {
  'use strict';
__JS__
})();
</script>
</body>
</html>
"""


def page(key, title, desc, body, data, script, css=""):
    """One full page. `data` becomes D in the script; asOf and built are filled in for the header."""
    data = dict(data)
    data.setdefault("built", datetime.date.today().isoformat())
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    out = TEMPLATE
    for k, v in (("__TITLE__", title), ("__DESC__", desc), ("__CSS__", CSS + NAV_CSS + css), ("__NAV__", nav(key)), ("__BODY__", body),
                 ("__JS__", JS + script), ("__DATA__", payload)):
        out = out.replace(k, v)
    return out


LOADER = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>HLM27 GM report cards</title>
<style>
  :root { color-scheme: light dark; }
  body { margin: 0; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; background: #f2f6f9; color: #5b6b82; }
  @media (prefers-color-scheme: dark) { body { background: #0e1726; color: #9fb0c6; } }
  p { margin: 40px 16px; text-align: center; }
</style>
<script>
  var files = __FILES__;
  var file = files[new URLSearchParams(location.search).get('p')] || 'report.html';
  fetch(file + '?v=' + Date.now(), {cache: 'no-store'})
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
    .then(function (html) { document.open(); document.write(html); document.close(); })
    .catch(function () { location.replace(file + location.hash); });
</script>
</head>
<body><p>Loading…</p><noscript><p><a href="report.html">Open the report cards</a></p></noscript></body>
</html>
""".replace("__FILES__", json.dumps({key: f for key, f, _ in PAGES[1:]}))
