"""Player stats: every skater's and goalie's season line, with the rates and on-ice numbers beside it.

Each player carries one _CareerStats line per season type, league and club: comma-separated numbers with no
names. The columns were named by matching the 2026-27 lines against their named copies in pastathlete.hlm, and
the NHL lines add up to every team's own totals. An earlier season is read from the last save of that season,
which still has the players who retired after it.
"""
import collections
import datetime

import site_cap
import site_pages as sp
import site_shell

FIRST_SEASON = 2026  # the league's first season; lines from before it are real-life history

# (page key, column in a _CareerStats line, name in pastathlete.hlm), in the order the page's rows carry them.
# A line starts: goalie flag, player id, type (0 regular season, 1 playoffs, 3 preseason), league, club, season.
SKATER = (("gp", 6, "GamePlayed"), ("g", 7, "Goals"), ("a1", 8, "PrimaryAssists"), ("a2", 20, "SecondaryAssists"), ("s", 9, "Shot"),
          ("blk", 10, "ShotBlock"), ("ogf", 11, "EvenStrengthGoalsFor"), ("oga", 22, "EvenStrengthGoalsAgainst"), ("toi", 12, "TimeOnIce"),
          ("fow", 13, "FaceoffWins"), ("fol", 14, "FaceoffLosses"), ("cf", 15, "CorsiFor"), ("ca", 16, "CorsiAgainst"),
          ("pim", 17, "PenaltyTaken"), ("ppg", 18, "PowerPlayGoals"), ("ppa", 19, "PowerPlayAssists"), ("pd", 21, "PenaltyDraw"),
          ("hit", 23, "Hit"), ("gwg", 24, "GameWinningGoals"), ("ht", 25, "HatTricks"))
# Wins include overtime wins; losses are regulation losses, with overtime losses counted apart.
GOALIE =(("gp", 6, "GamePlayed"), ("w", 7, "Wins"), ("l", 15, "Losses"), ("otl", 14, "OvertimeLosses"), ("sv", 9, "Save"),
          ("ga", 8, "GoalAgainst"), ("so", 10, "Shutout"), ("toi", 11, "TimeOnIce"))
PIM = [k for k, _, _ in SKATER].index("pim")
GOALS = [k for k, _, _ in SKATER].index("g")
SV, GA = [k for k, _, _ in GOALIE].index("sv"), [k for k, _, _ in GOALIE].index("ga")


def csv_lines(p):
    """A player's lines in the live save: (goalie?, type, league, club, season, numbers)."""
    for line in p.get("_CareerStats") or []:
        c = line.split(",")
        if len(c) < 7 or c[6] in ("", "0"):
            continue  # no games

        def n(i):
            return int(float(c[i])) if i < len(c) and c[i] else 0
        goalie = c[0] == "1"
        yield goalie, n(2), n(3), n(4), n(5), [n(i) for _, i, _ in (GOALIE if goalie else SKATER)]


def named_lines(rows):
    """The same shape from pastathlete.hlm, where the numbers have names. Its penalties are a count; the live lines hold minutes."""
    for r in rows or []:
        goalie = r.get("$type") == "GoalieStats"
        nums = [int(r.get(name) or 0) for _, _, name in (GOALIE if goalie else SKATER)]
        if not nums[0]:
            continue
        if not goalie:
            nums[PIM] *= 2
        yield goalie, r.get("Type") or 0, r.get("League") or 0, r.get("Team") or 0, r.get("Season") or 0, nums


def gather(players, lines_of, year):
    """{(type, league): {player id: {"g": goalie?, "clubs": [club ids], "n": numbers}}} for one season, a player's clubs added up."""
    out = collections.defaultdict(dict)
    for pid, p in players.items():
        for goalie, typ, league, club, season, nums in lines_of(pid, p):
            if season != year or typ not in (0, 1):
                continue
            e = out[(typ, league)].setdefault(pid, {"g": goalie, "clubs": [], "n": [0] * len(nums)})
            if e["g"] != goalie:
                continue
            e["clubs"].append(club)
            e["n"] = [a + b for a, b in zip(e["n"], nums)]
    return out


def save_rate(entries):
    """A league's save rate over every goalie in it, for goals saved above average."""
    sv = sum(e["n"][SV] for e in entries.values() if e["g"])
    ga = sum(e["n"][GA] for e in entries.values() if e["g"])
    return round(sv / (sv + ga), 5) if sv + ga else None


def build(ctx):
    sl, code, year = ctx.sl, ctx.code, ctx.sl["Year"]

    def label(y):
        return f"{y}-{(y + 1) % 100:02d}"

    def club_name(league, tid):
        t = (league.get("TeamList") or {}).get(str(tid)) or {}
        return " ".join(x for x in (t.get("City"), t.get("Name")) if x) or "?"

    def rows(players, entries, y, on, current, league_id=0):
        """Page rows for one table. NHL: the team is where he played. Elsewhere: the NHL club that holds his rights."""
        league = sl["Leagues"].get(str(league_id)) or {}
        sk, go = [], []
        for pid, e in entries.items():
            p = players[pid]
            if league_id == 0:
                team, lg, club = "/".join(code.get(c, "?") for c in e["clubs"]), "", ""
                rookie = int((p.get("RookieSeason") or {}).get("0") == y)
            else:
                team = code.get((p.get("TeamIds") or {}).get("0"))
                if not team:
                    continue
                lg, club, rookie = league.get("Abbreviation") or "?", " / ".join(club_name(league, c) for c in e["clubs"]), 0
            c = site_cap.nhl_contract(p) if current and league_id == 0 else None
            h = site_cap.hits(c) if c else []
            tail = [sp.age_on(p, on), rookie, lg, club, sp.overall(p) if current else None, h[0] if h else None] + e["n"]
            if e["g"]:
                go.append([sp.full_name(p), team] + tail)
            else:
                sk.append([sp.full_name(p), team, sp.positions(p), sp.group(p)] + tail)
        return sk, go

    sets = []

    def add(sid, text, sk, go, sv, **flags):
        if sk or go:
            sets.append(dict({"id": sid, "label": text, "nhl": True, "po": False, "cur": False, "sv": sv, "sk": sk, "go": go}, **flags))

    # This season: the NHL, its playoffs once they start, and NHL clubs' players in every other league.
    now = gather(ctx.PL, lambda pid, p: csv_lines(p), year)
    add(str(year), f"{label(year)} · NHL", *rows(ctx.PL, now.get((0, 0), {}), year, ctx.date, True), {"": save_rate(now.get((0, 0), {}))}, cur=True)
    add(f"{year}p", f"{label(year)} · NHL playoffs", *rows(ctx.PL, now.get((1, 0), {}), year, ctx.date, True), {"": save_rate(now.get((1, 0), {}))}, cur=True, po=True)
    sk, go, rates = [], [], {}
    for (typ, lid), entries in now.items():
        if typ == 0 and lid != 0:
            a, b = rows(ctx.PL, entries, year, ctx.date, True, lid)
            sk += a
            go += b
            rates[(sl["Leagues"].get(str(lid)) or {}).get("Abbreviation") or "?"] = save_rate(entries)
    add(f"{year}o", f"{label(year)} · Other leagues", sk, go, rates, cur=True, nhl=False)
    others = len(sk) + len(go)

    # Earlier seasons: the last save of each one when the build has the older saves, else the newest save's history file.
    finals = {s["year"]: s["path"] for s in ctx.states or [] if s.get("year") and s["year"] < year}  # date order: the last one wins
    past, thin = None, []
    for y in range(year - 1, FIRST_SEASON - 1, -1):
        if y in finals:
            players = sp.read_full(finals[y])["PlayerList"]
            table = gather(players, lambda pid, p: csv_lines(p), y)
        else:
            if past is None:
                past = sp.read_member(ctx.path, "pastathlete.hlm")["Stats"]
            players = ctx.PL
            table = gather(players, lambda pid, p: named_lines(past.get(pid)), y)
            thin.append(label(y))
        on = datetime.date(y + 1, 2, 1)
        add(str(y), f"{label(y)} · NHL", *rows(players, table.get((0, 0), {}), y, on, False), {"": save_rate(table.get((0, 0), {}))})
        add(f"{y}p", f"{label(y)} · NHL playoffs", *rows(players, table.get((1, 0), {}), y, on, False), {"": save_rate(table.get((1, 0), {}))}, po=True)

    # Check: this season's NHL goals, club by club, against each team's own line.
    goals = collections.Counter()
    for p in ctx.PL.values():
        for goalie, typ, league, club, season, nums in csv_lines(p):
            if not goalie and typ == 0 and league == 0 and season == year:
                goals[club] += nums[GOALS]
    off = [c for t, c in code.items() if goals[t] != ((ctx.lg["TeamList"][str(t)].get("Stats") or {}).get("GoalsFor") or 0)]
    if off:
        print(f"CHECK: players' goals don't add up to the team's for {', '.join(sorted(off))}", flush=True)

    cfg = ctx.lg.get("ConfigOrDefault") or {}
    data = dict(ctx.base(), sets=sets, games=cfg.get("GamesPerSeason") or 82, teams=[{"code": c} for c in sorted(code.values())])
    first = sets[0] if sets else {"sk": [], "go": []}
    note = f" ({', '.join(thin)} from the history file: run from build_report_cards.py to add players since retired)" if thin else ""
    return site_shell.page("stats", "PHL player stats", "Every skater's and goalie's numbers in the HLM27 league: scoring, rates, on-ice results and cost per point.",
                           BODY, data, SCRIPT, CSS), \
        (f"{len(first['sk'])} skaters and {len(first['go'])} goalies in {first.get('label', 'no season')}, {others} players in other leagues, "
         f"{len(sets)} tables; goals match the standings for {len(code) - len(off)} of {len(code)} teams{note}")


CSS = """
  [hidden] { display: none !important; }
  td.who { font-weight: 600; }
  td.on { font-weight: 700; }
  th.rk, td.rk { color: var(--ink-soft); font-weight: 400; width: 1%; }
  a.tl { color: inherit; text-decoration: none; }
  a.tl:hover { text-decoration: underline; }
  .figures { grid-template-columns: repeat(6, minmax(0, 1fr)); margin-top: 14px; }
  @media (max-width: 900px) { .figures { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
  @media (max-width: 520px) { .figures { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  .figures .l, .figures .s { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .more { margin-top: 10px; }
  button.link { font: inherit; color: var(--blue); background: none; border: 0; padding: 0; cursor: pointer; text-decoration: underline; }
  .ctl { display: inline-flex; align-items: center; gap: 6px; max-width: 100%; }
  .ctl label { color: var(--ink-soft); font-size: 13px; }
  @media (max-width: 760px) { td.who { white-space: normal; min-width: 7.5rem; max-width: 11rem; } td.tm { white-space: normal; } }
"""

BODY = """
  <header>
    <h1>Player stats</h1>
    <p class="lede">Every skater and goalie, sortable by anything: scoring, rates per 60 minutes, on-ice results and cost per point. Pick Other leagues to see each club's prospects in the minors, junior, college and Europe.</p>
    <p class="meta">Through the league save of <span id="as-of"></span>. Updated <span id="built"></span>.</p>
    <div class="tools" style="margin-top:14px">
      <span class="ctl"><label for="set">Season</label><select id="set"></select></span>
      <span class="ctl" id="lg-wrap" hidden><label for="lg">League</label><select id="lg"></select></span>
      <span class="ctl"><label for="t-pick">Team</label><select id="t-pick"></select></span>
      <span class="ctl"><label for="min">Minimum</label><select id="min"></select></span>
      <span class="seg" id="rk-wrap"><button type="button" id="rk" aria-pressed="false">Rookies</button></span>
      <input type="search" id="q" placeholder="Search a player" aria-label="Search players" autocomplete="off">
    </div>
    <div class="figures" id="leaders" aria-label="Leaders"></div>
  </header>

  <section id="skaters">
    <div class="head"><h2>Skaters</h2><span class="note" id="sk-note" aria-live="polite"></span></div>
    <div class="tools">
      <span class="seg" id="view" role="group" aria-label="Columns"></span>
      <span class="seg" id="pos" role="group" aria-label="Position"><button type="button" data-v="" aria-pressed="true">All</button><button type="button" data-v="F" aria-pressed="false">Forwards</button><button type="button" data-v="D" aria-pressed="false">Defence</button></span>
      <span class="note" id="view-note"></span>
    </div>
    <div class="scroll"><table id="sk"><thead></thead><tbody></tbody></table></div>
    <p class="note more" id="sk-more" hidden><button type="button" class="link" id="sk-all"></button></p>
  </section>

  <section id="goalies">
    <div class="head"><h2>Goalies</h2><span class="note" id="go-note" aria-live="polite"></span></div>
    <div class="scroll tall"><table id="go"><thead></thead><tbody></tbody></table></div>
  </section>

  <section id="method" class="method">
    <div class="head"><h2>How it works</h2></div>
    <p><b>The numbers.</b> Each player's season line as the league save holds it: the same totals the game's own stats screens show, and the NHL lines add up to every team's goals, shots and record. A traded player gets one line for the season, with every team he played for. Age is today's for this season, and on February 1 for an earlier one.</p>
    <p><b>Rates.</b> Per 60 uses all of his ice time, at any strength. P/<span class="m-games"></span> is his points per game over <span class="m-games"></span> games. A1 is primary assists, and P1 is goals plus primary assists. Rates and Value open at a minimum number of games so that one good night doesn't top the list; change it with Minimum.</p>
    <p><b>On ice.</b> GF and GA are the goals scored while he was on the ice, power-play goals left out; +/− is the difference and GF% his team's share. CF and CA are shot attempts at even strength while he was on the ice, CF% his team's share.</p>
    <p><b>Physical.</b> The game gives every penalty two minutes, so PIM is twice his penalties. Pen ± is penalties drawn less penalties taken. FO% shows for players who take at least four faceoffs a game.</p>
    <p><b>Value.</b> Cap hit is this season's, and OVR is today's rating. $/point is the cap hit divided by his points over <span class="m-games"></span> games: what a point costs at his scoring pace. It says nothing about his defence.</p>
    <p><b>Goalies.</b> L is losses in regulation. GSAA is goals saved above average: the goals the league's average goalie would have allowed on the same shots, less the goals he allowed. The save percentage leader needs a third of the busiest goalie's games.</p>
    <p><b>Rookies.</b> R marks a player in his first NHL season, as the game counts it.</p>
    <p><b>Other leagues.</b> Players whose NHL rights a club holds today, in the league they are playing in. Team is that NHL club. GSAA there is against every goalie in that league.</p>
  </section>
"""

SCRIPT = r"""
  const G82 = D.games;
  document.querySelectorAll('.m-games').forEach((e) => { e.textContent = G82; });
  if (!D.sets.length) { $('skaters').innerHTML = '<p class="empty">No games played yet.</p>'; $('goalies').hidden = true; return; }
  const SF = ['n', 't', 'pos', 'grp', 'age', 'r', 'lg', 'club', 'o', 'cap', 'gp', 'g', 'a1', 'a2', 's', 'blk', 'ogf', 'oga', 'toi', 'fow', 'fol', 'cf', 'ca', 'pim', 'ppg', 'ppa', 'pd', 'hit', 'gwg', 'ht'];
  const GF = ['n', 't', 'age', 'r', 'lg', 'club', 'o', 'cap', 'gp', 'w', 'l', 'otl', 'sv', 'ga', 'so', 'toi'];
  const fold = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const per = (x, toi) => toi ? x * 3600 / toi : null;
  const share = (a, b) => a + b ? 100 * a / (a + b) : null;
  const cache = {};
  // A set's rows as objects, with everything worked out from the totals.
  function load(set) {
    if (cache[set.id]) return cache[set.id];
    const sk = set.sk.map((r) => { const o = {}; SF.forEach((k, i) => { o[k] = r[i]; });
      o.a = o.a1 + o.a2; o.p = o.g + o.a; o.p1 = o.g + o.a1; o.pm = o.ogf - o.oga; o.ppp = o.ppg + o.ppa;
      o.shp = o.s ? 100 * o.g / o.s : null; o.toig = o.toi / o.gp; o.pgp = o.p / o.gp; o.p82 = o.pgp * G82;
      o.g60 = per(o.g, o.toi); o.a160 = per(o.a1, o.toi); o.p60 = per(o.p, o.toi); o.p160 = per(o.p1, o.toi); o.s60 = per(o.s, o.toi);
      o.hit60 = per(o.hit, o.toi); o.blk60 = per(o.blk, o.toi);
      o.gfp = share(o.ogf, o.oga); o.cfp = share(o.cf, o.ca); o.fop = o.fow + o.fol >= 4 * o.gp ? share(o.fow, o.fol) : null;
      o.pend = o.pd - o.pim / 2; o.cost = o.cap && o.p ? o.cap / o.p82 : null;
      o.q = fold(o.n); o.teams = o.t.split('/'); return o; });
    const go = set.go.map((r) => { const o = {}; GF.forEach((k, i) => { o[k] = r[i]; });
      const avg = set.sv[o.lg];
      o.sa = o.sv + o.ga; o.svp = o.sa ? o.sv / o.sa : null; o.gaa = per(o.ga, o.toi);
      o.gsaa = o.sa && avg != null ? (1 - avg) * o.sa - o.ga : null;
      o.q = fold(o.n); o.teams = o.t.split('/'); return o; });
    return (cache[set.id] = {sk, go});
  }

  const dash = '<span class="soft">–</span>';
  const F = {
    int: (x) => String(x),
    sign: (x) => `<span class="${cls(x)}">${signed(x)}</span>`,
    sign1: (x) => `<span class="${cls(Math.round(x * 10))}">${signed(x, 1)}</span>`,
    d1: (x) => x.toFixed(1), d2: (x) => x.toFixed(2), r0: (x) => String(Math.round(x)),
    clock: (x) => { const s = Math.round(x); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); },
    sv: (x) => x.toFixed(3).replace(/^0/, ''),
    money: (x) => money(x),
    cost: (x) => '$' + Math.round(x / 1000).toLocaleString('en-CA') + 'K',
  };
  // A column: row field, header, hover text, format; sec hides it on a phone, asc sorts low to high first, reg is NHL regular season only.
  const C = (k, h, t, f, x) => Object.assign({k, h, t, f: f || 'int'}, x);
  const toi = (x) => C('toig', 'TOI/GP', 'Ice time per game', 'clock', x);
  const pm = C('pm', '+/−', 'Goals for less goals against while he was on the ice, power-play goals left out', 'sign');
  const VIEWS = {
    scoring: {label: 'Scoring', sort: 'p', cols: [C('g', 'G', 'Goals'), C('a', 'A', 'Assists'), C('p', 'P', 'Points'), pm,
      C('pim', 'PIM', 'Penalty minutes', 0, {sec: 1}), C('ppg', 'PPG', 'Power-play goals', 0, {sec: 1}), C('ppp', 'PPP', 'Power-play points', 0, {sec: 1}),
      C('gwg', 'GWG', 'Game-winning goals', 0, {sec: 1}), C('s', 'S', 'Shots on goal', 0, {sec: 1}), C('shp', 'S%', 'Goals per 100 shots', 'd1', {sec: 1}), toi({sec: 1})]},
    rates: {label: 'Rates', sort: 'p60', rate: 1, cols: [toi({sec: 1}), C('pgp', 'P/GP', 'Points per game', 'd2'), C('p82', 'P/' + G82, 'Points per game over ' + G82 + ' games', 'r0', {reg: 1}),
      C('g60', 'G/60', 'Goals per 60 minutes of ice time', 'd2', {sec: 1}), C('a160', 'A1/60', 'Primary assists per 60 minutes', 'd2', {sec: 1}), C('p60', 'P/60', 'Points per 60 minutes', 'd2'),
      C('p160', 'P1/60', 'Goals and primary assists per 60 minutes', 'd2', {sec: 1}), C('s60', 'S/60', 'Shots per 60 minutes', 'd1', {sec: 1})]},
    onice: {label: 'On ice', sort: 'pm', cols: [toi({sec: 1}), C('ogf', 'GF', 'Goals for while he was on the ice, power-play goals left out', 0, {sec: 1}),
      C('oga', 'GA', 'Goals against while he was on the ice, power-play goals left out', 0, {sec: 1, asc: 1}), pm, C('gfp', 'GF%', 'His team’s share of those goals', 'd1'),
      C('cf', 'CF', 'Shot attempts for at even strength while he was on the ice', 0, {sec: 1}), C('ca', 'CA', 'Shot attempts against at even strength while he was on the ice', 0, {sec: 1, asc: 1}),
      C('cfp', 'CF%', 'His team’s share of those shot attempts', 'd1')]},
    physical: {label: 'Physical', sort: 'hit', cols: [C('hit', 'Hits', 'Hits'), C('hit60', 'Hits/60', 'Hits per 60 minutes', 'd1', {sec: 1}), C('blk', 'Blocks', 'Blocked shots'),
      C('blk60', 'Blk/60', 'Blocked shots per 60 minutes', 'd1', {sec: 1}), C('pim', 'PIM', 'Penalty minutes', 0, {sec: 1}), C('pd', 'Drawn', 'Penalties drawn', 0, {sec: 1}),
      C('pend', 'Pen ±', 'Penalties drawn less penalties taken', 'sign', {sec: 1}), C('fow', 'FOW', 'Faceoffs won', 0, {sec: 1}), C('fol', 'FOL', 'Faceoffs lost', 0, {sec: 1, asc: 1}),
      C('fop', 'FO%', 'Faceoffs won, for players who take four or more a game', 'd1')]},
    value: {label: 'Value', sort: 'cost', dir: 1, rate: 1, cur: 1, cols: [C('o', 'OVR', 'Overall rating today', 0, {sec: 1}), C('cap', 'Cap hit', 'This season’s cap hit', 'money'), C('p', 'P', 'Points', 0, {sec: 1}),
      C('pgp', 'P/GP', 'Points per game', 'd2', {sec: 1}), C('p82', 'P/' + G82, 'Points per game over ' + G82 + ' games', 'r0', {sec: 1}),
      C('cost', '$/point', 'Cap hit divided by his points over ' + G82 + ' games', 'cost', {asc: 1})]},
  };
  const GCOLS = [C('w', 'W', 'Wins'), C('l', 'L', 'Losses in regulation', 0, {asc: 1}), C('otl', 'OTL', 'Losses in overtime', 0, {asc: 1}), C('sa', 'SA', 'Shots against', 0, {sec: 1}),
    C('ga', 'GA', 'Goals against', 0, {sec: 1, asc: 1}), C('svp', 'Sv%', 'Saves per shot', 'sv'), C('gaa', 'GAA', 'Goals against per 60 minutes', 'd2', {sec: 1, asc: 1}), C('so', 'SO', 'Shutouts', 0, {sec: 1}),
    C('gsaa', 'GSAA', 'Goals saved above the league’s average goalie on the same shots', 'sign1', {sec: 1})];

  const byId = Object.fromEntries(D.sets.map((s) => [s.id, s]));
  let set = D.sets[0], team = hashTeam() || '', league = '', view = 'scoring', pos = '', rookies = false, minGp = 0, userMin = false, qual = 1, all = false;
  const ss = {k: 'p', d: -1}, gs = {k: 'w', d: -1}, LIMIT = 250;
  const regular = () => set.nhl && !set.po;
  const viewOk = (v) => !VIEWS[v].cur || (set.cur && regular());
  const colOk = (c) => !c.reg || regular();
  const cols = () => VIEWS[view].cols.filter(colOk);

  $('set').innerHTML = D.sets.map((s) => `<option value="${s.id}">${esc(s.label)}</option>`).join('');
  $('t-pick').innerHTML = '<option value="">All teams</option>' + D.teams.map((t) => `<option value="${t.code}"${t.code === team ? ' selected' : ''}>${t.code} · ${esc(D.names[t.code] || t.code)}</option>`).join('');
  $('view').innerHTML = Object.keys(VIEWS).map((v) => `<button type="button" data-v="${v}" aria-pressed="${v === view}">${VIEWS[v].label}</button>`).join('');

  function head(table, list, state, draw, skaters) {
    const th = (c) => `<th class="num${c.sec ? ' sec' : ''}" data-k="${c.k}"${c.asc ? ' data-d="asc"' : ''} title="${esc(c.t)}">${c.h}</th>`;
    table.tHead.innerHTML = `<tr><th class="num rk sec">#</th><th data-k="n" data-d="asc">Player</th><th${team ? ' class="sec"' : ''} data-k="t" data-d="asc">Team</th>` +
      (set.nhl ? '' : '<th data-k="lg" data-d="asc">League</th><th class="sec" data-k="club" data-d="asc">Club</th>') +
      (skaters ? '<th class="sec" data-k="pos" data-d="asc">Pos</th>' : '') +
      '<th class="num sec" data-k="age">Age</th><th class="num" data-k="gp" title="Games played">GP</th>' + list.map(th).join('') + '</tr>';
    sortable(table, state, draw);
  }
  const link = (c) => teamCodes.has(c) ? `<a class="tl" href="#${c}" title="${esc(D.names[c] || c)}">${c}</a>` : esc(c);
  function body(rows, list, state, skaters) {
    return rows.map((r, i) => `<tr><td class="num rk sec">${i + 1}</td><td class="who">${esc(r.n)}${r.r ? ' <span class="tag" title="Rookie">R</span>' : ''}</td><td class="tm${team ? ' sec' : ''}">${r.teams.map(link).join('/<wbr>')}</td>` +
      (set.nhl ? '' : `<td>${esc(r.lg)}</td><td class="sec">${esc(r.club)}</td>`) + (skaters ? `<td class="sec">${r.pos}</td>` : '') +
      `<td class="num sec${state.k === 'age' ? ' on' : ''}">${r.age}</td><td class="num${state.k === 'gp' ? ' on' : ''}">${r.gp}</td>` +
      list.map((c) => { const v = r[c.k]; return `<td class="num${c.sec ? ' sec' : ''}${c.k === state.k ? ' on' : ''}">${v == null ? dash : F[c.f](v)}</td>`; }).join('') + '</tr>').join('');
  }
  // Sort by the picked column; a blank always sinks, and ties fall back to the usual order.
  const order = (state, ties) => (a, b) => { const x = a[state.k], y = b[state.k];
    if (x == null || y == null) { if ((x == null) !== (y == null)) return x == null ? 1 : -1; }
    else { const c = (typeof x === 'string' ? x.localeCompare(y) : x - y) * state.d; if (c) return c; }
    return ties(a, b); };
  const skTies = (a, b) => b.p - a.p || b.g - a.g || a.gp - b.gp || a.n.localeCompare(b.n);
  const goTies = (a, b) => b.w - a.w || (b.svp || 0) - (a.svp || 0) || a.n.localeCompare(b.n);
  const scope = (r) => (!team || r.teams.includes(team)) && (!league || r.lg === league);
  function keep(skaters) {
    const q = fold($('q').value.trim());
    return (r) => scope(r) && r.gp >= minGp && (!rookies || r.r) && (!q || r.q.includes(q)) && (!skaters || !pos || r.grp === pos);
  }
  const count = (n, one, many) => n.toLocaleString('en-CA') + ' ' + (n === 1 ? one : many);

  function drawSkaters() {
    const rows = load(set).sk.filter(keep(true)).sort(order(ss, skTies)), cut = !all && rows.length > LIMIT;
    $('sk').tBodies[0].innerHTML = body(cut ? rows.slice(0, LIMIT) : rows, cols(), ss, true) || `<tr><td colspan="30" class="empty">No skaters match.</td></tr>`;
    $('sk-note').textContent = cut ? `Top ${LIMIT} of ${count(rows.length, 'skater', 'skaters')}` : count(rows.length, 'skater', 'skaters');
    $('sk-more').hidden = !cut;
    $('sk-all').textContent = `Show all ${rows.length.toLocaleString('en-CA')}`;
  }
  function drawGoalies() {
    const rows = load(set).go.filter(keep(false)).sort(order(gs, goTies));
    $('go').tBodies[0].innerHTML = body(rows, GCOLS, gs, false) || `<tr><td colspan="30" class="empty">No goalies match.</td></tr>`;
    $('go-note').textContent = count(rows.length, 'goalie', 'goalies');
  }
  // The leaders among the picked season, league and team.
  function drawLeaders() {
    const d = load(set), sk = d.sk.filter(scope), go = d.go.filter(scope);
    const need = Math.max(1, Math.ceil(Math.max(0, ...go.map((r) => r.gp)) / 3));
    const tiles = [['Points', sk, 'p', skTies], ['Goals', sk, 'g', skTies], ['Assists', sk, 'a', skTies],
      set.nhl ? ['Rookie points', sk.filter((r) => r.r), 'p', skTies] : ['Plus-minus', sk, 'pm', skTies, (x) => signed(x)],
      ['Wins', go, 'w', goTies], ['Save percentage', go.filter((r) => r.gp >= need && r.svp != null), 'svp', goTies, F.sv]];
    $('leaders').innerHTML = tiles.map(([name, list, k, ties, f]) => {
      if (!list.length) return `<div><div class="l">${name}</div><div class="v soft">–</div><div class="s">Nobody yet<br>&nbsp;</div></div>`;
      const best = list.slice().sort(order({k, d: -1}, ties))[0];  // the same order as the table, so a tie names the same player
      const tied = list.filter((r) => r[k] === best[k]).length - 1;
      return `<div><div class="l">${name}${tied ? ` · ${tied + 1} tied` : ''}</div><div class="v">${f ? f(best[k]) : best[k]}</div><div class="s" title="${esc(best.n)}">${esc(best.n)}<br>${esc(best.t)}</div></div>`;
    }).join('');
  }
  function drawAll() { drawLeaders(); drawSkaters(); drawGoalies(); }

  // The games minimum: Rates and Value start at a third of the season so far, until the reader picks one.
  function fillMin() {
    const max = Math.max(1, ...load(set).sk.map((r) => r.gp));
    qual = Math.max(1, Math.round(max / 3));
    if (userMin && minGp > max) userMin = false;
    if (!userMin) minGp = VIEWS[view].rate ? qual : 0;
    const opts = [...new Set([0, 5, 10, 20, 30, 40, 50, 60].filter((x) => x < max).concat(qual, minGp))].sort((a, b) => a - b);
    $('min').innerHTML = opts.map((x) => `<option value="${x}"${x === minGp ? ' selected' : ''}>${x ? x + '+ games' : 'Any games'}</option>`).join('');
    minNote();
  }
  function minNote() { $('view-note').textContent = VIEWS[view].rate && minGp ? `Players with ${minGp}+ games. Change it with Minimum.` : ''; }
  function setView(v, keepSort) {
    view = viewOk(v) ? v : 'scoring';
    [...$('view').children].forEach((b) => { b.hidden = !viewOk(b.dataset.v); b.setAttribute('aria-pressed', b.dataset.v === view); });
    const mine = new Set(['n', 't', 'pos', 'age', 'gp', ...(set.nhl ? [] : ['lg', 'club']), ...cols().map((c) => c.k)]);
    if (!keepSort || !mine.has(ss.k)) { ss.k = VIEWS[view].sort; ss.d = VIEWS[view].dir || -1; }
    fillMin();
    heads();
  }
  // With a team picked, a phone drops the Team column, so the headers follow the team too.
  function heads() { head($('sk'), cols(), ss, drawSkaters, true); head($('go'), GCOLS, gs, drawGoalies, false); }
  // A new season or league: rebuild the menus that depend on it, then draw.
  function setup() {
    const d = load(set), n = {};
    d.sk.concat(d.go).forEach((r) => { if (r.lg) n[r.lg] = (n[r.lg] || 0) + 1; });
    const leagues = Object.keys(n).sort((a, b) => n[b] - n[a]);
    if (!leagues.includes(league)) league = '';
    $('lg').innerHTML = '<option value="">All leagues</option>' + leagues.map((l) => `<option value="${esc(l)}"${l === league ? ' selected' : ''}>${esc(l)}</option>`).join('');
    $('lg-wrap').hidden = set.nhl;
    $('rk-wrap').hidden = !set.nhl;
    if (!set.nhl) { rookies = false; $('rk').setAttribute('aria-pressed', 'false'); }
    all = false;
    setView(view, true);
    drawAll();
  }

  function pick(code) { team = code; $('t-pick').value = code; history.replaceState(null, '', code ? '#' + code : location.pathname + location.search); heads(); drawAll(); }
  $('set').addEventListener('change', (e) => { set = byId[e.target.value]; setup(); });
  $('lg').addEventListener('change', (e) => { league = e.target.value; all = false; drawAll(); });
  $('t-pick').addEventListener('change', (e) => pick(e.target.value));
  $('min').addEventListener('change', (e) => { minGp = +e.target.value; userMin = true; minNote(); drawSkaters(); drawGoalies(); });
  $('rk').addEventListener('click', () => { rookies = !rookies; $('rk').setAttribute('aria-pressed', rookies); drawAll(); });
  $('q').addEventListener('input', () => { drawSkaters(); drawGoalies(); });
  $('view').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; all = false; setView(b.dataset.v, false); drawAll(); });
  $('pos').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; pos = b.dataset.v;
    [...$('pos').children].forEach((x) => x.setAttribute('aria-pressed', x === b)); drawSkaters(); });
  $('sk-all').addEventListener('click', () => { all = true; drawSkaters(); });
  addEventListener('hashchange', () => { const c = hashTeam() || ''; if (c !== team) pick(c); });
  setup();
"""
