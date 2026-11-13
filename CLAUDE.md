# PHL league site (HLM27 sim league)

Zachary is GM of the Calgary Flames (CGY) in the PHL, an online Hockey Legacy Manager 27 league that uses real player names. This repo publishes the league site on GitHub Pages: https://zacharymichaud.github.io/phl-hml27/. It has six tabs: the GM trade report cards, plus team value, the cap board, standings, player stats and progression (added Nov 10, 2026).

Zachary is a developer. Keep answers short and decision-ready. The page is public to the whole league.

## Files

- `index.html`: tiny loader. It fetches the page named by `?p=` (`value`, `cap`, `standings`, `stats`, `progression`; no `p` is the trade report cards) with a cache-busting query, since GitHub Pages caches pages for 10 minutes. It only changes when a tab is added; keep `#hash` links working through it.
- `report.html`, `value.html`, `cap.html`, `standings.html`, `stats.html`, `progression.html`: the pages, generated. Commit them after every build.
- `build_report_cards.py`: builds `report.html` straight from the saves, then runs `site_pages.py` for the other tabs. No dependencies beyond Python.
- `site_shell.py`: what the tabs share. The tab bar (`PAGES`), the base styles, the page template, the loader and a few script helpers (sortable tables, a team picked by `#CODE`).
- `site_pages.py`: reads the newest save in full and runs the five builders below. `python site_pages.py --only cap,standings` rebuilds single pages in seconds; run alone it has no older saves, so the progression page loses its summer rollover and the player stats of earlier seasons lose the players who have since retired. Always finish with the full build.
- `site_value.py`, `site_cap.py`, `site_standings.py`, `site_stats.py`, `site_progression.py`: one builder per tab (see The other tabs).
- `fit_race_model.py`: refits the constants behind the playoff race. Run it once a season.
- `../saves/`: every official league save, one per sim block, outside the repo. Never commit saves.
- Trades posted in Discord need no tracking: the official saves include them. The old workbook is retired.

## After each sim block

1. Zachary drops the new save zip in `../saves/`.
2. Build, check the output (counts, a few cards and every tab in a browser), commit the six pages plus any script changes, push. Pages deploys on push.
   - A `CHECK:` line in the output is a move entered like a waiver claim or an offer sheet. Ask Zachary which it was and add its ids to the matching list (see How the ledger is built) before pushing.

Build command (reads every zip in `../saves/`, about a minute, and writes all six pages):

```
python build_report_cards.py
```

From the 25 saves through Jan 2, 2028 this gives 8 combined deals, 225 deals and 453 ledger rows (2026-27: 169 deals; 2027-28: 56). The 341 rows before July 1, 2027 reproduce the old ledger exactly. The other tabs print one line each: 32 teams over 4 periods; 1,318 contracts through 2034-35; 663 games played and 681 to play; 635 skaters and 65 goalies in the NHL (one skater kept after leaving the save), 1,292 players in other leagues and 4 tables, with goals matching the standings for 32 of 32 teams; 4,219 rating changes over 8 monthly ticks and 1 summer rollover.

## How the ledger is built

- Trades: the union of every save's `TradeHistory` (it resets at the season rollover), plus trades only the `DailyTradeRecapMailArgs` mails still hold (e.g. #4067, July 3, 2027).
- Waiver claims and offer sheets are entered in the game as trades but aren't trades, so the build leaves them out (`WAIVER_CLAIMS`, `OFFER_SHEETS`; confirmed by Zachary, Nov 9, 2026):
  - A waiver claim is the player plus the waiving team's 7th for the claiming team's 7th, then the two 7ths swapped back. Sept 18, 2027 (#4075 to #4086): Hunt FLA→COL, Gudas FLA→EDM, Balinskis FLA→SEA, Cole and Hart OTT→COL, Gaudreau SEA→COL. Oct 6, 2027 (#4096 to #4107): Primeau CAR→NYI, Jarry CGY→FLA, Pachal CGY→NYI, George NYI→CGY, Struble NYI→NYR, Benoît PHI→NYI. Dec 2, 2027 (#4117 and #4118): Sissons NYI→VAN (confirmed Nov 13, 2026).
  - An offer sheet is the player for nothing: McKown, Samson and Jack Smith, MTL→MIN, July 9, 2027 (#4069 to #4071).
  - Gustavsson LAK→NYI (#4062+4063, July 2, 2027) is entered like a claim but was a trade. It sits in `CHECKED_TRADES` with the OTT–VAN and FLA–PIT legs (see Open, below).
  - The build prints a `CHECK:` line for any other same-day group where a pick goes out and comes back, or a side sends nothing.
- A two-team row's value in is the partner's `ValueOutSum`; value out is its own.
- Salary kept by the sender is not in the trade history. It is read from the sending team's `DeadCapSpace` (`IsRetainedContract`, `PlayerId`, `DaySigned` = trade day); share = that amount / the player's full cap hit. When a team sent the same player twice in one day, the tag goes on the last trade. A third team's retention is in its participant's `Contracts`.
- Seasons run July 1 to June 30 (the league year). The page covers every season, with a season filter at the top that regrades from that season's trades only.
- Value today: the latest save's cached value; the cache is nearly empty on some days (Nov 2, 2027 had 48 of 2,126 players), so it falls back to the last save that holds one.

## The other tabs

All five read the newest save. Each page ends with a "How it works" section that states its rules for the league.

- **Team value** (`site_value.py`). Runs Zachary's value tool, `../tools/value_grades.py --json`, and lays out its data files (periods, teams, grades, breakdown, items, coverage: league data only). The tool lives outside the repo; without it the page is skipped and the old `value.html` stays. Its `PHASES` list needs a new entry as each season unfolds. The method text quotes the curve (B- at the league average, A+ from 1.6 standard deviations up, F below 1.6 down): keep it in step with the tool's `CURVE`.
- **Cap** (`site_cap.py`).
  - Cap hit = every NHL contract whose player is on the NHL club (`TeamId` equals the NHL team id) plus the team's `DeadCapSpace` (salary kept in a trade when `IsRetainedContract`, otherwise buyouts and carried-over money). The minors, junior and Europe don't count.
  - The game charges `Salaries` x `Edit` (that is `DailyCapHit` x the season's days). `Edit` is 1 on most contracts and a little under on 103 from the opening rosters; FLA's running total confirms it. The page uses salary x `Edit` everywhere.
  - "Charged so far" is the team's `AccumulatedSalaryCap`; "On pace for" adds today's cap hit for the days left (`SeasonDayId` of `SeasonLenght`).
  - Later seasons count today's NHL roster and dead cap, with a signed `Extension` from the season it starts, against today's cap.
  - UFA or RFA at expiry is worked out, not read: UFA at `REQUIRED_UFA_AGE` (27) on July 1, or after `REQUIRED_UFA_SEASON_EXPERIENCE` (7) seasons since `RookieSeason`.
  - Clause type 4 is a no-trade list (`Teams`, from contract year `StartingYear`). Types 2 and 3 show as "Clause", since which one is the no-move isn't confirmed.
  - On the Dec 2, 2027 save NSH sits $4.5M over the cap, as it did on Nov 2; FLA, $1.1M over then, is back under. How the game enforces the cap in season isn't confirmed.
- **Standings** (`site_standings.py`).
  - The table comes from the save's game list and matches every team's own `Stats` line. Ties: fewer games played, regulation wins, wins, goal difference (the NHL's order; the game's isn't confirmed).
  - The race is a simulation, seeded by the save date so a rebuild gives the same numbers. Strength = the lineup's number (average overall of the 12 forwards, 6 defencemen and the starter against the league, weighted by `BETA`), pulled toward the goal difference so far (prior SD `PRIOR_SD`, game variance `GAME_VAR`). A home win has log-odds `HOME` + `SLOPE` x the strength gap; `OT_SHARE` of games give the loser a point. 10,000 seasons. Playoffs are the top three per division plus two wild cards per conference. "1st pick" applies the league's lottery odds to the 16 teams that miss, with a winner moving up at most `LotteryMaxMoveUp` spots; a winner seeded too low leaves first overall with the last-place team, as in the NHL.
  - The constants come from `fit_race_model.py`, last run on the saves through Nov 2, 2027: log-loss 0.674 against 0.693 for a coin flip, on 4,907 game predictions. On 2026-27, lineups alone called games better than results to date did. Refit after each regular season and paste the constants into `site_standings.py`.
- **Player stats** (`site_stats.py`).
  - Source: each player's `_CareerStats`, one line per season type, league and club (columns under Save format). The NHL regular-season lines add up to every team's own `Stats` (goals, shots, wins); the build prints a `CHECK:` line if a team's goals don't.
  - The Season menu lists this season's NHL table, its playoffs once they start, this season's other leagues, then each earlier season since `FIRST_SEASON` (2026) with its playoffs. A table with no games is left out, so in September the page opens on last season.
  - Other leagues: only players whose NHL rights a team holds today (`TeamIds["0"]`), one line per league. Team is that NHL team, and Club is the club's name as the save has it.
  - An earlier season is read from the last save of that season (the saves' `Year`), which still has the players who retired after it: 7 skaters after 2026-27. Run alone, `site_pages.py` has no older saves and falls back to `pastathlete.hlm`, which lacks them (669 skaters instead of 676).
  - A player who leaves the save during this season (retired, or dropped by the game: the PlayerList loses him) keeps his NHL line, read from the last save of the season that held him, with no overall or cap hit (`departed` in `site_stats.py`, added Nov 13, 2026). Without it his team's goals stop matching the standings: B. Bradford (NYR, 2 GP, 1 goal, gone in December 2027) was the first. It needs the older saves, so `site_pages.py` run alone can't do it and prints the `CHECK:` line.
  - A traded player gets one line for the season, his teams joined (`CAR/MIN`); the team filter matches any of them.
  - Worked out on the page from the totals:
    - Per 60 uses all ice time. P/84 is points per game over `GamesPerSeason` (84 in this league).
    - +/- is on-ice goals for less against. The game leaves power-play goals out of both: the players' on-ice goals for come to exactly five times each team's non-power-play goals.
    - CF and CA are even-strength shot attempts: the players' sum is about 86% of five times the team's attempts.
    - PIM is twice the penalties taken (the game gives every penalty two minutes). FO% shows from four faceoffs a game.
    - GSAA is the league's save rate (every goalie in that league, counted in the build) applied to his shots, less his goals against.
    - $/point is this season's cap hit (salary x `Edit`) over points per 84 games. The Value view shows for this season's NHL table only.
  - Rookie: `RookieSeason["0"]` equals the season. The game's own 2026-27 rookie of the year (McKenna) fits it.
  - Rates and Value open at a games minimum of a third of the most games played, until the reader picks one; the other views open at any.
  - Age is today's for this season and on February 1 for an earlier one.
  - On a phone the tables keep to the screen: secondary columns hide, and the Team column hides once a team is picked.
- **Progression** (`site_progression.py`).
  - Monthly ticks come from every team's `ProgressionMailArgs` mail. A day counts when at least half the teams have one; the lone Sept 3, 2027 mail is one team's summer report.
  - The summer rollover is each player's overall in the last save of one season against the first save of the next (`Year` changes): July 3 to Sept 18, 2027. Over the summer every signed player sits on the NHL roster, so the club shown is the league he played most regular-season games in the season before, from `pastathlete.hlm`.

## Save format

A save is a zip. The live state is `<root>/dynamic/d0.hlm`, gzip-compressed JSON. Ignore the `auto/` copy (an older autosave).

- Top level: `SportLeague`, `TradeHistory`.
- Other files in the zip, all gzip JSON:
  - `static/t1.hlm`: `TradeOffers`, every trade from before the last season rollover, with `ValueOutSum`. `TradeHistory` holds the ones since, so the newest save alone lists every trade (#3832 to #4071 there and #4072 on in `TradeHistory`, as of Nov 2, 2027).
  - `pastathlete.hlm`: `Stats[player id]`, one entry per past season and league. No `Type` is a regular season; no `League` is the NHL.
  - `past.hlm` (team season lines), `season/<year>/` (that year's playoffs, game by game), `lineups/<year>/` (each team's end-of-season lineup and stats), `static/d0.hlm` (every draft, pick by pick).
- `SportLeague.LastSaveDay`: the save's game date. `SportLeague.Year`: the season the stats belong to; it rolls over in early September. `Leagues["0"]` is the NHL: `TeamList` (`ShortCity` is the team code; ids are under 100; CGY is 20) and `PickList` (`Year`, `Round`, `Original`, `Owner`, `_Value`). Used picks leave the PickList after the draft.
- `Leagues["0"].SaveGames`: the season's schedule. A played game has `WinnerID`, `LooserID`, `ScoreHome` and `ScoreAway` (missing means 0), `OT`, and `ShotHome`, `ShotAttempsHome`, `ShotBlockHome`, `FaceoffWinHome`, `HitHome`, `PowerPlayGoalHome` with their `Away` twins. `_StatType` 3 is a preseason game; none is the regular season. Overtime games all end by one goal, and there is no shootout flag.
- A team in `TeamList`: `Conference` and `Division` (missing means 0; names in `Leagues["0"].Conferences` and `.Divisions`), `Stats` (this season's line, with `PowerPlay`, `PowerPlayGoal`, `PenaltyKill`, `PenaltyKillGoalAgainst`), `LineUp` (`ForwardsIds`, `DefensesIds`, `GoaliesIds`, power-play and penalty-kill units, `ScratchedIds`), `AccumulatedSalaryCap`, `DeadCapSpace`, `TradeBlock`.
- `Leagues["0"]` also has `HardSalaryCap`, `SeasonDayId` (days into the season) and `ConfigOrDefault` (`SeasonLenght`, `GamesPerSeason`, `MaxContract`, `LotteryOdds` in thousandths, `LotteryMaxMoveUp`).
- `SportLeague.PlayerList`, keyed by player id (string):
  - `FirstName`, `LastName`, `$type` (Skater or Goalie), `Positions` (0 LW, 1 C, 2 RW, 3 LD, 4 RD, 5 G), `_PlayerType`, `BaseOffense`, `BaseDefense`, `Birthday` (days since 1970-01-01).
  - `AttributeBoost.Value`: the temporary modifier on the overall the game shows (see Ratings). Missing means none.
  - `TeamIds["0"]`: NHL organization; 100 is the free-agent pool.
  - `Contract`: `Salaries` are flat, so `Salaries[0]` is the cap hit, times `Edit` where the contract has one under 1 (see The other tabs). `Length` counts seasons left including the current or upcoming one; `SeasonPassed` is how far into `Salaries` the contract is. A `LeagueId` means a non-NHL deal (college, junior, Europe, AHL-only). `Extension` is a signed extension, starting when the contract ends. `Clause` is `{Type, StartingYear, Teams}`.
  - `TeamId`: the club the player is on now, in any league. It equals `TeamIds["0"]` when he is on the NHL roster. `RookieSeason["0"]`: his first NHL season.
  - `_CareerStats`: this season's stat lines, one per type, league and club, as comma-separated text with no names. An empty field is 0.
    - Every line starts: goalie flag (0 skater, 1 goalie), player id, type (0 regular season, 1 playoffs, 3 preseason), league id, club id, season.
    - Skater, columns 6 to 25: GP, goals, primary assists, shots, blocks, on-ice goals for, ice time in seconds, faceoff wins, faceoff losses, shot attempts for, shot attempts against, PIM, power-play goals, power-play assists, secondary assists, penalties drawn, on-ice goals against, hits, game-winning goals, hat tricks.
    - Goalie, columns 6 to 15: GP, wins (overtime wins included), goals against, saves, shutouts, ice time, goals saved above average (empty during the season), overtime wins, overtime losses, regulation losses.
    - Named Nov 10, 2026 by matching all 11,396 lines of 2026-27 against their copies in `pastathlete.hlm`, where the fields have names (`PenaltyTaken` there counts penalties, half the PIM). The lines reset at the September rollover.
  - `_ContractStatus`: 2 unsigned RFA, 3 unsigned draft pick, 4 signed.
  - `Values["0"]`: the game's trade value, cached.
  - `_Potential` (missing means 0): 0 Franchise, 1 Elite, 2 Top 6 F / Top 4 D / Starter, 3 Top 9 F / Top 6 D / Mid Starter, 4 4th line / 7th D / Backup, 5 Depth, 6 Minor, 7 Semipro, 8 Amateur.
  - `_Motivation` (missing means 0): 0 Absolute, 1 High, 2 Medium, 3 Low, 4 Poor, 5 potential reached.
  - `Drafted`: `{Year, Round, Pick (within the round), PickId}`. An entry with a `League` key is a non-NHL draft.
  - Retired players disappear from the PlayerList.
- `TradeHistory` entries: `{Id, Date, Participants, GeneratedByAI}`.
  - Each participant: `TeamId`, `PlayersId [{Athlete, TeamIndex}]`, `PlayersName`, `PicksId [{Id, Year, Round, OriginalTeam, TeamId}]`, `Contracts [{Item1 player id, Item2 retained fraction}]`, `ValueOutSum`.
  - `TeamIndex` on a player and `TeamId` on a pick give the receiving participant's index; missing means 0.
  - Pick ids are `YYYYRRTT` (year, round, original team id).
  - Skip `GeneratedByAI` trades (AI deals in other leagues). A participant with only `Contracts` is a third team retaining salary.
- `SportLeague.Mails`:
  - `ProgressionMailArgs`: one per team on the 2nd of each month from November to March. `Players [{Item1 id, Item2 new overall, Item3 change, Item4 club team, Item5 potential, Item6 motivation}]`. Mails stay in the save: the Nov 2, 2027 save still holds every tick since November 2026.
  - `TrainingCompletedMailArgs`: `{Player, TrainingType, TrainingValue}`.

## Values

- `ValueOutSum` is the game's value of what that participant sends, at the moment of the trade. It adds 5% to the players sent by every participant after the first (the league's trade difficulty, 1.05), never to picks. This is confirmed exactly on the July 1, 2027 trades.
- Some players also carry a 10% boost in `ValueOutSum` (× 1.1, or ÷ 1.1 when the value is negative), on either side. It looks like the receiving team's needs (`TradeBlock.Needs` on each team); not modelled.
- The Sept 1, 2026 opening save ("PHL Sept 1st 2026 Updated Rosters 2") has stale player values and no pick values. Use it for ratings, not values. The build skips any save without pick values when it looks up values.
- Each asset's value at the trade (`vt` on a card move), built per side:
  - A pick's `_Value` carries the day it was computed in `CachedValueExpiration` (`Item1` day of the year, `Item2` year), so the save holding the value from the trade day gives it exactly (355 of 360 picks).
  - A player's is `Values["0"]` from the trade-day save, one that already holds the trade first, else the nearest save.
  - The side is then made to add up to its `ValueOutSum`: the gap goes to its players, in proportion to their size. Single-asset sides are exact. From the 25 saves through Jan 2, 2028, 128 of 475 sides sent several assets that don't add up as is (the build prints them); their split is flagged `ve` and estimated.
- Value today: the latest cached value (see How the ledger is built). A player now a free agent or retired counts as 0. All 51 traded players now in free agency still carry a cached value, which the cards counted before Nov 9, 2026.

## Ratings

- The rating underneath: `round(w * BaseOffense + (1 - w) * BaseDefense)`, with halves rounding to even (Python `round`). Goalies use `BaseDefense`.
  - `w` by (position group, `_PlayerType` or 0): F1 .70, F2 .70, F7 .60, F0 .30, F3 .35, D4 .50, D5 .65, D6 .25.
- The overall the game shows (OVR) adds a temporary modifier: `AttributeBoost.Value` on the player, a hot or cold streak (±1 or 2) or playing hurt. 220 players carried one on Jan 2, 2028 (Pulock showed 84 on a rating of 85). The progression mails carry the shown number: rating plus modifier matches every mail in the Nov 2, 2027, Dec 2 and Jan 2, 2028 saves, where the rating alone missed one (C. Warren, 69 on a rating of 70). Use `Value`; its parts (`_performanceAttribute`, `_temporaryInjuryAttribute`) don't always add up to it.
- Which number each page uses (since Nov 13, 2026):
  - The shown OVR (`shown()` in `site_pages.py` and `build_report_cards.py`): the Cap and Player stats tabs, and on the trade cards and ledger the overall today. The overall at the trade adds the modifier only when a save from the trade day exists, since no other day records it.
  - The rating underneath (`overall()`): the overall-at-the-trade history (snapshots plus the mails' ticks), the Progression tab's summer rollover, and the Standings race, so a streak doesn't count as progression or move the projection. The Progression tab's monthly rows come straight from the mails, so they show the shown number.
- Ratings change only at the monthly ticks (+1 or +2), plus the odd point after training. On a tick day, the tick lands before that day's trades.
- The build works out the overall on any date from the nearest earlier save plus the mails. Do not trust the old workbook's overalls; 92 of them were a point off.
- Age regression happens only at the season rollover: in the official saves, 44 of the league's 112 players aged 34 or older lost 1 or 2 points there.

## Grading rules (decided with Zachary)

- The ledger has one row per team per trade.
  - Entries and exits text: `N. Name (OVR, age)`; picks as `YYYY R# (TEAM)` (the original team); retention as `[sender keeps X% of salary]`.
  - Each row also has value in, value out and net.
- Result: Even when |net| / (|in| + |out|) < 10%; otherwise Win or Loss.
- Edge = (in − out) / (in + out) per team.
- Grade cutoffs (minimum Edge): A+ .25, A .15, A- .10, B+ .07, B .04, B- .02, C+ 0, C −.02, C- −.04, D+ −.065, D −.085, D- −.10, F below that.
  - Fewer than 3 trades shows INC. Fewer than 8 trades gets an asterisk.
- Combined deals:
  - The game caps a trade at 5 assets per side. Same-day trades between the same two teams are graded as one deal (`3834+3856+3857`) when any part reaches 5 assets in for a team.
  - Zachary confirmed these same-day pairs were separate deals (`KEEP_SEPARATE`): 3837 (Pulock, MTL–NYI); 3972 (Nylander, OTT–TOR); the two CGY–NJD trades of July 1, 2027 (4049 and 4050); the CAR–SEA pair of July 1, 2027 (4042 and 4044); and the three PHI–CAR trades of Nov 2, 2027 (4109 Miller, 4112 Woll for Kerfoot, 4113 Thompson; confirmed Nov 11, 2026). One id per group is enough in the list.
  - `EXTRA_MERGES`: other groups to combine by hand; none now. The two it held, Calgary's Oct 6, 2027 moves, turned out to be waiver claims.
- Three-team trades 3931, 3942 and 3991 each have BUF retaining salary. Value out is each team's `ValueOutSum`; value in is the sum of what it received, valued per asset at the trade. Values (in/out):
  - 3931: BUF 566/0, OTT 131/764, TOR 481/414
  - 3942: BUF 253/34, DET 511/879, OTT 913/764
  - 3991: BUF 541/0, CHI 1964/2386, NYI 2386/2505
  - Until Nov 9, 2026 value in was a hand estimate (3931: BUF 455, OTT 170, TOR 553; 3942: BUF 203, DET 561; 3991: BUF 507, CHI 1998). The switch moved BUF from D- to D over all seasons, and for 2026-27 OTT from D to D- and TOR from C+ to C (3931 is now Even for TOR).
- Open: OTT–VAN (DeMelo and Hamara swapped three times) and FLA–PIT (Verhaeghe and two 7ths back and forth) look like corrections. Each leg counts for now; ask Zachary before changing.
## Next task

1. Done Nov 9, 2026: the ledger is built from the official saves and the workbook is retired.
2. Done Nov 9, 2026: each asset's value at the trade next to its value today, as a bar (see Values and Page conventions). Three-team trades are split by those values. Trades on 2027-06-24 and 2027-07-09 have no same-day save; their players use the nearest save.
3. Done Nov 10, 2026: the site has tabs. Team value, Cap, Standings and Progression sit beside the trade report cards (see The other tabs).
4. Done Nov 10, 2026: the Player stats tab (see The other tabs).
5. Next, when Zachary asks: a draft tracker (the 2026 and 2027 classes pick by pick, pick ownership with the game's pick values) and a transactions log (signings from the `DailySigningRecapMailArgs` mails, offer sheets, buyouts, retirements).

## Page conventions (Zachary's preferences)

- Real player names, always. The default HLM roster file uses altered names (e.g. "Morgan Foster" = Morgan Frost).
- Trade cards: no legends or explanatory text.
  - Potential badges use the game's motivation colours: m0 #2f6fd6, m1 #2b8a3e, m2 #e8890c (dark text), m3 #d03b3b, m4 #7f1d1d, m5 #6f7a89.
  - Shown player values include the game's 5% where it applied, so each column adds up.
  - Each asset shows `value at the trade → today`, the change, and a bar; every bar on a card shares one scale. Grey is value kept, solid blue value gained, faded red value lost; below zero, faded blue is negative value shed and solid red negative value taken on. Each side ends with a Total row in the same style, aligned across sides.
- Light and dark mode. Check a phone width.
- Season filter: "All seasons" by default; not kept in the URL.
- Hash links: `#CGY` for a team view, `#trade-<id>` for a card. Any part id works. Every tab takes `#CGY` too: `?p=cap#CGY` opens Calgary's cap sheet.
- Tabs: one row of links at the top of every page, the open one underlined. A new tab is a row in `site_shell.PAGES` plus a builder in `site_pages.build_all`; the loader picks it up on the next build.
- The new tabs follow the trade page: the same colours and table style, sortable headers, a team picker that keeps its choice in the address bar, and a short "How it works" section at the bottom. Bars are thin with the number beside them: blue for a gain, red for a loss or a team over the cap, grey otherwise.
- Only league-wide facts any GM could look up in the game go on the site. Calgary's plans and notes live in Zachary's private workspace, not here.
