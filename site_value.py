"""Team value: every team graded on the in-game value it gained or lost, phase by phase.

The numbers come from the value tool that sits beside the saves (../tools/value_grades.py --json): it values
every player and pick in every save, splits each team's change between saves by cause and grades each phase
on a curve against the league. Its data files hold league data only. Without the tool the page is skipped.
"""
import json
import os
import subprocess
import sys
import tempfile

import site_shell

FILES = ("periods", "teams", "grades", "breakdown", "items", "coverage")


def build(ctx):
    saves = os.path.abspath(ctx.saves_dir or os.path.dirname(os.path.abspath(ctx.path)))
    tool = os.path.join(os.path.dirname(saves), "tools", "value_grades.py")
    if not os.path.exists(tool):
        return None, f"the value tool isn't at {tool}"
    with tempfile.TemporaryDirectory() as tmp:
        run = subprocess.run([sys.executable, tool, "--saves", saves, "--json", tmp, "--out", os.path.join(tmp, "value-grades.md")],
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
        if run.returncode:
            return None, "the value tool failed: " + (run.stderr or run.stdout).strip().splitlines()[-1]
        d = {}
        for name in FILES:
            with open(os.path.join(tmp, name + ".json"), encoding="utf-8") as f:
                d[name] = json.load(f)
    data = dict(ctx.base(), periods=d["periods"], grades=d["grades"], breakdown=d["breakdown"], items=d["items"], coverage=d["coverage"],
                teams=[{"code": t["team"], "rank": t["rank"]} for t in d["teams"]])
    return site_shell.page("value", "PHL team value", "Every HLM27 team graded on the in-game value it gained or lost, phase by phase.", BODY, data, SCRIPT, CSS), \
        f"{len(d['teams'])} teams over {len(d['periods']) - 1} periods, from {len(d['coverage'])} saves"


CSS = """
  td.bar { width: 20%; min-width: 7rem; }
  .gv { color: var(--ink-soft); font-size: 13px; margin-left: 2px; }
  #phases tr.ph td { color: var(--ink-soft); font-size: 13px; }
  #phases tr.ph td:first-child { padding-left: 22px; }
  #phases tr.per td { font-weight: 600; }
  .items { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 22rem), 1fr)); gap: 4px 32px; }
  .items table td { white-space: normal; }
  .items td.v { white-space: nowrap; }
  .cover { max-width: 34rem; margin-top: 10px; }
"""

BODY = """
  <header>
    <h1>Team value</h1>
    <p class="lede">Every team graded on the in-game value it gained or lost, stretch by stretch, on a curve against the league. Click a team to see where its value came from.</p>
    <p class="meta">Through the league save of <span id="as-of"></span>. Updated <span id="built"></span>.</p>
  </header>

  <section id="grades">
    <div class="head"><h2>Grades</h2><span class="note">Value gained or lost, and its grade against the league. Click a header to sort; the bars follow.</span></div>
    <div class="scroll tall"><table id="grade-table"><thead></thead><tbody></tbody></table></div>
  </section>

  <section id="team">
    <div class="head"><h2>Team view</h2><span class="note">Share a team's card with the link in your address bar.</span></div>
    <div class="team-head">
      <div class="stamp" id="t-stamp"></div>
      <div class="team-title"><h2 id="t-name"></h2><div class="gm" id="t-sub"></div><select id="t-pick" aria-label="Team"></select></div>
    </div>
    <div class="figures">
      <div><div class="l">Rank</div><div class="v" id="t-rank"></div></div>
      <div><div class="l">Value gained</div><div class="v" id="t-total"></div></div>
      <div><div class="l">From moves</div><div class="v" id="t-moves"></div><div class="s" id="t-moves-g"></div></div>
      <div><div class="l">From development</div><div class="v" id="t-dev"></div></div>
    </div>
    <div class="scroll tall"><table id="phases"><thead></thead><tbody></tbody></table></div>
    <h3>Biggest items</h3>
    <div class="items" id="items"></div>
  </section>

  <section id="method" class="method">
    <div class="head"><h2>How the grades work</h2></div>
    <p><b>What it measures.</b> The change in a team's in-game value over each stretch of the league. Value is the game's own trade value, the number behind the trade screen, for every player whose rights a team holds: roster, minors, prospects and unsigned picks. Value given away by keeping salary in a trade is taken off.</p>
    <p><b>The curve.</b> Each stretch is graded against the other 31 teams, by how far a team's change sits from the league average. The average earns a B−; an A+ takes 1.6 standard deviations above it, and more than 1.6 below is an F. A stretch still running is marked so far, and its grades will move.</p>
    <p><b>Moves and development.</b> Moves are what a GM did: trades, the draft, free agency, re-signings and waivers. Development is what the players did: ratings going up or down, and the yearly rollovers. "Moves only" grades the first without the second.</p>
    <p><b>Picks.</b> Pick value isn't graded by itself. A pick counts when it is traded, at its value that day, or used: the player drafted is set against the value of the slot he was taken in. A pick that gains value because its team sinks in the standings earns nothing.</p>
    <p><b>Where things land.</b> Trades are valued just before they happen, without the 5% the trade screen adds to one side; what a player gains or loses after a trade is development for his new team. Contracts lose a year at the draft, which counts with the season rather than the draft. The summer rollover ages everyone a year and sits in the offseason.</p>
    <p><b>Estimates.</b> The game stores a player's value only when someone looks at him, so most saves hold few. A value comes from the save when it is stored there; otherwise it is copied from another save where the same player had the same rating, potential, contract and season; otherwise it is estimated from his own earlier value or from similar players.</p>
    <table class="cover" id="cover"><thead><tr><th>Save</th><th class="num">Players</th><th class="num">Stored</th><th class="num">Copied</th><th class="num">Estimated</th></tr></thead><tbody></tbody></table>
  </section>
"""

SCRIPT = r"""
  const P = D.periods, GROUPS = [['trades', 'Trades'], ['draft', 'Draft'], ['free_agency', 'Free agency'], ['re_signings', 'Re-signings'], ['waivers', 'Waivers'], ['development', 'Development']];
  const G = {};
  D.grades.forEach((r) => { (G[r.team] = G[r.team] || {})[r.period] = r; });
  const rows = D.teams.map((t) => { const o = {code: t.code, name: D.names[t.code] || t.code, rank: t.rank, moves: G[t.code].overall.moves};
    P.forEach((p) => { o[p.period] = G[t.code][p.period].total; }); return o; });
  const val = (v) => `<span class="${cls(v)}">${signed(v)}</span>`;
  const grade = (g) => `<span class="grade ${gradeCls(g)}">${g}</span>`;
  let picked = hashTeam() || 'CGY';

  const st = {k: 'overall', d: -1}, table = $('grade-table');
  table.tHead.innerHTML = '<tr><th class="num" data-k="rank" data-d="asc">Rank</th><th data-k="code" data-d="asc">Team</th>' +
    P.filter((p) => p.period !== 'overall').map((p) => `<th class="sec" data-k="${p.period}" title="${esc(p.description)}">${esc(p.label.replace(/ so far$/, ''))}${p.provisional ? ' <span class="soft">so far</span>' : ''}</th>`).join('') +
    '<th data-k="overall">Overall</th><th class="sec" aria-label="The sorted column as bars"></th><th data-k="moves" title="Trades, draft, free agency, re-signings and waivers, without development">Moves only</th></tr>';
  function drawGrades() {
    const k = st.k === 'rank' || st.k === 'code' ? 'overall' : st.k, max = Math.max(1, ...rows.map((r) => Math.abs(r[k])));
    table.tBodies[0].innerHTML = rows.slice().sort(by(st)).map((r) => { const g = G[r.code], v = r[k], w = (50 * Math.abs(v) / max).toFixed(1);
      return `<tr class="pick${r.code === picked ? ' me' : ''}" data-team="${r.code}" tabindex="0"><td class="num soft">${r.rank}</td><td><b>${r.code}</b> <span class="soft wide">${esc(r.name)}</span></td>` +
        P.filter((p) => p.period !== 'overall').map((p) => `<td class="sec">${grade(g[p.period].grade)}<span class="gv">${signed(g[p.period].total)}</span></td>`).join('') +
        `<td>${grade(g.overall.grade)}<span class="gv">${signed(g.overall.total)}</span></td>
         <td class="bar sec"><span class="dbar" title="${signed(v)}"><i class="${v >= 0 ? 'pos' : 'neg'}" style="${v >= 0 ? 'left' : 'right'}:50%;width:${w}%"></i><i class="zero" style="left:50%"></i></span></td>
         <td>${grade(g.overall.moves_grade)}<span class="gv">${signed(g.overall.moves)}</span></td></tr>`; }).join('');
  }
  sortable(table, st, drawGrades);
  const pickRow = (e) => { const tr = e.target.closest('tr[data-team]'); if (tr) { pick(tr.dataset.team); $('team').scrollIntoView({behavior: 'smooth'}); } };
  table.addEventListener('click', pickRow);
  table.addEventListener('keydown', (e) => { if (e.key === 'Enter') pickRow(e); });

  $('phases').tHead.innerHTML = '<tr><th>Stretch</th>' + GROUPS.map(([k, l]) => `<th class="num${k === 'waivers' || k === 're_signings' ? ' sec' : ''}">${l}</th>`).join('') + '<th class="num">Total</th><th>Grade</th></tr>';
  function drawTeam() {
    const g = G[picked], o = g.overall, t = rows.find((r) => r.code === picked);
    $('t-stamp').textContent = o.grade;
    $('t-name').textContent = t.name;
    $('t-sub').textContent = P.filter((p) => p.period !== 'overall').map((p) => p.label.replace(/ so far$/, '') + ' ' + g[p.period].grade).join(' · ');
    $('t-rank').innerHTML = t.rank + '<span class="soft">/' + rows.length + '</span>';
    $('t-total').innerHTML = val(o.total); $('t-moves').innerHTML = val(o.moves); $('t-moves-g').textContent = 'Moves only: ' + o.moves_grade; $('t-dev').innerHTML = val(o.development);
    const cells = (r) => GROUPS.map(([k]) => `<td class="num${k === 'waivers' || k === 're_signings' ? ' sec' : ''}">${r[k] ? signed(r[k]) : '<span class="soft">0</span>'}</td>`).join('');
    const body = [];
    P.forEach((p) => {
      const r = g[p.period];
      body.push(`<tr class="${p.period === 'overall' ? 'sum' : 'per'}"><td>${esc(p.label.replace(/ so far$/, ''))}${p.provisional ? ' <span class="soft">so far</span>' : ''}</td>${cells(r)}<td class="num">${val(r.total)}</td><td>${grade(r.grade)}</td></tr>`);
      const ph = D.breakdown.filter((b) => b.team === picked && b.period === p.period);
      if (ph.length > 1) ph.forEach((b) => body.push(`<tr class="ph"><td>${esc(b.label)}</td>${cells(b)}<td class="num">${signed(b.total)}</td><td></td></tr>`));
    });
    $('phases').tBodies[0].innerHTML = body.join('');
    $('items').innerHTML = P.filter((p) => p.period !== 'overall').map((p) => { const it = D.items.filter((i) => i.team === picked && i.period === p.period).sort((a, b) => a.rank - b.rank);
      return it.length ? `<div><table><thead><tr><th>${esc(p.label.replace(/ so far$/, ''))}</th><th class="num">Value</th></tr></thead><tbody>` +
        it.map((i) => `<tr><td><b>${esc(i.asset)}</b> <span class="soft">${esc(i.kind)}${i.note ? ', ' + esc(i.note) : ''}</span></td><td class="num v">${val(i.value)}</td></tr>`).join('') + '</tbody></table></div>' : ''; }).join('');
  }
  function pick(code) { picked = code; setHashTeam(code); $('t-pick').value = code; drawGrades(); drawTeam(); }
  fillTeams($('t-pick'), picked, D.names);
  $('t-pick').addEventListener('change', (e) => pick(e.target.value));
  addEventListener('hashchange', () => { const c = hashTeam(); if (c && c !== picked) pick(c); });
  $('cover').tBodies[0].innerHTML = D.coverage.map((c) => `<tr><td>${fmtDate(c.day)}</td><td class="num">${c.players.toLocaleString('en-CA')}</td><td class="num">${c.stored.toLocaleString('en-CA')}</td><td class="num">${c.copied.toLocaleString('en-CA')}</td><td class="num">${c.estimated.toLocaleString('en-CA')}</td></tr>`).join('');
  drawGrades(); drawTeam();
  if (hashTeam()) $('team').scrollIntoView();
"""
