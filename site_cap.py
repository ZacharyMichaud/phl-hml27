"""Cap board: every team's cap hit, space and commitments by season, from the newest save.

The game counts the NHL roster plus dead cap (salary kept in a trade, buyouts) and charges it by the day.
A signed extension sits inside the current contract and starts when it ends.
"""
import datetime

import site_pages as sp
import site_shell


def nhl_contract(p):
    c = p.get("Contract") or {}
    return c if c.get("Salaries") and not c.get("LeagueId") and (c["Salaries"][0] or 0) > 0 else None


def hits(c):
    """Cap hits from this season on. The game charges salary x Edit (its DailyCapHit x the season's days):
    Edit is 1 on most contracts and a little under on about a hundred from the opening rosters."""
    passed, edit = c.get("SeasonPassed") or 0, c.get("Edit") or 1
    return [round(c["Salaries"][passed + i] * edit) for i in range(c.get("Length") or 0) if passed + i < len(c["Salaries"])]


def clause(ctx, c):
    """(tag, hover text) for a contract's trade clause. Type 4 carries a no-trade list; 2 and 3 are full clauses."""
    cl = c.get("Clause")
    if not cl:
        return None
    year_now = (c.get("SeasonPassed") or 0) + 1
    later = cl.get("StartingYear", 1) - year_now
    when = f", from {ctx.season_label(later)}" if later > 0 else ""
    if cl.get("Type") == 4:
        teams = sorted(ctx.code.get(t, str(t)) for t in cl.get("Teams") or [] if t != -1)
        return ["NTC", (f"No-trade list of {len(teams)} teams: {', '.join(teams)}" if teams else "No-trade list, teams not picked yet") + when]
    return ["Clause", "No-move or full no-trade clause" + when]


def build(ctx):
    lg, ufa_age, ufa_seasons = ctx.lg, ctx.sl.get("REQUIRED_UFA_AGE", 27), ctx.sl.get("REQUIRED_UFA_SEASON_EXPERIENCE", 7)
    teams, most = [], 1
    for tid, code in sorted(ctx.code.items(), key=lambda kv: kv[1]):
        t = lg["TeamList"][str(tid)]
        players = []
        for pid, p in ctx.by_org[tid]:
            c = nhl_contract(p)
            if not c:
                continue
            now = hits(c)
            ext = c.get("Extension") or {}
            h = now + [round(s * (ext.get("Edit") or 1)) for s in (ext.get("Salaries") or [])[: ext.get("Length") or 0]]
            if not h:
                continue
            end = datetime.date(ctx.season0 + len(h), 7, 1)  # the July 1 the last signed season runs out
            rookie = (p.get("RookieSeason") or {}).get("0") or 0
            free = sp.age_on(p, end) >= ufa_age or (rookie and end.year - rookie >= ufa_seasons)
            row = {"n": sp.full_name(p), "pos": sp.positions(p), "age": sp.age_on(p, ctx.date), "o": sp.shown(p), "g": sp.group(p),
                   "c": "NHL" if p.get("TeamId") == tid else (ctx.league_of.get(p.get("TeamId")) or "Other"), "h": h, "e": "UFA" if free else "RFA"}
            if ext:
                row["x"] = len(now)
            k = clause(ctx, c)
            if k:
                row["k"] = k
            players.append(row)
            most = max(most, len(h))
        dead = []
        for c in t.get("DeadCapSpace") or []:
            h = hits(c)
            if h:
                who = ctx.PL.get(str(c.get("PlayerId")))
                dead.append({"n": sp.full_name(who) if who else c.get("PlayerName") or "?", "kind": "Salary kept in a trade" if c.get("IsRetainedContract") else "Buyout or carried over", "h": h})
                most = max(most, len(h))
        teams.append({"code": code, "accrued": t.get("AccumulatedSalaryCap") or 0, "players": players, "dead": dead})
    cfg = lg["ConfigOrDefault"]
    data = dict(ctx.base(), cap=lg["HardSalaryCap"], days=lg.get("SeasonDayId") or 0, length=cfg.get("SeasonLenght") or 187,
                seasons=[ctx.season_label(k) for k in range(most)], roster=ctx.sl.get("MAX_ON_ROSTER", 23), contracts=cfg.get("MaxContract", 50),
                faYear=ctx.season0 + 1, teams=teams)
    n = sum(len(t["players"]) for t in teams)
    return site_shell.page("cap", "PHL cap board", "Every team's cap hit, space and contracts by season in the HLM27 league.", BODY, data, SCRIPT, CSS), \
        f"{n} contracts on {len(teams)} teams, seasons through {data['seasons'][-1]}"


CSS = """
  .grid td:first-child, .grid th:first-child { position: sticky; left: 0; background: var(--ice); z-index: 1; }
  .grid th:first-child { z-index: 2; }
  .grid td.ext { font-style: italic; }
  .grid td.who { font-weight: 600; }
  @media (max-width: 760px) { .grid td.who { white-space: normal; min-width: 8.5rem; max-width: 12rem; } }
  .grid tr.sub td.who, .grid tr.out td.who { font-weight: 400; }
  .grid tr.out td { color: var(--ink-soft); }
  td.bar { width: 18%; min-width: 6rem; }
  .figures { grid-template-columns: repeat(auto-fit, minmax(min(100%, 8rem), 1fr)); }
"""

BODY = """
  <header>
    <h1>Cap board</h1>
    <p class="lede">Every team's cap hit, space and commitments, side by side. Click a team for its contracts year by year.</p>
    <p class="meta">Through the league save of <span id="as-of"></span>. Updated <span id="built"></span>. The cap is <b id="cap"></b>.</p>
  </header>

  <section id="league">
    <div class="head"><h2>League</h2><span class="note">Cap hit is the NHL roster plus dead cap. Click a header to sort.</span></div>
    <div class="scroll tall">
      <table id="cap-table">
        <thead><tr>
          <th data-k="code" data-d="asc">Team</th>
          <th class="num" data-k="hit">Cap hit</th>
          <th class="sec" aria-label="Share of the cap used"></th>
          <th class="num" data-k="space">Space</th>
          <th class="num" data-k="roster">Roster</th>
          <th class="num" data-k="contracts">Contracts</th>
          <th class="num sec" data-k="dead">Dead cap</th>
          <th class="num sec" data-k="pace">On pace for</th>
          <th class="num sec" data-k="next" id="h-next"></th>
          <th class="num sec" data-k="expiring">Expiring</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <section id="team">
    <div class="head"><h2>Team view</h2><span class="note">Share a team's cap sheet with the link in your address bar.</span></div>
    <div class="team-head"><div class="team-title"><h2 id="t-name"></h2><select id="t-pick" aria-label="Team"></select></div></div>
    <div class="figures">
      <div><div class="l">Cap hit today</div><div class="v" id="t-hit"></div></div>
      <div><div class="l">Space</div><div class="v" id="t-space"></div></div>
      <div><div class="l">Dead cap</div><div class="v" id="t-dead"></div></div>
      <div><div class="l">Charged so far</div><div class="v" id="t-acc"></div><div class="s" id="t-days"></div></div>
      <div><div class="l">On pace for</div><div class="v" id="t-pace"></div></div>
      <div><div class="l">NHL roster</div><div class="v" id="t-roster"></div></div>
      <div><div class="l">Contracts</div><div class="v" id="t-contracts"></div></div>
    </div>
    <p class="note">Cap hit by season. Italics are a signed extension. The tag after a player's last season is his status when it runs out.</p>
    <div class="scroll"><table class="grid" id="grid"><thead></thead><tbody></tbody></table></div>
  </section>

  <section id="fa">
    <div class="head"><h2 id="fa-title"></h2><span class="note">Every contract in its last season with no extension signed.</span></div>
    <div class="tools">
      <input type="search" id="q" placeholder="Search a player or team" aria-label="Search free agents" autocomplete="off">
      <span class="seg" id="fa-seg"><button type="button" data-v="" aria-pressed="true">All</button><button type="button" data-v="UFA" aria-pressed="false">UFA</button><button type="button" data-v="RFA" aria-pressed="false">RFA</button></span>
      <span class="note" id="fa-count" aria-live="polite"></span>
    </div>
    <div class="scroll">
      <table id="fa-table">
        <thead><tr>
          <th data-k="n" data-d="asc">Player</th><th data-k="team" data-d="asc">Team</th><th class="sec" data-k="c" data-d="asc">Club</th><th data-k="pos" data-d="asc">Pos</th>
          <th class="num" data-k="age">Age</th><th class="num" data-k="o">OVR</th><th class="num" data-k="hit">Cap hit</th><th data-k="e" data-d="asc">Status</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <section id="method" class="method">
    <div class="head"><h2>How to read it</h2></div>
    <p><b>Cap hit.</b> Every contract on a team's NHL roster, plus dead cap: salary it kept on a player it traded, and buyouts. Contracts in the minors, junior or Europe don't count, and neither do unsigned draft picks. Space is the cap less that total; a negative number is a team over the cap.</p>
    <p><b>By the day.</b> The game charges the cap one day at a time over the <span id="m-len"></span>-day season. "Charged so far" is the game's own running total for the team; "On pace for" adds today's roster for every day that is left.</p>
    <p><b>Later seasons.</b> What today's NHL roster and dead cap already commit, with signed extensions counted from the season they start. They are set against today's cap, since next season's cap isn't known yet.</p>
    <p><b>Free agents.</b> A player is unrestricted at <span id="m-age"></span> or after seven NHL seasons, restricted otherwise. That is worked out here from the league's free-agency settings, not read from the game, so treat a borderline case with care.</p>
    <p><b>Clauses.</b> NTC is a no-trade list; hover it for the teams. Clause is a no-move or a full no-trade clause.</p>
  </section>
"""

SCRIPT = r"""
  const cap = D.cap, Y = D.seasons.length, left = D.length - D.days;
  const sum = (list, y) => list.reduce((s, p) => s + (p.h[y] || 0), 0);
  const teams = D.teams.map((t) => {
    const ros = t.players.filter((p) => p.c === 'NHL');
    const hits = D.seasons.map((_, y) => sum(ros, y) + sum(t.dead, y));
    return Object.assign(t, { name: D.names[t.code] || t.code, ros, hits, hit: hits[0], space: cap - hits[0], dead0: sum(t.dead, 0), dead: t.dead,
      roster: ros.length, contracts: t.players.length, pace: t.accrued + hits[0] / D.length * left, next: hits[1] || 0,
      expiring: ros.filter((p) => p.h.length === 1).length });
  });
  const byCode = Object.fromEntries(teams.map((t) => [t.code, t]));
  $('cap').textContent = money(cap);
  $('h-next').textContent = (D.seasons[1] || '') + ' so far';
  $('m-len').textContent = D.length;
  $('m-age').textContent = 27;
  let picked = hashTeam() || 'CGY';

  // League table
  const st = {k: 'hit', d: -1}, table = $('cap-table');
  function drawLeague() {
    const rows = teams.map((t) => Object.assign({}, t, {dead: t.dead0})).sort(by(st));
    table.tBodies[0].innerHTML = rows.map((t) => {
      const used = Math.min(t.hit / cap, 1) * 100;
      return `<tr class="pick${t.code === picked ? ' me' : ''}" data-team="${t.code}" tabindex="0">
        <td><b>${t.code}</b> <span class="soft wide">${esc(t.name)}</span></td>
        <td class="num">${mil(t.hit)}</td>
        <td class="bar sec"><span class="meter" title="${used.toFixed(0)}% of the cap"><i class="${t.space < 0 ? 'red' : ''}" style="width:${used.toFixed(1)}%"></i></span></td>
        <td class="num ${t.space < 0 ? 'down' : ''}">${mil(t.space)}</td>
        <td class="num">${t.roster}<span class="soft">/${D.roster}</span></td>
        <td class="num">${t.contracts}<span class="soft">/${D.contracts}</span></td>
        <td class="num sec">${t.dead ? mil(t.dead) : '<span class="soft">0</span>'}</td>
        <td class="num sec ${t.pace > cap ? 'down' : ''}">${mil(t.pace)}</td>
        <td class="num sec">${mil(t.next)}</td>
        <td class="num sec">${t.expiring}</td></tr>`;
    }).join('');
  }
  sortable(table, st, drawLeague);
  const pickRow = (e) => { const tr = e.target.closest('tr[data-team]'); if (tr) { pick(tr.dataset.team); $('team').scrollIntoView({behavior: 'smooth'}); } };
  table.addEventListener('click', pickRow);
  table.addEventListener('keydown', (e) => { if (e.key === 'Enter') pickRow(e); });

  // Team view: one row per contract, one column per season
  const order = {F: 0, D: 1, G: 2};
  function line(p, n, out) {
    const cells = D.seasons.slice(0, n).map((_, y) => {
      if (y < p.h.length) return `<td class="num${p.x != null && y >= p.x ? ' ext' : ''}">${money(p.h[y])}</td>`;
      return y === p.h.length && p.e ? `<td class="num"><span class="tag">${p.e}</span></td>` : '<td></td>';
    }).join('');
    const k = p.k ? ` <span class="tag" title="${esc(p.k[1])}">${p.k[0]}</span>` : '';
    return `<tr${out ? ' class="out"' : ''}><td class="who">${esc(p.n)}${k}${out ? ` <span class="tag">${esc(p.c)}</span>` : ''}</td><td class="sec">${p.pos || ''}</td><td class="num sec">${p.age || ''}</td><td class="num sec">${p.o || ''}</td>${cells}</tr>`;
  }
  function drawTeam() {
    const t = byCode[picked];
    $('t-name').textContent = t.name;
    $('t-hit').textContent = mil(t.hit);
    $('t-space').textContent = mil(t.space); $('t-space').className = 'v ' + (t.space < 0 ? 'down' : '');
    $('t-dead').textContent = mil(t.dead0);
    $('t-acc').textContent = mil(t.accrued); $('t-days').textContent = D.days + ' of ' + D.length + ' days';
    $('t-pace').textContent = mil(t.pace);
    $('t-roster').innerHTML = t.roster + '<span class="soft">/' + D.roster + '</span>';
    $('t-contracts').innerHTML = t.contracts + '<span class="soft">/' + D.contracts + '</span>';
    const last = Math.max(1, ...t.players.map((p) => p.h.length + 1), ...t.dead.map((p) => p.h.length));
    const cols = D.seasons.slice(0, Math.min(Y, last));
    const sort = (a, b) => order[a.g] - order[b.g] || b.h[0] - a.h[0];
    const n = cols.length;
    const sub = (label) => `<tr class="sub"><td class="who" colspan="${4 + n}">${label}</td></tr>`;
    const out = t.players.filter((p) => p.c !== 'NHL').sort(sort);
    const total = (label, f, c) => `<tr class="sum"><td class="who">${label}</td><td class="sec"></td><td class="sec"></td><td class="sec"></td>${cols.map((_, y) => { const v = f(y); return t.hits[y] ? `<td class="num ${c && v < 0 ? 'down' : ''}">${mil(v)}</td>` : '<td></td>'; }).join('')}</tr>`;
    const body = [sub(`NHL roster (${t.ros.length})`), ...t.ros.slice().sort(sort).map((p) => line(p, n))];
    if (t.dead.length) body.push(sub('Dead cap'), ...t.dead.map((p) => line({n: p.n + ' · ' + p.kind.toLowerCase(), h: p.h}, n)));
    body.push(total('Counts against the cap', (y) => t.hits[y]), total('Space under today’s cap', (y) => cap - t.hits[y], true));
    if (out.length) body.push(sub(`Not counted: minors, junior, Europe (${out.length})`), ...out.map((p) => line(p, n, true)));
    const grid = $('grid');
    grid.tHead.innerHTML = `<tr><th>Player</th><th class="sec">Pos</th><th class="num sec">Age</th><th class="num sec">OVR</th>${cols.map((s) => `<th class="num">${s}</th>`).join('')}</tr>`;
    grid.tBodies[0].innerHTML = body.join('');
  }
  function pick(code) { picked = code; setHashTeam(code); $('t-pick').value = code; drawLeague(); drawTeam(); }
  fillTeams($('t-pick'), picked, D.names);
  $('t-pick').addEventListener('change', (e) => pick(e.target.value));
  addEventListener('hashchange', () => { const c = hashTeam(); if (c && c !== picked) pick(c); });

  // Free agents next summer
  const fa = [];
  teams.forEach((t) => t.players.forEach((p) => { if (p.h.length === 1) fa.push(Object.assign({team: t.code, hit: p.h[0]}, p)); }));
  $('fa-title').textContent = 'Free agents in ' + D.faYear;
  const fst = {k: 'o', d: -1};
  let want = '';
  function drawFa() {
    const q = $('q').value.trim().toLowerCase();
    const rows = fa.filter((p) => (!want || p.e === want) && (!q || (p.n + ' ' + p.team + ' ' + (D.names[p.team] || '')).toLowerCase().includes(q))).sort(by(fst));
    $('fa-count').textContent = rows.length + ' of ' + fa.length;
    $('fa-table').tBodies[0].innerHTML = rows.map((p) => `<tr><td><b>${esc(p.n)}</b></td><td>${p.team}</td><td class="sec">${esc(p.c)}</td><td>${p.pos}</td>
      <td class="num">${p.age}</td><td class="num">${p.o}</td><td class="num">${money(p.hit)}</td><td><span class="tag">${p.e}</span></td></tr>`).join('');
  }
  sortable($('fa-table'), fst, drawFa);
  $('q').addEventListener('input', drawFa);
  $('fa-seg').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; want = b.dataset.v;
    [...$('fa-seg').children].forEach((x) => x.setAttribute('aria-pressed', x === b)); drawFa(); });

  drawLeague(); drawTeam(); drawFa();
  if (hashTeam()) $('team').scrollIntoView();
"""
