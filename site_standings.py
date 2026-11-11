"""Standings: the table, what sits under it (shot share, luck, special teams) and the playoff race.

Everything comes from the newest save's game list: every regular-season game played, with its score, shots,
shot attempts, faceoffs and overtime flag, and every game still to play.

The race is a simulation. A team's strength starts from its lineup and is pulled toward its results as
games pile up; each game left is then played SIMS times. The constants come from fit_race_model.py,
last run on the saves through Nov 2, 2027: 4,907 game predictions (2026-27 from six points in the season,
the start of 2027-28 from opening night), log-loss 0.674 against 0.693 for a coin flip. On 2026-27 the
lineups alone called games better than the results to date did (0.676 against 0.687), so results only
nudge the lineup number. Refit once a season and paste the constants here.
"""
import math
import random
import statistics

import site_pages as sp
import site_shell

# Goals per game a lineup is worth for each point of overall above the league average: forwards, defence, starter.
BETA = (0.336, 0.089, 0.026)
PRIOR_SD = 0.266   # how far a team's true level sat from its lineup number, in goals per game
GAME_VAR = 7.31    # variance of one game's goal difference
HOME, SLOPE = 0.05, 0.55  # log-odds of a home win: HOME + SLOPE x the strength gap in goals per game
OT_SHARE = 0.156   # share of games that go to overtime
SIMS = 10000


def raw_overall(p):
    """A player's overall before rounding."""
    g = sp.group(p)
    if g == "G":
        return p.get("BaseDefense", 0)
    w = sp.OVR_WEIGHTS.get((g, p.get("_PlayerType") or 0), 50)
    return (w * p.get("BaseOffense", 0) + (100 - w) * p.get("BaseDefense", 0)) / 100


def build(ctx):
    lg, PL = ctx.lg, ctx.PL
    T = {int(k): t for k, t in lg["TeamList"].items()}
    ids = sorted(T, key=lambda t: ctx.code[t])
    ix = {t: i for i, t in enumerate(ids)}
    n = len(ids)
    games = [g for g in lg["SaveGames"] if not g.get("_StatType") and not g.get("Playoffs")]
    played = sorted((g for g in games if "WinnerID" in g), key=lambda g: (g["DateTime"], g["Id"]))
    todo = [g for g in games if "WinnerID" not in g]

    rows = [{"code": ctx.code[t], "conf": T[t].get("Conference", 0), "div": T[t].get("Division", 0), "gp": 0, "w": 0, "l": 0, "otl": 0, "otw": 0,
             "gf": 0, "ga": 0, "sf": 0, "sa": 0, "cf": 0, "ca": 0, "fw": 0, "fl": 0, "home": [0, 0, 0], "away": [0, 0, 0], "one": [0, 0, 0], "log": []} for t in ids]
    faced = [[] for _ in ids]
    for g in played:
        h, a = ix[g["HomeID"]], ix[g["AwayID"]]
        sh, sa, ot = g.get("ScoreHome", 0), g.get("ScoreAway", 0), bool(g.get("OT"))
        for me, opp, gf, ga, side, k in ((h, a, sh, sa, "home", "Home"), (a, h, sa, sh, "away", "Away")):
            r, other = rows[me], "Away" if k == "Home" else "Home"
            res = 0 if gf > ga else (2 if ot else 1)  # win, loss, overtime loss
            r["gp"] += 1
            r[("w", "l", "otl")[res]] += 1
            r["otw"] += ot and res == 0
            r["gf"] += gf; r["ga"] += ga
            r["sf"] += g["Shot" + k]; r["sa"] += g["Shot" + other]
            r["cf"] += g["ShotAttemps" + k]; r["ca"] += g["ShotAttemps" + other]
            r["fw"] += g["FaceoffWin" + k]; r["fl"] += g["FaceoffWin" + other]
            r[side][res] += 1
            if abs(gf - ga) == 1:
                r["one"][res] += 1
            r["log"].append(res)
            faced[me].append(opp)
    for t, r in zip(ids, rows):
        s = T[t].get("Stats") or {}
        r["pts"] = 2 * r["w"] + r["otl"]
        r["l10"] = [r["log"][-10:].count(k) for k in (0, 1, 2)]
        last = r["log"][-1] if r["log"] else None
        run = next((i for i, x in enumerate(reversed(r["log"])) if x != last), len(r["log"]))
        r["strk"] = ("W", "L", "OT")[last] + str(run) if last is not None else ""
        r["ppg"], r["ppo"], r["pkga"], r["pko"] = s.get("PowerPlayGoal", 0), s.get("PowerPlay", 0), s.get("PenaltyKillGoalAgainst", 0), s.get("PenaltyKill", 0)
        del r["log"]

    # Strength: the lineup's number, then pulled toward the goal difference so far.
    line = []
    for t in ids:
        lu = T[t].get("LineUp") or {}
        f = [raw_overall(PL[str(i)]) for i in lu.get("ForwardsIds") or [] if str(i) in PL]
        d = [raw_overall(PL[str(i)]) for i in lu.get("DefensesIds") or [] if str(i) in PL]
        g = [raw_overall(PL[str(i)]) for i in lu.get("GoaliesIds") or [] if str(i) in PL]
        line.append((statistics.mean(f) if f else 0, statistics.mean(d) if d else 0, g[0] if g else 0))
    avg = [statistics.mean(x[c] for x in line) for c in range(3)]
    prior = [sum(BETA[c] * (x[c] - avg[c]) for c in range(3)) for x in line]
    mean, sd = [], []
    for i, r in enumerate(rows):
        prec = 1 / PRIOR_SD ** 2 + r["gp"] / GAME_VAR
        mean.append((prior[i] / PRIOR_SD ** 2 + (r["gf"] - r["ga"]) / GAME_VAR) / prec)
        sd.append(math.sqrt(1 / prec))

    # The race: play out what's left.
    sched = [(ix[g["HomeID"]], ix[g["AwayID"]]) for g in todo]
    confs = {}
    for i, r in enumerate(rows):
        confs.setdefault(r["conf"], {}).setdefault(r["div"], []).append(i)
    cfg = lg["ConfigOrDefault"]
    odds = [o / 1000 for o in cfg.get("LotteryOdds") or []]
    reach = (cfg.get("LotteryMaxMoveUp") or 10) + 1  # the lowest lottery seed that can still move up to first
    lot = [o if r < reach else 0.0 for r, o in enumerate(odds)]
    if lot:
        lot[0] += sum(odds[reach:])  # a winner seeded too low to reach first leaves the pick with the last-place team
    rng = random.Random(int(ctx.day.replace("-", "")))
    pts0, w0 = [r["pts"] for r in rows], [r["w"] for r in rows]
    made, div_won, first, finals = [0] * n, [0] * n, [0.0] * n, [[] for _ in range(n)]
    edge = math.exp(-HOME)
    for _ in range(SIMS if sched else 1):
        e = [math.exp(SLOPE * rng.gauss(mean[i], sd[i])) for i in range(n)]
        pts, wins = pts0[:], w0[:]
        for h, a in sched:
            if rng.random() * (e[h] + edge * e[a]) < e[h]:
                w, l = h, a
            else:
                w, l = a, h
            pts[w] += 2
            wins[w] += 1
            if rng.random() < OT_SHARE:
                pts[l] += 1
        key = [pts[i] * 1000 + wins[i] + rng.random() for i in range(n)]  # points, then wins, then a coin flip
        out = []
        for divs in confs.values():
            rest = []
            for div in divs.values():
                order = sorted(div, key=key.__getitem__, reverse=True)
                div_won[order[0]] += 1
                for i in order[:3]:
                    made[i] += 1
                rest += order[3:]
            rest.sort(key=key.__getitem__, reverse=True)
            for i in rest[:2]:
                made[i] += 1
            out += rest[2:]
        out.sort(key=key.__getitem__)
        for r, i in enumerate(out):
            if r < len(lot):
                first[i] += lot[r]
        for i in range(n):
            finals[i].append(pts[i])
    sims = SIMS if sched else 1
    left = [[] for _ in ids]
    home_left = [0] * n
    for h, a in sched:
        left[h].append(a)
        left[a].append(h)
        home_left[h] += 1
    for i, r in enumerate(rows):
        f = sorted(finals[i])
        r.update(str=round(mean[i], 2), lineup=round(prior[i], 2), proj=round(statistics.mean(f), 1), lo=f[int(0.1 * (len(f) - 1))], hi=f[int(0.9 * (len(f) - 1))],
                 po=round(100 * made[i] / sims, 1), dv=round(100 * div_won[i] / sims, 1), first=round(100 * first[i] / sims, 1),
                 left=len(left[i]), homeLeft=home_left[i],
                 sosLeft=round(statistics.mean(mean[j] for j in left[i]), 2) if left[i] else 0,
                 sosPlayed=round(statistics.mean(mean[j] for j in faced[i]), 2) if faced[i] else 0)
    data = dict(ctx.base(), teams=rows, confs=[c.get("Name", "") for c in lg["Conferences"]], divs=[d.get("Name", "") for d in lg["Divisions"]],
                played=len(played), left=len(todo), sims=sims, season=ctx.season_label(), ot=round(100 * OT_SHARE, 1),
                lottery=[round(100 * x, 1) for x in lot])
    return site_shell.page("standings", "PHL standings", "Standings, shot share, luck and the playoff race in the HLM27 league.", BODY, data, SCRIPT, CSS), \
        f"{len(played)} games played, {len(todo)} to play, {sims:,} simulated seasons"


CSS = """
  td.bar { width: 16%; min-width: 5.5rem; }
  .blocks { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 26rem), 1fr)); gap: 0 32px; }
  .blocks h3 { margin-top: 14px; }
  table.tight th, table.tight td { padding: 6px 6px; font-size: 14px; }
  .pick-team { font-size: 14px; }
"""

BODY = """
  <header>
    <h1>Standings</h1>
    <p class="lede"><span id="season"></span>: the table, what sits under it, and how the playoff race is likely to end.</p>
    <p class="meta">Through the league save of <span id="as-of"></span>: <span id="n-played"></span> games played, <span id="n-left"></span> to go. Updated <span id="built"></span>.</p>
    <p class="meta pick-team"><label for="t-pick">Highlight</label> <select id="t-pick"></select></p>
  </header>

  <section id="table">
    <div class="head"><h2>The table</h2>
      <span class="seg" id="view"><button type="button" data-v="wild" aria-pressed="true">Wild card</button><button type="button" data-v="div" aria-pressed="false">Division</button><button type="button" data-v="league" aria-pressed="false">League</button></span></div>
    <div id="tables"></div>
    <p class="note" style="margin-top:10px">The line is the playoff cut: the top three in each division, then two wild cards per conference.</p>
  </section>

  <section id="race">
    <div class="head"><h2>The race</h2><span class="note">The rest of the season played out <span id="n-sims"></span> times. Click a header to sort.</span></div>
    <div class="scroll tall">
      <table id="race-table">
        <thead><tr>
          <th data-k="code" data-d="asc">Team</th>
          <th class="num" data-k="pts">PTS</th>
          <th class="num" data-k="proj" title="Average final points, with the range 8 seasons in 10 land in">Projected</th>
          <th class="num" data-k="po">Playoffs</th>
          <th class="sec" aria-label="Playoff chance"></th>
          <th class="num sec" data-k="dv" title="Chance of finishing first in the division">Division</th>
          <th class="num" data-k="first" title="Chance of the first overall pick, after the lottery">1st pick</th>
          <th class="num sec" data-k="str" title="Goals per game better or worse than an average team">Strength</th>
          <th class="num sec" data-k="sosLeft" title="Average strength of the opponents left; above zero is a harder road">Schedule left</th>
          <th class="num sec" data-k="homeLeft">Home left</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <section id="hood">
    <div class="head"><h2>Under the hood</h2><span class="note">Who is driving play, who is running hot. Click a header to sort.</span></div>
    <div class="scroll tall">
      <table id="hood-table">
        <thead><tr>
          <th data-k="code" data-d="asc">Team</th>
          <th class="num" data-k="cfp" title="Share of all shot attempts in the team's games">Shot share</th>
          <th class="num sec" data-k="sfg">Shots for</th>
          <th class="num sec" data-k="sag">Shots against</th>
          <th class="num" data-k="shp" title="Goals per shot on goal">Sh%</th>
          <th class="num" data-k="svp" title="Saves per shot against">Sv%</th>
          <th class="num" data-k="pdo" title="Sh% plus Sv%. Far from 100 tends not to last">PDO</th>
          <th class="num" data-k="pp">PP%</th>
          <th class="num" data-k="pk">PK%</th>
          <th class="num sec" data-k="fo">Faceoffs</th>
          <th class="sec" data-k="onep" title="Games decided by one goal: wins, losses, overtime losses">One-goal games</th>
          <th class="sec" data-k="otp" title="Overtime wins and losses">Overtime</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <section id="method" class="method">
    <div class="head"><h2>How it works</h2></div>
    <p><b>The table.</b> Built from every regular-season game in the save: two points for a win, one for an overtime loss. Teams level on points are split by fewer games played, then regulation wins, wins and goal difference, the NHL's order; the game's own order isn't confirmed.</p>
    <p><b>Under the hood.</b> Shot share is a team's part of all shot attempts in its games, the best quick read of who controls play. Sh% and Sv% are goals per shot, for and against; PDO adds them up, and a team far above or below 100 is usually riding luck that fades. Faceoffs is the share won.</p>
    <p><b>The race.</b> Each team gets a strength, in goals per game against an average team. It starts from the lineup: the average overall of the 12 forwards, the six defencemen and the starting goalie, weighted by how much each has mattered to goal difference in this league. Results then pull it toward the team's actual goal difference, slowly: a full season of games moves it about halfway. Every game left is played out <span id="m-sims"></span> times, with a small edge for the home team and <span id="m-ot"></span>% of games going to overtime for the loser's point.</p>
    <p><b>Playoffs and the pick.</b> Playoffs is how often a team finishes in the top three of its division or takes one of its conference's two wild cards. 1st pick is its chance at first overall once the lottery is run among the 16 teams that miss: the league's odds, with a winner able to move up at most ten spots.</p>
    <p><b>How good is it?</b> Checked against every game of 2026-27 and the start of this season, the lineup number called winners better than the standings did. It doesn't know about trades, injuries or call-ups that haven't happened, so read it as where things point today.</p>
  </section>
"""

SCRIPT = r"""
  const pct = (a, b) => b ? 100 * a / b : 0;
  const rec = (r) => r.join('–');
  const T = D.teams.map((t) => Object.assign(t, { name: D.names[t.code] || t.code, diff: t.gf - t.ga, pp100: t.gp ? t.pts / (2 * t.gp) : 0, rw: t.w - t.otw,
    cfp: pct(t.cf, t.cf + t.ca), sfg: t.gp ? t.sf / t.gp : 0, sag: t.gp ? t.sa / t.gp : 0, shp: pct(t.gf, t.sf), svp: 100 - pct(t.ga, t.sa),
    pp: pct(t.ppg, t.ppo), pk: 100 - pct(t.pkga, t.pko), fo: pct(t.fw, t.fw + t.fl), onep: pct(2 * t.one[0] + t.one[2], 2 * (t.one[0] + t.one[1] + t.one[2])), otp: t.otw - t.otl }));
  T.forEach((t) => { t.pdo = t.shp + t.svp; });
  $('season').textContent = D.season; $('n-played').textContent = D.played; $('n-left').textContent = D.left.toLocaleString('en-CA');
  $('n-sims').textContent = $('m-sims').textContent = D.sims.toLocaleString('en-CA'); $('m-ot').textContent = D.ot;
  let picked = hashTeam() || 'CGY';
  const rank = (a, b) => b.pts - a.pts || a.gp - b.gp || b.rw - a.rw || b.w - a.w || b.diff - a.diff || a.code.localeCompare(b.code);

  // The table
  let view = 'wild';
  // The league view has room for every column; the two-conference views keep to the essentials.
  const head = (full) => '<thead><tr><th class="num"></th><th>Team</th><th class="num">GP</th><th class="num">W</th><th class="num">L</th><th class="num">OTL</th><th class="num">PTS</th>' +
    (full ? '<th class="num sec">P%</th><th class="num sec">RW</th><th class="num sec">GF</th><th class="num sec">GA</th>' : '') + '<th class="num sec">Diff</th>' +
    (full ? '<th class="sec">Home</th><th class="sec">Away</th>' : '') + '<th class="sec">L10</th>' + (full ? '<th class="sec">Strk</th>' : '') + '</tr></thead>';
  const row = (t, i, cut, full) => `<tr class="${t.code === picked ? 'me' : ''}${cut ? ' cut' : ''}"><td class="num soft">${i}</td><td><b>${t.code}</b> <span class="soft wide">${esc(t.name)}</span></td>
    <td class="num">${t.gp}</td><td class="num">${t.w}</td><td class="num">${t.l}</td><td class="num">${t.otl}</td><td class="num"><b>${t.pts}</b></td>` +
    (full ? `<td class="num sec">${t.pp100.toFixed(3).replace(/^0/, '')}</td><td class="num sec">${t.rw}</td><td class="num sec">${t.gf}</td><td class="num sec">${t.ga}</td>` : '') +
    `<td class="num sec ${cls(t.diff)}">${signed(t.diff)}</td>` + (full ? `<td class="sec">${rec(t.home)}</td><td class="sec">${rec(t.away)}</td>` : '') +
    `<td class="sec">${rec(t.l10)}</td>` + (full ? `<td class="sec">${t.strk}</td>` : '') + '</tr>';
  const block = (title, list, cutAt, full) => `<h3>${esc(title)}</h3><div class="scroll tall"><table${full ? '' : ' class="tight"'}>${head(full)}<tbody>${list.map((t, i) => row(t, i + 1, i + 1 === cutAt, full)).join('')}</tbody></table></div>`;
  function drawTable() {
    if (view === 'league') { $('tables').innerHTML = block('League', T.slice().sort(rank), 0, true); return; }
    $('tables').innerHTML = '<div class="blocks">' + D.confs.map((cn, c) => {
      const inConf = T.filter((t) => t.conf === c), divs = [...new Set(inConf.map((t) => t.div))].sort(), out = [], rest = [];
      divs.forEach((d) => { const s = inConf.filter((t) => t.div === d).sort(rank);
        if (view === 'div') out.push(block(D.divs[d], s, 3)); else { out.push(block(D.divs[d], s.slice(0, 3))); rest.push(...s.slice(3)); } });
      if (view !== 'div') out.push(block(cn + ' wild card', rest.sort(rank), 2));
      return '<div>' + out.join('') + '</div>';
    }).join('') + '</div>';
  }
  $('view').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; view = b.dataset.v;
    [...$('view').children].forEach((x) => x.setAttribute('aria-pressed', x === b)); drawTable(); });

  // The race
  const rs = {k: 'po', d: -1};
  const p1 = (x) => x >= 99.95 ? '>99.9%' : x > 0 && x < 0.05 ? '<0.1%' : x.toFixed(1) + '%';
  function drawRace() {
    $('race-table').tBodies[0].innerHTML = T.slice().sort((a, b) => by(rs)(a, b) || b.proj - a.proj).map((t) => `<tr class="${t.code === picked ? 'me' : ''}">
      <td><b>${t.code}</b> <span class="soft wide">${esc(t.name)}</span></td><td class="num">${t.pts}</td>
      <td class="num"><b>${Math.round(t.proj)}</b> <span class="soft wide">${t.lo}–${t.hi}</span></td>
      <td class="num"><b>${p1(t.po)}</b></td><td class="bar sec"><span class="meter"><i class="blue" style="width:${t.po}%"></i></span></td>
      <td class="num sec">${p1(t.dv)}</td><td class="num">${t.first ? p1(t.first) : '<span class="soft">–</span>'}</td>
      <td class="num sec ${cls(t.str)}">${signed(t.str, 2)}</td><td class="num sec">${signed(t.sosLeft, 2)}</td><td class="num sec">${t.homeLeft}<span class="soft">/${t.left}</span></td></tr>`).join('');
  }
  sortable($('race-table'), rs, drawRace);

  // Under the hood
  const hs = {k: 'cfp', d: -1};
  const f1 = (x) => x.toFixed(1);
  function drawHood() {
    $('hood-table').tBodies[0].innerHTML = T.slice().sort(by(hs)).map((t) => `<tr class="${t.code === picked ? 'me' : ''}">
      <td><b>${t.code}</b> <span class="soft wide">${esc(t.name)}</span></td><td class="num"><b>${f1(t.cfp)}%</b></td><td class="num sec">${f1(t.sfg)}</td><td class="num sec">${f1(t.sag)}</td>
      <td class="num">${f1(t.shp)}</td><td class="num">${f1(t.svp)}</td><td class="num ${t.pdo >= 102 ? 'up' : t.pdo <= 98 ? 'down' : ''}">${f1(t.pdo)}</td>
      <td class="num">${f1(t.pp)}</td><td class="num">${f1(t.pk)}</td><td class="num sec">${f1(t.fo)}%</td><td class="sec">${rec(t.one)}</td><td class="sec">${t.otw}–${t.otl}</td></tr>`).join('');
  }
  sortable($('hood-table'), hs, drawHood);

  function drawAll() { drawTable(); drawRace(); drawHood(); }
  fillTeams($('t-pick'), picked, D.names);
  $('t-pick').addEventListener('change', (e) => { picked = e.target.value; setHashTeam(picked); drawAll(); });
  addEventListener('hashchange', () => { const c = hashTeam(); if (c && c !== picked) { picked = c; $('t-pick').value = c; drawAll(); } });
  drawAll();
"""
