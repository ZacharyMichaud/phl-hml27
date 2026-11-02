#!/usr/bin/env python3
"""Build a self-contained index.html from HLM27_GM_Report_Cards.xlsx.

Usage: python3 build_report_cards.py HLM27_GM_Report_Cards.xlsx [index.html]

Reads the "Entries and Exits" sheet (one row per team per trade), the grade
cutoffs and sample-size limits on the "Method" sheet, and the team names from
the per-team tabs. Everything else (grades, ranks, chart) is computed in the
page itself, so replacing the workbook and re-running is the whole update.
"""
import datetime
import json
import re
import sys

from openpyxl import load_workbook

src = sys.argv[1] if len(sys.argv) > 1 else "HLM27_GM_Report_Cards.xlsx"
out = sys.argv[2] if len(sys.argv) > 2 else "index.html"
wb = load_workbook(src, data_only=True)

cols = ["date", "trade", "team", "partner", "entries", "exits", "players_in", "players_out",
        "picks_in", "picks_out", "value_in", "value_out", "net", "result", "note"]
ledger = []
for r in wb["Entries and Exits"].iter_rows(min_row=2, values_only=True):
    if r[0] is None:
        continue
    d = dict(zip(cols, r))
    d["trade"] = str(d["trade"])
    d["note"] = d["note"] or ""
    ledger.append(d)

cutoffs, limits = [], {}
for r in wb["Method"].iter_rows(values_only=True):
    if isinstance(r[0], (int, float)) and isinstance(r[1], str):
        cutoffs.append({"min_edge": r[0], "grade": r[1]})
    elif isinstance(r[0], str) and isinstance(r[1], int):
        limits[r[0]] = r[1]
min_trades = limits.get("Minimum trades for any grade", 3)
full_trades = limits.get("Trades for a full (no asterisk) grade", 8)

teams = []
for ws in wb.worksheets:
    m = re.match(r"(.+) \((\w{3})\)", str(ws["A1"].value or ""))
    if m and ws.title == m.group(2):
        teams.append({"team": m.group(2), "name": m.group(1), "gm": ""})

# The game caps a trade at 5 assets per side, so a bigger deal gets entered as
# several trades on the same day between the same two teams. Those are combined
# into one: any same-day group between the same teams where one part hits the cap.
# KEEP_SEPARATE lists groups to leave split anyway (by any one of their trade ids);
# EXTRA_MERGES lists other groups to combine, as tuples of trade ids.
ASSET_CAP = 5
KEEP_SEPARATE = {"3837", "3972", "4041"}  # Pulock (MTL-NYI), Nylander (OTT-TOR), Kuznetsov (CGY-NJD): separate deals
EXTRA_MERGES = []

from collections import defaultdict
by_trade = defaultdict(list)
for d in ledger:
    by_trade[d["trade"]].append(d)
groups = defaultdict(list)
for tid, rs in by_trade.items():
    groups[(rs[0]["date"], frozenset(x["team"] for x in rs))].append(tid)
merge_sets = []
for tids in groups.values():
    if len(tids) < 2 or any(t in KEEP_SEPARATE for t in tids):
        continue
    if any(d["players_in"] + d["picks_in"] >= ASSET_CAP for t in tids for d in by_trade[t]):
        merge_sets.append(tids)
merge_sets += [list(m) for m in EXTRA_MERGES]

def _num(t):
    return (0, int(t)) if t.isdigit() else (1, int(t.lstrip("D#")))

merged_ids = set()
combined = []
for tids in merge_sets:
    tids = sorted(tids, key=_num)
    merged_ids.update(tids)
    new_id = "+".join(tids)
    for team in sorted({d["team"] for t in tids for d in by_trade[t]}):
        parts = [d for t in tids for d in by_trade[t] if d["team"] == team]
        join = lambda k: "; ".join(p[k] for p in parts if p[k] and p[k] != "—") or "—"
        notes = [p["note"] for p in parts if p["note"]]
        row = {
            "date": parts[0]["date"], "trade": new_id, "team": team, "partner": parts[0]["partner"],
            "entries": join("entries"), "exits": join("exits"),
            **{k: sum(p[k] for p in parts) for k in ("players_in", "players_out", "picks_in", "picks_out", "value_in", "value_out")},
            "note": "; ".join([f"Combined from {len(tids)} trades entered the same day (the game allows {ASSET_CAP} assets per side)"] + notes),
        }
        row["net"] = row["value_in"] - row["value_out"]
        combined.append(row)
ledger = [d for d in ledger if d["trade"] not in merged_ids] + combined
ledger.sort(key=lambda d: (d["date"], _num(d["trade"].split("+")[0]), d["team"]))
print("combined", len(merge_sets), "split deals:", ", ".join("+".join(sorted(m, key=_num)) for m in merge_sets))

# A trade counts as Even when its balance, net value / total value moved, is
# within this band either way: close enough that both sides' AI GMs would take it.
EVEN_BAND = 0.10
for d in ledger:
    vin, vout = d["value_in"], d["value_out"]
    moved = abs(vin) + abs(vout)
    bal = (vin - vout) / moved if moved else 0.0
    d["result"] = "Even" if abs(bal) < EVEN_BAND else ("Win" if vin > vout else "Loss")

# GM names: fill this in once and they show on the cards.
GM_NAMES = {}
for t in teams:
    t["gm"] = GM_NAMES.get(t["team"], "")

data = {
    "ledger": ledger, "cutoffs": cutoffs, "teams": teams,
    "minTrades": min_trades, "fullTrades": full_trades, "evenBand": EVEN_BAND,
    "asOf": max(r["date"] for r in ledger),
    "built": datetime.date.today().isoformat(),
}
payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>HLM27 GM report cards</title>
<meta name="description" content="Trade report cards for every GM in the HLM27 league: value won versus sent, graded trade by trade.">
<style>
  :root {
    color-scheme: light dark;
    --ice: #f2f6f9; --paper: #ffffff; --ink: #11203a; --ink-soft: #5b6b82; --line: #d6dfe8; --line-strong: #aebbcb;
    --blue: #1d5fa6; --blue-soft: #dbe8f7; --red: #b4121c; --red-soft: #f8dcdc; --stamp: #b4121c; --hover: #e9f0f8;
    --sans: "Helvetica Neue", Helvetica, Arial, "Segoe UI", Roboto, sans-serif;
    padding-top: env(safe-area-inset-top, 0px); padding-bottom: env(safe-area-inset-bottom, 0px);
  }
  @media (prefers-color-scheme: dark) { :root {
    --ice: #0e1726; --paper: #15213a; --ink: #edf2f8; --ink-soft: #9fb0c6; --line: #2a3850; --line-strong: #46587a;
    --blue: #6aa6ee; --blue-soft: #1c3458; --red: #f0636b; --red-soft: #4b1f24; --stamp: #f0636b; --hover: #1d2d4a;
  } }
  * { box-sizing: border-box; }
  html { scroll-padding-top: env(safe-area-inset-top, 0px); }
  body { margin: 0; background: var(--ice); color: var(--ink); font-family: var(--sans); font-size: 15px; line-height: 1.45; -webkit-text-size-adjust: 100%; }
  a { color: var(--blue); }
  .wrap { max-width: 1120px; margin: 0 auto; padding: 24px 16px 48px; }
  h1 { font-size: clamp(30px, 5vw, 46px); font-weight: 800; letter-spacing: -0.02em; line-height: 1.05; margin: 0 0 8px; }
  h2 { font-size: 20px; font-weight: 700; letter-spacing: -0.01em; margin: 0; }
  p { margin: 0; max-width: 70ch; }
  .lede { color: var(--ink-soft); font-size: 16px; }
  .meta { color: var(--ink-soft); font-size: 13px; margin-top: 6px; }
  .meta a { color: inherit; }
  section { margin-top: 40px; }
  .head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 8px 16px; padding-bottom: 10px; border-bottom: 2px solid var(--ink); margin-bottom: 12px; }
  .note { color: var(--ink-soft); font-size: 13px; }
  .scroll { overflow: auto; max-height: 72vh; border-bottom: 1px solid var(--line); }
  table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
  th, td { padding: 7px 10px; text-align: left; border-bottom: 1px solid var(--line); vertical-align: top; white-space: nowrap; }
  th { position: sticky; top: 0; z-index: 1; background: var(--ice); color: var(--ink-soft); font-weight: 600; font-size: 13px; }
  th.sortable { cursor: pointer; user-select: none; }
  th.sortable:hover { color: var(--ink); }
  th[aria-sort="ascending"]::after { content: " \2191"; } th[aria-sort="descending"]::after { content: " \2193"; }
  .num { text-align: right; } th.num { text-align: right; }
  td.text { white-space: normal; min-width: 15rem; }
  tr.pick { cursor: pointer; } tr.pick:hover td { background: var(--hover); }
  tr.me td { background: var(--blue-soft); }
  .sec { display: table-cell; } @media (max-width: 760px) { .sec { display: none; } th, td { padding: 7px 6px; } }
  td.tag { white-space: nowrap; }
  .grade { display: inline-block; min-width: 2.4em; text-align: center; font-weight: 800; letter-spacing: 0.02em; }
  .g-a, .g-b { color: var(--blue); } .g-d, .g-f { color: var(--red); } .g-x { color: var(--ink-soft); font-weight: 600; }
  .win { color: var(--blue); } .loss { color: var(--red); } .even { color: var(--ink-soft); }
  .chart { position: relative; }
  .chart svg { display: block; width: 100%; height: auto; }
  .tip { position: absolute; pointer-events: none; background: var(--paper); color: var(--ink); border: 1px solid var(--line-strong); border-radius: 4px; padding: 6px 9px; font-size: 13px; white-space: nowrap; box-shadow: 0 4px 14px rgba(0,0,0,.18); }
  .tip .t { color: var(--ink-soft); }
  /* Team view: the stamp is the one loud element on the page. */
  .team-head { display: flex; flex-wrap: wrap; align-items: center; gap: 16px 28px; }
  .stamp { width: 112px; height: 112px; border: 4px solid var(--stamp); color: var(--stamp); border-radius: 50%; display: grid; place-items: center; font-size: 46px; font-weight: 900; letter-spacing: -0.02em; transform: rotate(-8deg); flex: none; }
  .stamp.inc { font-size: 26px; }
  .team-title h2 { font-size: 30px; font-weight: 800; letter-spacing: -0.02em; }
  .team-title .gm { color: var(--ink-soft); font-size: 15px; }
  .team-title select { margin-top: 10px; font: inherit; color: var(--ink); background: var(--paper); border: 1px solid var(--line-strong); border-radius: 4px; padding: 6px 10px; max-width: 100%; }
  .figures { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 9rem), 1fr)); gap: 0 24px; margin: 22px 0 6px; border-top: 1px solid var(--line); }
  .figures div { padding: 10px 0; border-bottom: 1px solid var(--line); }
  .figures .l { color: var(--ink-soft); font-size: 13px; }
  .figures .v { font-size: 26px; font-weight: 700; letter-spacing: -0.01em; font-variant-numeric: tabular-nums; }
  .tops { margin: 14px 0 20px; color: var(--ink-soft); font-size: 14px; }
  .tops b { color: var(--ink); font-weight: 600; }
  .empty { color: var(--ink-soft); padding: 16px 0; }
  .method p { margin-bottom: 10px; }
  .method b { font-weight: 700; }
  .cut { max-width: 20rem; margin-top: 10px; }
  .foot { margin-top: 48px; padding-top: 14px; border-top: 1px solid var(--line); color: var(--ink-soft); font-size: 13px; }
  :focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>HLM27 GM report cards</h1>
    <p class="lede">Every GM graded on the trade value they took in versus sent out, across <b id="n-trades"></b> GM-to-GM trades from <b id="d-first"></b> to <b id="d-last"></b>. Click a team to see every entry and exit.</p>
    <p class="meta">Through the league save of <span id="as-of"></span>. Updated <span id="built"></span>. <a id="dl" href="#" download="hlm27_trade_ledger.csv">Download the full ledger (CSV)</a>.</p>
  </header>

  <section id="cards">
    <div class="head"><h2>Report cards</h2><span class="note">Ranked by Edge, the value won as a share of value moved. Click a header to sort.</span></div>
    <div class="scroll">
      <table id="cards-table">
        <thead><tr>
          <th class="num sortable" data-sort="rank">Rank</th>
          <th class="sortable" data-sort="team">Team</th>
          <th class="sortable" data-sort="edge">Grade</th>
          <th class="num sortable" data-sort="trades">Trades</th>
          <th class="num sortable" data-sort="wins">W</th>
          <th class="num sortable" data-sort="losses">L</th>
          <th class="num sortable" data-sort="evens">E</th>
          <th class="num sec sortable" data-sort="win_pct">Win %</th>
          <th class="num sec">Players in</th><th class="num sec">Players out</th><th class="num sec">Picks in</th><th class="num sec">Picks out</th>
          <th class="num sec sortable" data-sort="value_in">Value in</th>
          <th class="num sec sortable" data-sort="value_out">Value out</th>
          <th class="num sortable" data-sort="net">Net</th>
          <th class="num sortable" data-sort="edge">Edge</th>
          <th class="sec">Biggest win</th><th class="sec">Biggest loss</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <section id="edge">
    <div class="head"><h2>Edge by team</h2><span class="note">Blue took in more value than it sent; red the reverse. Hover a bar for the record.</span></div>
    <div class="chart" id="edge-chart"></div>
  </section>

  <section id="team">
    <div class="head"><h2>Team view</h2><span class="note">Share a team's card with the link in your address bar.</span></div>
    <div class="team-head">
      <div class="stamp" id="t-stamp"></div>
      <div class="team-title">
        <h2 id="t-name"></h2>
        <div class="gm" id="t-gm"></div>
        <select id="t-pick" aria-label="Team"></select>
      </div>
    </div>
    <div class="figures">
      <div><div class="l">Rank</div><div class="v" id="t-rank"></div></div>
      <div><div class="l">Trades</div><div class="v" id="t-trades"></div></div>
      <div><div class="l">Wins</div><div class="v" id="t-wins"></div></div>
      <div><div class="l">Losses</div><div class="v" id="t-losses"></div></div>
      <div><div class="l">Even</div><div class="v" id="t-evens"></div></div>
      <div><div class="l">Value in</div><div class="v" id="t-vin"></div></div>
      <div><div class="l">Value out</div><div class="v" id="t-vout"></div></div>
      <div><div class="l">Net value</div><div class="v" id="t-net"></div></div>
      <div><div class="l">Edge</div><div class="v" id="t-edge"></div></div>
    </div>
    <div class="tops">Top player acquired: <b id="t-topin"></b><br>Top player sent: <b id="t-topout"></b></div>
    <p class="note">Trade by trade, newest first. Players show their current overall and age.</p>
    <p class="empty" id="t-empty" hidden>No trades yet this season.</p>
    <div class="scroll">
      <table id="trades-table">
        <thead><tr><th>Date</th><th>Partner</th><th>Entries (received)</th><th>Exits (sent)</th><th class="num">Value in</th><th class="num">Value out</th><th class="num">Net</th><th>Result</th><th class="sec">Note</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <section id="method" class="method">
    <div class="head"><h2>How the grades work</h2></div>
    <p><b>Source.</b> The league save's trade history (every GM-to-GM trade since the season opened), plus trades posted in Discord after the latest save, numbered D#n. AI trades in the game's other leagues are left out.</p>
    <p><b>Value.</b> The game's own trade valuation of each side at the time of the deal, as the save records it. Value in is what a team received; value out is what it sent. A trade is a Win or a Loss for a team only when the gap is more than <b id="m-band"></b> of the value moved; inside that band it is Even, a deal both sides' AI GMs would accept. Even trades count as neither a win nor a loss, but their value still counts toward Edge. For Discord-posted trades the save has no recorded value, so picks use the save's pick values and players use the save's player values plus 5%, which is how the game's recorded values ran across recent trades.</p>
    <p><b>Edge.</b> (value in − value out) ÷ (value in + value out): value won as a share of value moved, so a busy GM and a quiet one compare fairly. The grade comes from Edge using the cutoffs below. A team needs at least <b id="m-min"></b> trades for a grade (fewer shows INC) and <b id="m-full"></b> for a full grade; in between, the grade carries an asterisk.</p>
    <p><b>Combined trades.</b> The game allows at most 5 assets per side in one trade, so bigger deals get entered as several trades on the same day between the same two teams. Those are combined into one deal here and graded as a whole; their trade number joins the parts, like 3844+3845+3846.</p>
    <p><b>What it measures.</b> Asset value, not whether a trade helped a team win. Cap dumps, rentals and win-now veterans for young talent count as value lost. Where a team took picks to retain salary, that shows as value won, since the game does not price the cap cost. Three-team trades are split per asset by estimate. Players are shown with their overall and age as of the latest save, not at trade time.</p>
    <table class="cut"><thead><tr><th class="num">Minimum Edge</th><th>Grade</th></tr></thead><tbody id="cut-body"></tbody></table>
  </section>

  <footer class="foot">Calgary Flames front office, HLM27 sim league. Grades are a measure of trade value, not of who built the better team.</footer>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
(() => {
  const D = JSON.parse(document.getElementById('data').textContent);
  const MIN = D.minTrades, FULL = D.fullTrades;
  const $ = (id) => document.getElementById(id);
  const fmtInt = (n) => Number(n).toLocaleString('en-US');
  const fmtNet = (n) => (n > 0 ? '+' : n < 0 ? '−' : '') + fmtInt(Math.abs(n));
  const fmtPct = (v) => (v * 100).toFixed(1) + '%';
  const fmtEdge = (v) => (v > 0 ? '+' : v < 0 ? '−' : '') + (Math.abs(v) * 100).toFixed(1) + '%';
  const fmtDate = (s) => new Date(s + 'T00:00:00Z').toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'});
  const gradeClass = (g) => 'grade g-' + (/^[A-F]/.test(g) ? g[0].toLowerCase() : 'x');

  // ---- Cards, computed from the ledger (same arithmetic as the workbook) ----
  const item = /^(.+?) \((\d+), (\d+)\)(.*)$/;
  const parts = (t) => String(t || '').split('; ').filter((p) => p && p !== '—');
  const head = (text) => {
    let best = null;
    for (const p of parts(text)) { const m = item.exec(p); if (m && (!best || +m[2] > best.ovr)) best = {ovr: +m[2], name: m[1]}; }
    if (best) return best.name;
    const pick = parts(text).find((p) => /^\d{4} R\d/.test(p));
    return pick || parts(text)[0] || '—';
  };
  const top = (text) => {
    let best = null;
    for (const p of parts(text)) { const m = item.exec(p); if (m && (!best || +m[2] > best.ovr)) best = {ovr: +m[2], desc: p}; }
    return best;
  };
  const by = {};
  const blank = (code, name, gm) => ({team: code, name, gm, trades: 0, wins: 0, losses: 0, evens: 0, players_in: 0, players_out: 0, picks_in: 0, picks_out: 0, value_in: 0, value_out: 0, best: null, worst: null, top_in: null, top_out: null});
  for (const t of D.teams) by[t.team] = blank(t.team, t.name, t.gm || '');
  for (const r of D.ledger) {
    const t = by[r.team] || (by[r.team] = blank(r.team, r.team, ''));
    const vin = +r.value_in, vout = +r.value_out, net = vin - vout;
    t.trades++; if (r.result === 'Win') t.wins++; else if (r.result === 'Loss') t.losses++; else t.evens++;
    t.players_in += +r.players_in; t.players_out += +r.players_out; t.picks_in += +r.picks_in; t.picks_out += +r.picks_out;
    t.value_in += vin; t.value_out += vout;
    const tag = r.date + ' vs ' + r.partner + ': got ' + head(r.entries) + ', sent ' + head(r.exits);
    if (!t.best || net > t.best.net) t.best = {net, tag};
    if (!t.worst || net < t.worst.net) t.worst = {net, tag};
    const ti = top(r.entries); if (ti && (!t.top_in || ti.ovr > t.top_in.ovr)) t.top_in = {ovr: ti.ovr, text: ti.desc + ' (' + r.date + ' vs ' + r.partner + ')'};
    const to = top(r.exits); if (to && (!t.top_out || to.ovr > t.top_out.ovr)) t.top_out = {ovr: to.ovr, text: to.desc + ' (' + r.date + ' vs ' + r.partner + ')'};
  }
  const cuts = D.cutoffs.map((c) => ({min: +c.min_edge, grade: c.grade})).sort((a, b) => a.min - b.min);
  const cards = Object.values(by).map((t) => {
    const moved = t.value_in + t.value_out, edge = moved > 0 ? (t.value_in - t.value_out) / moved : null;
    let grade = '-';
    if (t.trades > 0 && t.trades < MIN) grade = 'INC';
    else if (t.trades >= MIN) { let g = cuts[0].grade; for (const c of cuts) if (edge >= c.min) g = c.grade; grade = g + (t.trades < FULL ? '*' : ''); }
    return {...t, grade, edge, rank: null, net: t.value_in - t.value_out, win_pct: t.trades ? t.wins / t.trades : null,
      biggest_win: t.best ? t.best.tag : '', biggest_loss: t.worst ? t.worst.tag : '', top_in: t.top_in ? t.top_in.text : '', top_out: t.top_out ? t.top_out.text : ''};
  });
  const graded = cards.filter((r) => r.trades >= MIN);
  for (const r of graded) r.rank = graded.filter((o) => o.edge > r.edge).length + 1;
  cards.sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99) || b.trades - a.trades || a.team.localeCompare(b.team));
  const cardOf = (code) => cards.find((c) => c.team === code);

  // ---- Header ----
  const ids = new Set(D.ledger.map((r) => r.trade)), dates = D.ledger.map((r) => r.date).sort();
  $('n-trades').textContent = fmtInt(ids.size); $('d-first').textContent = fmtDate(dates[0]); $('d-last').textContent = fmtDate(dates[dates.length - 1]);
  $('as-of').textContent = fmtDate(D.asOf); $('built').textContent = fmtDate(D.built);
  $('m-min').textContent = MIN; $('m-band').textContent = Math.round(D.evenBand * 100) + '%'; $('m-full').textContent = FULL;
  const csvCell = (v) => { const s = String(v ?? ''); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const cols = ['date', 'trade', 'team', 'partner', 'entries', 'exits', 'players_in', 'players_out', 'picks_in', 'picks_out', 'value_in', 'value_out', 'net', 'result', 'note'];
  $('dl').href = URL.createObjectURL(new Blob(['\ufeff' + [cols.join(','), ...D.ledger.map((r) => cols.map((c) => csvCell(r[c])).join(','))].join('\r\n')], {type: 'text/csv'}));

  // ---- State: the picked team lives in the URL hash ----
  const valid = (c) => c && by[c] ? c : null;
  let picked = valid((location.hash || '').replace(/^#/, '').toUpperCase()) || 'CGY';
  let sort = {key: 'rank', dir: 1};
  const pick = (code, scroll) => {
    picked = code; history.replaceState(null, '', '#' + code);
    render();
    if (scroll) $('team').scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
  };
  addEventListener('hashchange', () => { const c = valid(location.hash.slice(1).toUpperCase()); if (c && c !== picked) { picked = c; render(); } });

  const cell = (tr, text, cls) => { const td = document.createElement('td'); td.textContent = text; if (cls) td.className = cls; tr.appendChild(td); return td; };

  // ---- Report cards table ----
  for (const th of document.querySelectorAll('#cards-table th.sortable')) th.addEventListener('click', () => {
    const key = th.dataset.sort;
    if (sort.key === key) sort.dir = -sort.dir; else sort = {key, dir: key === 'rank' || key === 'team' ? 1 : -1};
    for (const h of document.querySelectorAll('#cards-table th.sortable')) h.setAttribute('aria-sort', h.dataset.sort === key ? (sort.dir > 0 ? 'ascending' : 'descending') : 'none');
    renderCards();
  });
  $('cards-table').addEventListener('click', (e) => { const row = e.target.closest('tr[data-team]'); if (row) pick(row.dataset.team, true); });
  const renderCards = () => {
    const tb = $('cards-table').tBodies[0]; tb.replaceChildren();
    const rows = cards.slice().sort((a, b) => {
      const av = a[sort.key], bv = b[sort.key];
      if (av == null && bv == null) return 0; if (av == null) return 1; if (bv == null) return -1;
      return (typeof av === 'string' ? av.localeCompare(bv) : av - bv) * sort.dir;
    });
    for (const r of rows) {
      const tr = document.createElement('tr'); tr.dataset.team = r.team; tr.className = 'pick' + (r.team === picked ? ' me' : ''); tr.tabIndex = 0;
      tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') pick(r.team, true); });
      cell(tr, r.rank == null ? '' : r.rank, 'num');
      cell(tr, r.team + (r.gm ? ' (' + r.gm + ')' : ''));
      const g = cell(tr, ''); const s = document.createElement('span'); s.className = gradeClass(r.grade); s.textContent = r.grade; g.appendChild(s);
      cell(tr, r.trades, 'num'); cell(tr, r.wins, 'num'); cell(tr, r.losses, 'num'); cell(tr, r.evens, 'num');
      cell(tr, r.win_pct == null ? '' : fmtPct(r.win_pct), 'num sec');
      cell(tr, r.players_in, 'num sec'); cell(tr, r.players_out, 'num sec'); cell(tr, r.picks_in, 'num sec'); cell(tr, r.picks_out, 'num sec');
      cell(tr, fmtInt(r.value_in), 'num sec'); cell(tr, fmtInt(r.value_out), 'num sec');
      cell(tr, r.trades ? fmtNet(r.net) : '', 'num ' + (r.net > 0 ? 'win' : r.net < 0 ? 'loss' : 'even'));
      cell(tr, r.edge == null ? '' : fmtEdge(r.edge), 'num');
      cell(tr, r.biggest_win, 'tag sec'); cell(tr, r.biggest_loss, 'tag sec');
      tb.appendChild(tr);
    }
  };

  // ---- Edge chart ----
  const NS = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs, text) => { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (text != null) n.textContent = text; return n; };
  const renderChart = () => {
    const box = $('edge-chart'); box.replaceChildren();
    const rows = cards.filter((r) => r.trades > 0 && r.edge != null).slice().sort((a, b) => b.edge - a.edge);
    const W = Math.max(320, box.clientWidth), rowH = 20, mTop = 6, mBot = 28, mRight = 60, H = mTop + rowH * rows.length + mBot;
    const svg = el('svg', {viewBox: '0 0 ' + W + ' ' + H, width: '100%', role: 'img', 'aria-label': 'Edge by team, as bars'}); box.appendChild(svg);
    const probe = el('text', {'font-size': 12}, ''); svg.appendChild(probe);
    let mLeft = 0; for (const r of rows) { probe.textContent = r.team; mLeft = Math.max(mLeft, probe.getComputedTextLength()); } probe.remove(); mLeft = Math.ceil(mLeft) + 10;
    const lo = Math.min(0, ...rows.map((r) => r.edge)), hi = Math.max(0, ...rows.map((r) => r.edge));
    const step = 0.1, dLo = Math.floor(lo / step) * step, dHi = Math.ceil(hi / step) * step;
    const x = (v) => mLeft + (v - dLo) / (dHi - dLo) * (W - mLeft - mRight);
    const y = (i) => mTop + i * rowH;
    const axisY = mTop + rowH * rows.length;
    for (let v = dLo; v <= dHi + 1e-9; v += step) {
      svg.appendChild(el('line', {x1: x(v), x2: x(v), y1: mTop, y2: axisY, stroke: 'var(--line)', 'stroke-width': 1}));
      svg.appendChild(el('text', {x: x(v), y: axisY + 16, 'text-anchor': 'middle', 'font-size': 11, fill: 'var(--ink-soft)'}, (v > 0 ? '+' : '') + Math.round(v * 100) + '%'));
    }
    svg.appendChild(el('line', {x1: x(0), x2: x(0), y1: mTop, y2: axisY, stroke: 'var(--line-strong)'}));
    const tip = document.createElement('div'); tip.className = 'tip'; tip.hidden = true; const t1 = document.createElement('div'); t1.className = 't'; const t2 = document.createElement('div'); tip.append(t1, t2); box.appendChild(tip);
    rows.forEach((r, i) => {
      const me = r.team === picked;
      svg.appendChild(el('text', {x: mLeft - 6, y: y(i) + rowH / 2, dy: '0.35em', 'text-anchor': 'end', 'font-size': 12, 'font-weight': me ? 700 : 400, fill: me ? 'var(--ink)' : 'var(--ink-soft)'}, r.team));
      const bar = el('rect', {x: Math.min(x(0), x(r.edge)), y: y(i) + 3, width: Math.max(1, Math.abs(x(r.edge) - x(0))), height: rowH - 6, rx: 2, fill: r.edge >= 0 ? 'var(--blue)' : 'var(--red)', opacity: me ? 1 : 0.55, style: 'cursor:pointer'});
      bar.addEventListener('pointermove', (e) => {
        t1.textContent = r.name + ' (' + r.team + ')' + (r.gm ? ', ' + r.gm : '') + ' · grade ' + r.grade;
        t2.textContent = r.wins + '-' + r.losses + '-' + r.evens + ' (W-L-E) in ' + r.trades + ' trades, net ' + fmtNet(r.net) + ', edge ' + fmtEdge(r.edge);
        tip.hidden = false; const b = box.getBoundingClientRect();
        tip.style.left = Math.max(0, Math.min(e.clientX - b.left + 12, box.clientWidth - tip.offsetWidth)) + 'px';
        tip.style.top = (e.clientY - b.top - tip.offsetHeight - 10) + 'px';
      });
      bar.addEventListener('pointerleave', () => { tip.hidden = true; });
      bar.addEventListener('click', () => pick(r.team, true));
      svg.appendChild(bar);
      svg.appendChild(el('text', {x: Math.max(x(0), x(r.edge)) + 4, y: y(i) + rowH / 2, dy: '0.35em', 'font-size': 11, fill: 'var(--ink-soft)'}, fmtEdge(r.edge)));
    });
  };

  // ---- Team view ----
  const sel = $('t-pick');
  sel.replaceChildren(...D.teams.map((t) => new Option(t.name + ' (' + t.team + ')', t.team)));
  sel.addEventListener('change', () => pick(sel.value, false));
  const renderTeam = () => {
    const r = cardOf(picked); sel.value = picked;
    const stamp = $('t-stamp'); stamp.textContent = r.grade; stamp.className = 'stamp' + (/^[A-F]/.test(r.grade) ? '' : ' inc');
    $('t-name').textContent = r.name + ' (' + r.team + ')';
    $('t-gm').textContent = r.gm ? 'GM: ' + r.gm : '';
    $('t-rank').textContent = r.rank == null ? '—' : r.rank + ' of ' + graded.length;
    $('t-trades').textContent = r.trades; $('t-wins').textContent = r.wins; $('t-losses').textContent = r.losses; $('t-evens').textContent = r.evens;
    $('t-vin').textContent = fmtInt(r.value_in); $('t-vout').textContent = fmtInt(r.value_out);
    const net = $('t-net'); net.textContent = r.trades ? fmtNet(r.net) : '—'; net.className = 'v ' + (r.net > 0 ? 'win' : r.net < 0 ? 'loss' : '');
    $('t-edge').textContent = r.edge == null ? '—' : fmtEdge(r.edge);
    $('t-topin').textContent = r.top_in || '—'; $('t-topout').textContent = r.top_out || '—';
    $('t-empty').hidden = r.trades > 0;
    const tb = $('trades-table').tBodies[0]; tb.replaceChildren();
    const rows = D.ledger.filter((x) => x.team === picked).sort((a, b) => b.date.localeCompare(a.date) || b.trade.localeCompare(a.trade));
    for (const x of rows) {
      const tr = document.createElement('tr');
      cell(tr, fmtDate(x.date)); cell(tr, x.partner); cell(tr, x.entries, 'text'); cell(tr, x.exits, 'text');
      cell(tr, fmtInt(x.value_in), 'num'); cell(tr, fmtInt(x.value_out), 'num');
      const n = +x.net; cell(tr, fmtNet(n), 'num ' + (n > 0 ? 'win' : n < 0 ? 'loss' : 'even'));
      cell(tr, x.result, x.result === 'Win' ? 'win' : x.result === 'Loss' ? 'loss' : 'even');
      cell(tr, x.note || '', 'text sec');
      tb.appendChild(tr);
    }
  };

  // ---- Cutoffs ----
  const cb = $('cut-body');
  for (const c of cuts.slice().reverse()) { const tr = document.createElement('tr'); cell(tr, c.min < -1 ? 'no floor' : fmtEdge(c.min), 'num'); cell(tr, c.grade); cb.appendChild(tr); }

  const render = () => { renderCards(); renderChart(); renderTeam(); };
  render();
  let tmr; addEventListener('resize', () => { clearTimeout(tmr); tmr = setTimeout(renderChart, 120); });
  if (location.hash && valid(location.hash.slice(1).toUpperCase())) $('team').scrollIntoView();
})();
</script>
</body>
</html>
"""

html = TEMPLATE.replace("__DATA__", payload)
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print(f"wrote {out}: {len(ledger)} ledger rows, {len({r['trade'] for r in ledger})} trades, {len(teams)} teams, through {data['asOf']}")
