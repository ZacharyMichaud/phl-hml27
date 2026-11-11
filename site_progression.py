"""Progression: every rating change in the league, tick by tick.

Ratings move on the 2nd of each month from November to March; the game mails each team its own changes
(ProgressionMailArgs: player, new overall, change, club, potential, motivation), and the mails stay in the save.
The summer rollover has no league-wide mail, so it is read off the two saves either side of it.
"""
import collections
import datetime

import site_pages as sp
import site_shell


def build(ctx):
    code = ctx.code
    states = ctx.states or []
    # Monthly ticks: every team's mail for a day, from whichever save still holds it.
    ticks = collections.defaultdict(dict)
    for mails in [s["mails"] for s in states] + [ctx.sl.get("Mails") or []]:
        for m in mails:
            a = m.get("Args") or {}
            if a.get("$type") == "ProgressionMailArgs" and a.get("TeamId") in code:
                ticks[(m.get("Date") or "")[:10]][a["TeamId"]] = a.get("Players") or []
    ticks = {d: t for d, t in ticks.items() if len(t) >= len(code) // 2}  # a lone mail is one team's summer report

    def who(pid):
        p = ctx.PL.get(pid)
        if p is None:
            p = next((s["players"][pid] for s in reversed(states) if pid in s["players"]), None)
        return p

    def season(day):
        y = int(day[:4]) - (int(day[5:7]) < 7)
        return f"{y}-{(y + 1) % 100:02d}"

    events, rows = [], []
    for day in sorted(ticks):
        date = datetime.date.fromisoformat(day)
        events.append({"id": day, "day": day, "season": season(day), "kind": "tick"})
        for tid, players in ticks[day].items():
            for x in players:
                pid = str(x["Item1"])
                p = who(pid)
                if not p or not x.get("Item3"):
                    continue
                club = "NHL" if x.get("Item4") == tid else (ctx.league_of.get(x.get("Item4")) or "Other")
                rows.append([day, code[tid], pid, sp.full_name(p), sp.positions(p), sp.age_on(p, date), club, x["Item2"], x["Item3"],
                             sp.potential(p, x.get("Item5") or 0), x.get("Item6") or 0, ""])
    # Summer rollovers: the last save of one season against the first of the next. Over the summer every signed
    # player sits on the NHL roster, so the club shown is the league he played most of the season before in.
    past = None

    def played(pid, year):
        games = collections.Counter()
        for s in past.get(pid) or []:
            if s.get("Season") == year and not s.get("Type"):  # no Type: a regular season
                games[str(s.get("League", 0))] += s.get("GamePlayed", 0)
        if not games:
            return ""
        lid = games.most_common(1)[0][0]
        return "NHL" if lid == "0" else ((ctx.sl["Leagues"].get(lid) or {}).get("Abbreviation") or "Other")

    for before, after in zip(states, states[1:]):
        if not before.get("year") or not after.get("year") or before["year"] == after["year"]:
            continue
        if past is None:
            past = sp.read_member(ctx.path, "pastathlete.hlm")["Stats"]
        day, date = after["day"], datetime.date.fromisoformat(after["day"])
        events.append({"id": f"summer-{after['year']}", "day": day, "season": season(day), "kind": "summer", "from": before["day"]})
        for pid, p in after["players"].items():
            tid, was = (p.get("TeamIds") or {}).get("0"), before["players"].get(pid)
            if tid not in code or not was:
                continue
            new, old = sp.overall(p), sp.overall(was)
            if new == old:
                continue
            changed = (was.get("_Potential") or 0) != (p.get("_Potential") or 0)
            rows.append([events[-1]["id"], code[tid], pid, sp.full_name(p), sp.positions(p), sp.age_on(p, date), played(pid, before["year"]), new, new - old,
                         sp.potential(p), p.get("_Motivation") or 0, sp.potential(was) if changed else ""])
    events.sort(key=lambda e: e["day"])
    data = dict(ctx.base(), events=events, rows=rows, teams=[{"code": c} for c in sorted(code.values())])
    summers = sum(1 for e in events if e["kind"] == "summer")
    note = "" if states else " (run from build_report_cards.py to add the summer rollover)"
    return site_shell.page("progression", "PHL progression", "Every rating change in the HLM27 league, tick by tick.", BODY, data, SCRIPT, CSS), \
        f"{len(rows)} rating changes over {len(events) - summers} monthly ticks and {summers} summer rollover{'s' if summers != 1 else ''}{note}"


CSS = """
  td.bar { width: 22%; min-width: 6rem; }
  .arrow { color: var(--ink-soft); }
  .was { color: var(--ink-soft); font-size: 12px; }
"""

BODY = """
  <header>
    <h1>Progression</h1>
    <p class="lede">Who got better, and when. Ratings move on the 2nd of each month from November to March, and once more over the summer.</p>
    <p class="meta">Through the league save of <span id="as-of"></span>. Updated <span id="built"></span>.</p>
    <div class="tools" style="margin-top:14px">
      <label for="when">When</label> <select id="when"></select>
      <label for="t-pick">Team</label> <select id="t-pick"></select>
    </div>
  </header>

  <section id="teams">
    <div class="head"><h2>By team</h2><span class="note" id="teams-note"></span></div>
    <div class="scroll tall">
      <table id="team-table">
        <thead><tr>
          <th data-k="code" data-d="asc">Team</th>
          <th class="num" data-k="pts" title="Rating points gained, less any lost">Points</th>
          <th class="sec" aria-label="Points gained"></th>
          <th class="num" data-k="n" title="Players whose rating moved">Players</th>
          <th class="num sec" data-k="nhl" title="Points gained by players on the NHL club">NHL club</th>
          <th class="num sec" data-k="rest" title="Points gained in the minors, junior, college and Europe">Elsewhere</th>
          <th class="sec">Biggest mover</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <section id="players">
    <div class="head"><h2>Players</h2><span class="note" id="players-note"></span></div>
    <div class="tools"><input type="search" id="q" placeholder="Search a player" aria-label="Search players" autocomplete="off"></div>
    <div class="scroll">
      <table id="player-table">
        <thead><tr>
          <th data-k="n" data-d="asc">Player</th><th data-k="t" data-d="asc">Team</th><th class="sec" data-k="c" data-d="asc">Club</th><th class="sec" data-k="pos" data-d="asc">Pos</th>
          <th class="num" data-k="age">Age</th><th class="num" data-k="a">Overall</th><th class="num" data-k="d">Change</th><th class="sec" data-k="pi" data-d="asc">Potential</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <section id="method" class="method">
    <div class="head"><h2>How it works</h2></div>
    <p><b>Monthly ticks.</b> On the 2nd of each month from November to March the game moves ratings, usually by a point or two, and tells each GM about his own players. Those reports stay in the league save, so this page lists every team's. A player needs room under his ceiling and games played to move; almost nobody 29 or older does.</p>
    <p><b>Summer.</b> The big step. Over the summer everyone ages a year: prospects can jump several points, and some players 34 and older lose a point or two. There is no league-wide report for it, so the summer rows compare each player's rating in the last save before the rollover with the first one after.</p>
    <p><b>Club.</b> Where the player was when his rating moved: the NHL club, or the league he was playing in. For the summer it is the league he played most of the season before in. Potential is his badge at that moment, in the game's colours.</p>
  </section>
"""

SCRIPT = r"""
  const F = ['e', 't', 'id', 'n', 'pos', 'age', 'c', 'a', 'd', 'p', 'm', 'was'];
  const TIERS = ['Franchise', 'Elite', 'Top 6 F', 'Top 4 D', 'Starter', 'Top 9 F', 'Top 6 D', 'Mid Starter', '4th line', '7th D', 'Backup', 'Depth', 'Minor', 'Semipro', 'Amateur'];
  const R = D.rows.map((r) => { const o = {}; F.forEach((k, i) => { o[k] = r[i]; }); o.pi = TIERS.indexOf(o.p); return o; });
  const label = (e) => e.kind === 'summer' ? 'Summer ' + e.day.slice(0, 4) : fmtDate(e.day);
  const seasons = [...new Set(D.events.map((e) => e.season))];
  const options = [];
  seasons.slice().reverse().forEach((s) => {
    const ev = D.events.filter((e) => e.season === s).reverse();
    options.push({v: 's:' + s, text: s + ', all of it', ids: ev.map((e) => e.id)});
    ev.forEach((e) => options.push({v: e.id, text: '  ' + label(e), ids: [e.id]}));
  });
  const latest = D.events[D.events.length - 1];
  $('when').innerHTML = options.map((o) => `<option value="${o.v}"${latest && o.v === latest.id ? ' selected' : ''}>${o.text}</option>`).join('');
  let team = hashTeam() || '';
  $('t-pick').innerHTML = '<option value="">All teams</option>' + D.teams.map((t) => `<option value="${t.code}"${t.code === team ? ' selected' : ''}>${t.code} · ${esc(D.names[t.code] || t.code)}</option>`).join('');

  // One row per player for the chosen span: changes added up, first rating to last.
  let rows = [];
  function collect() {
    const opt = options.find((o) => o.v === $('when').value) || options[0];
    if (!opt) { rows = []; return; }
    const order = Object.fromEntries(D.events.map((e, i) => [e.id, i])), ids = new Set(opt.ids), m = new Map();
    R.filter((r) => ids.has(r.e)).sort((a, b) => order[a.e] - order[b.e]).forEach((r) => {
      const k = r.id, o = m.get(k);
      if (!o) m.set(k, Object.assign({}, r, {from: r.a - r.d}));
      else Object.assign(o, {a: r.a, d: o.d + r.d, t: r.t, c: r.c, age: r.age, p: r.p, pi: r.pi, m: r.m, was: r.was || o.was});
    });
    rows = [...m.values()].filter((r) => r.d !== 0);
  }

  const ts = {k: 'pts', d: -1};
  function drawTeams() {
    const g = {};
    D.teams.forEach((t) => { g[t.code] = {code: t.code, pts: 0, n: 0, nhl: 0, rest: 0, top: null}; });
    rows.forEach((r) => { const t = g[r.t]; if (!t) return; t.pts += r.d; t.n += 1; if (r.c === 'NHL') t.nhl += r.d; else t.rest += r.d;
      if (!t.top || r.d > t.top.d || (r.d === t.top.d && r.a > t.top.a)) t.top = r; });
    const list = Object.values(g).sort(by(ts)), max = Math.max(1, ...list.map((t) => t.pts));
    $('team-table').tBodies[0].innerHTML = list.map((t) => `<tr class="pick${t.code === team ? ' me' : ''}" data-team="${t.code}" tabindex="0">
      <td><b>${t.code}</b> <span class="soft wide">${esc(D.names[t.code] || '')}</span></td><td class="num"><b>${signed(t.pts)}</b></td>
      <td class="bar sec"><span class="meter"><i class="blue" style="width:${Math.max(0, 100 * t.pts / max).toFixed(1)}%"></i></span></td>
      <td class="num">${t.n}</td><td class="num sec">${signed(t.nhl)}</td><td class="num sec">${signed(t.rest)}</td>
      <td class="sec">${t.top ? `${esc(t.top.n)} <span class="soft">${t.top.from}<span class="arrow"> → </span>${t.top.a}</span>` : ''}</td></tr>`).join('');
    const tot = rows.reduce((s, r) => s + r.d, 0);
    $('teams-note').textContent = `${rows.length.toLocaleString('en-CA')} players moved, ${signed(tot)} points in all. Click a team to see its players.`;
  }
  sortable($('team-table'), ts, drawTeams);

  const ps = {k: 'd', d: -1}, LIMIT = 400;
  function drawPlayers() {
    const q = $('q').value.trim().toLowerCase();
    const list = rows.filter((r) => (!team || r.t === team) && (!q || r.n.toLowerCase().includes(q))).sort((a, b) => by(ps)(a, b) || b.a - a.a || a.n.localeCompare(b.n));
    $('players-note').textContent = list.length > LIMIT ? `Showing ${LIMIT} of ${list.length.toLocaleString('en-CA')}. Pick a team or search to narrow it.` : `${list.length.toLocaleString('en-CA')} players`;
    $('player-table').tBodies[0].innerHTML = list.slice(0, LIMIT).map((r) => `<tr><td><b>${esc(r.n)}</b></td><td>${r.t}</td><td class="sec">${esc(r.c) || '<span class="soft">–</span>'}</td><td class="sec">${r.pos}</td>
      <td class="num">${r.age}</td><td class="num"><span class="soft">${r.from}<span class="arrow"> → </span></span><b>${r.a}</b></td><td class="num ${cls(r.d)}"><b>${signed(r.d)}</b></td>
      <td class="sec"><span class="pot m${r.m}">${esc(r.p)}</span>${r.was ? ` <span class="was">was ${esc(r.was)}</span>` : ''}</td></tr>`).join('') ||
      '<tr><td colspan="8" class="empty">Nobody moved.</td></tr>';
  }
  sortable($('player-table'), ps, drawPlayers);

  function drawAll() { collect(); drawTeams(); drawPlayers(); }
  function pick(code) { team = code; $('t-pick').value = code; history.replaceState(null, '', code ? '#' + code : location.pathname + location.search); drawTeams(); drawPlayers(); }
  $('when').addEventListener('change', drawAll);
  $('t-pick').addEventListener('change', (e) => pick(e.target.value));
  $('q').addEventListener('input', drawPlayers);
  const pickRow = (e) => { const tr = e.target.closest('tr[data-team]'); if (tr) { pick(tr.dataset.team === team ? '' : tr.dataset.team); $('players').scrollIntoView({behavior: 'smooth'}); } };
  $('team-table').addEventListener('click', pickRow);
  $('team-table').addEventListener('keydown', (e) => { if (e.key === 'Enter') pickRow(e); });
  addEventListener('hashchange', () => { const c = hashTeam() || ''; if (c !== team) pick(c); });
  drawAll();
"""
