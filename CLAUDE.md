# PHL report cards (HLM27 sim league)

Zachary is GM of the Calgary Flames (CGY) in the PHL, an online Hockey Legacy Manager 27 league that uses real player names. This repo publishes league-wide GM trade report cards on GitHub Pages: https://zacharymichaud.github.io/phl-hml27/

Zachary is a developer. Keep answers short and decision-ready. The page is public to the whole league.

## Files

- `index.html`: tiny loader that fetches `report.html` with a cache-busting query (GitHub Pages caches pages for 10 minutes). Never changes; keep `#hash` links working through it.
- `report.html`: the page, generated. Commit it after every build.
- `build_report_cards.py`: builds `report.html` straight from the saves. No dependencies beyond Python.
- `../saves/`: every official league save, one per sim block, outside the repo. Never commit saves.
- Trades posted in Discord need no tracking: the official saves include them. The old workbook is retired.

## After each sim block

1. Zachary drops the new save zip in `../saves/`.
2. Build, check the output (counts, a few cards in a browser), commit `report.html` plus any script changes, push. Pages deploys on push.

Build command (reads every zip in `../saves/`, about a minute):

```
python build_report_cards.py
```

From the 23 saves through Nov 2, 2027 this gives 10 combined deals, 238 deals and 479 ledger rows (2026-27: 169 deals; 2027-28: 69). The 341 rows before July 1, 2027 reproduce the old ledger exactly.

## How the ledger is built

- Trades: the union of every save's `TradeHistory` (it resets at the season rollover), plus trades only the `DailyTradeRecapMailArgs` mails still hold (e.g. #4067, July 3, 2027).
- A two-team row's value in is the partner's `ValueOutSum`; value out is its own.
- Salary kept by the sender is not in the trade history. It is read from the sending team's `DeadCapSpace` (`IsRetainedContract`, `PlayerId`, `DaySigned` = trade day); share = that amount / the player's full cap hit. When a team sent the same player twice in one day, the tag goes on the last trade. A third team's retention is in its participant's `Contracts`.
- Seasons run July 1 to June 30 (the league year). The page covers every season, with a season filter at the top that regrades from that season's trades only.
- Value today: the latest save's cached value; the cache is nearly empty on some days (Nov 2, 2027 had 48 of 2,126 players), so it falls back to the last save that holds one.

## Save format

A save is a zip. The live state is `<root>/dynamic/d0.hlm`, gzip-compressed JSON. Ignore the `auto/` copy (an older autosave).

- Top level: `SportLeague`, `TradeHistory`.
- `SportLeague.LastSaveDay`: the save's game date. `Leagues["0"]` is the NHL: `TeamList` (`ShortCity` is the team code; ids are under 100; CGY is 20) and `PickList` (`Year`, `Round`, `Original`, `Owner`, `_Value`). Used picks leave the PickList after the draft.
- `SportLeague.PlayerList`, keyed by player id (string):
  - `FirstName`, `LastName`, `$type` (Skater or Goalie), `Positions` (0 LW, 1 C, 2 RW, 3 LD, 4 RD, 5 G), `_PlayerType`, `BaseOffense`, `BaseDefense`, `Birthday` (days since 1970-01-01).
  - `TeamIds["0"]`: NHL organization; 100 is the free-agent pool.
  - `Contract`: `Salaries` are flat, so `Salaries[0]` is the cap hit. `Length` counts seasons left including the current or upcoming one. A `LeagueId` means a non-NHL deal (college, junior, Europe, AHL-only).
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
  - `ProgressionMailArgs`: one per team on the 2nd of each month from November to March. `Players [{Item1 id, Item2 new overall, Item3 change, Item4 club team, Item5 potential, Item6 motivation}]`.
  - `TrainingCompletedMailArgs`: `{Player, TrainingType, TrainingValue}`.

## Values

- `ValueOutSum` is the game's value of what that participant sends, at the moment of the trade. It adds 5% to the players sent by every participant after the first (the league's trade difficulty, 1.05), never to picks. This is confirmed exactly on the July 1, 2027 trades.
- The Sept 1, 2026 opening save ("PHL Sept 1st 2026 Updated Rosters 2") has stale player values and no pick values. Use it for ratings, not values.

## Ratings

- `OVR = round(w * BaseOffense + (1 - w) * BaseDefense)`, with halves rounding to even (Python `round`). Goalies use `BaseDefense`.
  - `w` by (position group, `_PlayerType` or 0): F1 .70, F2 .70, F7 .60, F0 .30, F3 .35, D4 .50, D5 .65, D6 .25.
  - This matches the game's own overall in the progression mails for 98% of players.
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
  - Zachary confirmed these same-day pairs were separate deals (`KEEP_SEPARATE`): 3837 (Pulock, MTL–NYI); 3972 (Nylander, OTT–TOR); the two CGY–NJD trades of July 1, 2027 (4049 and 4050); and the CAR–SEA pair of July 1, 2027 (4042 and 4044).
  - `EXTRA_MERGES`: Calgary's two Oct 6, 2027 deals, each entered as several trades with a 7th-round pick passed back and forth (4098+4099 Jarry to FLA; 4100 to 4103 Pachal for George with NYI). Zachary confirmed this merge.
- Three-team trades 3931, 3942 and 3991 each have BUF retaining salary. Each team's value is split per asset by estimate. Current values (in/out):
  - 3931: BUF 455/0, OTT 170/764, TOR 553/414
  - 3942: BUF 203/34, DET 561/879, OTT 913/764
  - 3991: BUF 507/0, CHI 1998/2386, NYI 2386/2505
- Open: OTT–VAN (DeMelo and Hamara swapped three times) and FLA–PIT (Verhaeghe and two 7ths back and forth) look like corrections. Each leg counts for now; ask Zachary before changing.

## Next task

1. Done Nov 9, 2026: the ledger is built from the official saves and the workbook is retired.
2. Show each asset's value at the trade next to its value today, marked up or down.
   - For each trade, read each asset's `Values["0"]` or `_Value` from the save dated on the trade day. Apply the 5% to players sent by participants after the first.
   - Check that they add up to each side's `ValueOutSum`, and report any side that doesn't.
   - Every trade date now has a save in `../saves/` except 2027-06-24 and 2027-07-09.
   - The Sep 1 deals need a save from after the opening-day trades. Without one, try the Sep 18 save (no ratings moved in between) and measure the fit.
   - With dated values, three-team trades can be split by real per-asset values instead of the estimate.

## Page conventions (Zachary's preferences)

- Real player names, always. The default HLM roster file uses altered names (e.g. "Morgan Foster" = Morgan Frost).
- Trade cards: no legends or explanatory text.
  - Potential badges use the game's motivation colours: m0 #2f6fd6, m1 #2b8a3e, m2 #e8890c (dark text), m3 #d03b3b, m4 #7f1d1d, m5 #6f7a89.
  - Shown player values include the game's 5% where it applied, so each column adds up.
- Light and dark mode. Check a phone width.
- Season filter: "All seasons" by default; not kept in the URL.
- Hash links: `#CGY` for a team view, `#trade-<id>` for a card. Any part id works.
- Other league context (rosters, cap, picks) lives in Zachary's claude.ai project, not here.
