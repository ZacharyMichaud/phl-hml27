#!/usr/bin/env python3
"""Build the HLM27 GM report cards site from HLM27_GM_Report_Cards.xlsx (and the league save).

Usage:
    python3 build_report_cards.py HLM27_GM_Report_Cards.xlsx [index.html] --save LEAGUE_SAVE.zip

Writes index.html (a small loader that never changes) and report.html (the page)
next to it; commit report.html after each update.

Reads the "Entries and Exits" sheet (one row per team per trade), the grade
cutoffs and sample-size limits on the "Method" sheet, and the team names from
the per-team tabs. Everything else (grades, ranks, chart) is computed in the
page itself, so replacing the workbook and re-running is the whole update.

--save (the league save zip, its unzipped folder, or its dynamic/d0.hlm) adds
the trade cards: every asset in every trade with position, overall, age,
contract and its value in that save. Without it the page still builds, and the
cards list the assets without values.
"""
import argparse
import datetime
import gzip
import json
import os
import re
import zipfile
from collections import defaultdict

from openpyxl import load_workbook

ap = argparse.ArgumentParser(description="Build the HLM27 GM report cards page.")
ap.add_argument("workbook", nargs="?", default="HLM27_GM_Report_Cards.xlsx")
ap.add_argument("out", nargs="?", default="index.html", help="loader file to write; report.html goes next to it")
ap.add_argument("--save", help="league save (.zip, unzipped folder, or dynamic/d0.hlm) for the trade cards")
args = ap.parse_args()

src, out = args.workbook, args.out
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
KEEP_SEPARATE = {"3837", "3972", "4041", "D#4"}  # Pulock (MTL-NYI), Nylander (OTT-TOR), Kuznetsov (CGY-NJD), CAR-SEA Discord D#4/D#7: separate deals
EXTRA_MERGES = []

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


# ---- Trade cards: every asset, from the league save ----------------------------
# The save records one value per side at the moment of a trade (ValueOutSum), not
# per asset. Each asset's value here is its value in this save; the page shows it
# beside the side's recorded value at the trade. In the recorded values the game
# adds 5% to the players sent by every participant after the first (the league's
# trade difficulty, 1.05), so those players are flagged to carry the same 5% now.
TRADE_MARKUP_FROM_PARTICIPANT = 1
POSITIONS = {0: "LW", 1: "C", 2: "RW", 3: "LD", 4: "RD", 5: "G"}
JUNIOR, COLLEGE = {"2", "3", "4"}, {"5", "6", "7", "8", "9", "10"}
ITEM_RE = re.compile(r"^(?P<name>.+?)(?: \((?P<ovr>\d+), (?P<age>\d+)\))?(?: \[sender keeps (?P<ret>\d+)% of salary\])?$")
PICK_RE = re.compile(r"^(?P<y>\d{4}) R(?P<r>\d) \((?P<o>[A-Z]{2,3})\)$")


def read_save(path):
    """The save's live state: dynamic/d0.hlm (gzip JSON), not the autosave copy under auto/."""
    if os.path.isdir(path):
        hits = [os.path.join(dp, "d0.hlm") for dp, _, fs in os.walk(path)
                if "d0.hlm" in fs and os.path.basename(dp) == "dynamic" and "auto" not in dp.split(os.sep)]
        raw = open(min(hits, key=len), "rb").read()
    elif zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            hits = [n for n in z.namelist() if n.endswith("dynamic/d0.hlm") and "/auto/" not in "/" + n]
            raw = z.read(min(hits, key=len))
    else:
        raw = open(path, "rb").read()
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)


def money(x):
    if x >= 1_000_000:
        s = f"{x / 1e6:.3f}".rstrip("0")
        return "$" + (s + "0" if s.endswith(".") else s) + "M"
    return f"${round(x / 1000)}K"


def ledger_items(text):
    """Entries/exits text -> [('p', name, ovr, age, ret%) | ('k', year, round, team)]."""
    out = []
    for it in (text or "").split("; "):
        if not it or it == "—":
            continue
        m = PICK_RE.match(it)
        if m:
            out.append(("k", int(m["y"]), int(m["r"]), m["o"]))
            continue
        m = ITEM_RE.match(it)
        out.append(("p", m["name"], int(m["ovr"]) if m["ovr"] else None,
                    int(m["age"]) if m["age"] else None, int(m["ret"]) if m["ret"] else None))
    return out


def build_cards(state, rows_by_part, deal_ids):
    sl = state["SportLeague"]
    lg = sl["Leagues"]["0"]
    code = {int(k): t["ShortCity"] for k, t in lg["TeamList"].items()}
    team_id = {c: i for i, c in code.items()}
    leagues = {str(k): v.get("Abbreviation") or "" for k, v in sl["Leagues"].items()}
    PL = sl["PlayerList"]
    pick_list = {f"{p['Year']}{p['Round']:02d}{p['Original']:02d}": p for p in lg["PickList"]}
    history = {str(t["Id"]): t for t in state.get("TradeHistory") or [] if not t.get("GeneratedByAI")}
    save_day = datetime.date.fromisoformat(sl["LastSaveDay"][:10])
    season0 = save_day.year if save_day.month >= 7 else save_day.year - 1
    per_round = len(code)
    drafted = {}
    for pid, p in PL.items():
        for d in p.get("Drafted") or []:
            if "League" not in d and str(d.get("PickId", "-1")) not in ("-1", ""):
                drafted[str(d["PickId"])] = (pid, (d["Round"] - 1) * per_round + d["Pick"])
    short_ids = defaultdict(list)
    for pid, p in PL.items():
        short_ids[f"{(p.get('FirstName') or '')[:1]}. {p.get('LastName') or ''}"].append(pid)

    # Overall and salary retention as the ledger shows them, keyed by (trade part, receiving team, short name).
    seen = {}
    for tid, rows in rows_by_part.items():
        for r in rows:
            for it in ledger_items(r["entries"]):
                if it[0] == "p":
                    seen[(tid, r["team"], it[1])] = it

    def age_of(p):
        b = datetime.date(1970, 1, 1) + datetime.timedelta(days=p["Birthday"])
        return save_day.year - b.year - ((save_day.month, save_day.day) < (b.month, b.day))

    def contract(p):
        con = p.get("Contract") or {}
        lid = con.get("LeagueId")
        if lid is not None and str(lid) != "0":
            ab = leagues.get(str(lid), "")
            return f"College ({ab})" if str(lid) in COLLEGE else f"Junior ({ab})" if str(lid) in JUNIOR else f"{ab} contract"
        sal = con.get("Salaries") or []
        if p.get("_ContractStatus") == 2:
            return "RFA, unsigned"
        if sal and sal[0] > 0 and con.get("Length"):
            last = season0 + con["Length"] - 1
            return f"{money(sal[0])} through {last}-{(last + 1) % 100:02d}"
        return "Unsigned draft pick" if p.get("_ContractStatus") == 3 else "Unsigned"

    people, picks, unresolved = {}, {}, []

    def person(pid, short=None, ovr=None):
        e = people.get(pid)
        if e is None:
            p = PL.get(pid)
            if p is None:  # gone from the save: retired
                e = {"n": short or "Unknown player", "x": "ret"}
            else:
                org_id = (p.get("TeamIds") or {}).get("0")
                e = {"n": f"{p.get('FirstName', '')} {p.get('LastName', '')}".strip(),
                     "pos": "/".join(POSITIONS.get(x, "?") for x in p.get("Positions") or []),
                     "age": age_of(p), "v": (p.get("Values") or {}).get("0")}
                if org_id in code:
                    e["org"], e["con"] = code[org_id], contract(p)
                else:
                    e["x"], e["con"] = "fa", "Free agent"
            people[pid] = e
        if ovr and not e.get("ovr"):
            e["ovr"] = ovr
        return e

    def pick(kid, year, rnd, orig):
        if kid not in picks:
            e = {"y": year, "r": rnd, "o": orig}
            live = pick_list.get(kid)
            if live is not None:
                e["v"], e["own"] = live.get("_Value"), code.get(live.get("Owner"), "")
            elif kid in drafted:
                e["dr"], e["no"] = drafted[kid]
                person(e["dr"])
            picks[kid] = e
        return "k:" + kid

    def from_history(tid):
        t = history[tid]
        ps = t["Participants"]
        sides = [code.get(p["TeamId"], str(p["TeamId"])) for p in ps]
        moves, holds = [], []
        for i, p in enumerate(ps):
            for nm, a in zip(p["PlayersName"], p["PlayersId"]):
                pid, to = str(a["Athlete"]), sides[a.get("TeamIndex", 0)]
                it = seen.get((tid, to, nm))
                person(pid, nm, it and it[2])
                m = {"a": "p:" + pid, "f": sides[i], "t": to, "part": tid}
                if i >= TRADE_MARKUP_FROM_PARTICIPANT:
                    m["mk"] = 1
                if it and it[4]:
                    m["ret"] = it[4]
                moves.append(m)
            for k in p["PicksId"]:
                moves.append({"a": pick(str(k["Id"]), int(k["Year"]), int(k["Round"]), code.get(int(k["OriginalTeam"]), k["OriginalTeam"])),
                              "f": sides[i], "t": sides[k.get("TeamId", 0)], "part": tid})
            for c in p.get("Contracts") or []:
                person(str(c["Item1"]))
                holds.append({"team": sides[i], "p": str(c["Item1"]), "pct": round(c["Item2"] * 100), "part": tid})
        return moves, holds

    def from_ledger(tid):
        """Trades not in the save (posted in Discord after it): match names against the save,
        valued the way the ledger estimated them (players plus 5%, picks as is)."""
        moves = []
        for r in rows_by_part[tid]:
            senders = [s.strip() for s in str(r["partner"]).split(",")]
            for it in ledger_items(r["entries"]):
                sender = senders[0]
                if it[0] == "k":
                    kid = f"{it[1]}{it[2]:02d}{team_id.get(it[3], 0):02d}"
                    moves.append({"a": pick(kid, it[1], it[2], it[3]), "f": sender, "t": r["team"], "part": tid})
                    continue
                _, name, ovr, age, ret = it
                cands = [pid for pid in short_ids.get(name, [])
                         if code.get((PL[pid].get("TeamIds") or {}).get("0")) in senders]
                if len(cands) > 1 and age:
                    cands = [pid for pid in cands if age_of(PL[pid]) == age]
                if len(cands) == 1:
                    pid = cands[0]
                    person(pid, name, ovr)
                    sender = code[(PL[pid].get("TeamIds") or {}).get("0")]
                else:
                    unresolved.append(f"{tid} {name}")
                    pid = "x:" + name
                    people.setdefault(pid, {"n": name, "age": age, "ovr": ovr})
                m = {"a": "p:" + pid, "f": sender, "t": r["team"], "part": tid, "mk": 1}
                if ret:
                    m["ret"] = ret
                moves.append(m)
        return moves

    deals = {}
    for tid in deal_ids:
        moves, holds, parts = [], [], []
        for p in tid.split("+"):
            if p in history:
                mv, hd = from_history(p)
                moves += mv
                holds += hd
                parts.append({"id": p})
            elif p in rows_by_part:
                moves += from_ledger(p)
                parts.append({"id": p, "est": 1})
        deals[tid] = {"parts": parts, "moves": moves}
        if holds:
            deals[tid]["holds"] = holds
    return {"date": save_day.isoformat()}, people, picks, deals, unresolved


save_info, people, pick_info, deals = None, {}, {}, {}
if args.save:
    deal_ids = sorted({d["trade"] for d in ledger}, key=lambda t: _num(t.split("+")[0]))
    save_info, people, pick_info, deals, unresolved = build_cards(read_save(args.save), by_trade, deal_ids)
    n_assets = sum(len(d["moves"]) for d in deals.values())
    print(f"trade cards: {len(deals)} deals, {n_assets} assets, values as of {save_info['date']}"
          + (f"; not found in the save: {', '.join(unresolved)}" if unresolved else ""))
else:
    print("no --save given: the trade cards will list assets without values")

data = {
    "ledger": ledger, "cutoffs": cutoffs, "teams": teams,
    "minTrades": min_trades, "fullTrades": full_trades, "evenBand": EVEN_BAND,
    "asOf": max(r["date"] for r in ledger),
    "built": datetime.date.today().isoformat(),
    "save": save_info, "people": people, "picks": pick_info, "deals": deals,
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
    --scrim: rgba(17, 32, 58, .55);
    --sans: "Helvetica Neue", Helvetica, Arial, "Segoe UI", Roboto, sans-serif;
    padding-top: env(safe-area-inset-top, 0px); padding-bottom: env(safe-area-inset-bottom, 0px);
  }
  @media (prefers-color-scheme: dark) { :root {
    --ice: #0e1726; --paper: #15213a; --ink: #edf2f8; --ink-soft: #9fb0c6; --line: #2a3850; --line-strong: #46587a;
    --blue: #6aa6ee; --blue-soft: #1c3458; --red: #f0636b; --red-soft: #4b1f24; --stamp: #f0636b; --hover: #1d2d4a;
    --scrim: rgba(3, 8, 16, .66);
  } }
  * { box-sizing: border-box; }
  html { scroll-padding-top: env(safe-area-inset-top, 0px); }
  html:has(dialog[open]) { overflow: hidden; }
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
  /* Every trade */
  .find { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; margin-bottom: 10px; }
  .find input { font: inherit; color: var(--ink); background: var(--paper); border: 1px solid var(--line-strong); border-radius: 4px; padding: 7px 10px; width: min(100%, 24rem); }
  td.gist { white-space: normal; min-width: 17rem; }
  @media (max-width: 760px) { td.gist { min-width: 9.5rem; } }
  .method p { margin-bottom: 10px; }
  .method b { font-weight: 700; }
  .cut { max-width: 20rem; margin-top: 10px; }
  .foot { margin-top: 48px; padding-top: 14px; border-top: 1px solid var(--line); color: var(--ink-soft); font-size: 13px; }
  :focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
  /* Trade card: a two-column trade sheet, one column per team, in a modal. */
  dialog.card { padding: 0; border: 1px solid var(--line-strong); border-radius: 6px; background: var(--paper); color: var(--ink);
    width: min(960px, calc(100vw - 32px)); max-width: none; max-height: calc(100vh - 32px); max-height: calc(100dvh - 32px); overflow: auto; overscroll-behavior: contain;
    box-shadow: 0 18px 50px rgba(0, 0, 0, .3); }
  dialog.card::backdrop { background: var(--scrim); }
  .card-head { position: sticky; top: 0; z-index: 2; background: var(--paper); border-bottom: 2px solid var(--ink); padding: 16px 22px 12px;
    display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 16px; align-items: start; }
  .card-meta { color: var(--ink-soft); font-size: 13px; grid-column: 1; }
  #deal-title:focus { outline: none; }
  .card-head h2 { font-size: clamp(22px, 3.2vw, 28px); font-weight: 800; letter-spacing: -0.02em; line-height: 1.12; grid-column: 1; }
  .card-tools { grid-column: 2; grid-row: 1 / span 2; display: flex; gap: 8px; }
  .card-tools button { font: inherit; font-size: 13px; color: var(--ink); background: var(--paper); border: 1px solid var(--line-strong); border-radius: 4px; padding: 6px 10px; cursor: pointer; }
  .card-tools button:hover { background: var(--hover); }
  .card-tools .x { font-size: 20px; line-height: 1; padding: 3px 10px 5px; }
  .verdict { padding: 14px 22px 4px; }
  .verdict .then { font-size: 17px; font-weight: 700; letter-spacing: -0.01em; max-width: none; }
  .verdict .now { color: var(--ink-soft); margin-top: 3px; max-width: none; }
  .sides { display: grid; grid-template-columns: repeat(var(--n, 2), minmax(0, 1fr)); }
  .side { margin: 0; padding: 12px 22px 18px; border-right: 1px solid var(--line); min-width: 0; }
  .side:last-child { border-right: 0; }
  .side h3 { font-size: 15px; font-weight: 700; margin: 0; padding-bottom: 7px; border-bottom: 1px solid var(--line-strong); }
  .side.me h3 { color: var(--blue); }
  .assets { list-style: none; margin: 0; padding: 0; }
  .asset { padding: 9px 0 8px; border-bottom: 1px solid var(--line); }
  .a-top { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
  .a-name { font-weight: 600; overflow-wrap: anywhere; }
  .a-val { font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .a-val.neg { color: var(--red); }
  .a-val.none { color: var(--ink-soft); font-weight: 400; }
  .a-meta { color: var(--ink-soft); font-size: 13px; }
  .a-flag { color: var(--ink); font-size: 13px; }
  .a-part { display: inline-block; margin-left: 6px; padding: 0 5px; border: 1px solid var(--line-strong); border-radius: 3px; color: var(--ink-soft); font-size: 12px; font-weight: 400; vertical-align: 1px; }
  .asset.hold .a-name { font-weight: 400; }
  .tot { margin: 10px 0 0; }
  .tot div { display: flex; justify-content: space-between; gap: 12px; padding: 1px 0; font-variant-numeric: tabular-nums; }
  .tot dt { color: var(--ink-soft); font-size: 13px; }
  .tot dd { margin: 0; color: var(--ink-soft); }
  .tot .sum { border-top: 1px solid var(--line-strong); margin-top: 4px; padding-top: 5px; }
  .tot .sum dt, .tot .sum dd { color: var(--ink); font-size: 15px; font-weight: 700; }
  .tot .was dd { color: var(--ink); }
  .card-notes { padding: 6px 22px 22px; padding-bottom: calc(22px + env(safe-area-inset-bottom, 0px)); color: var(--ink-soft); font-size: 13px; }
  .card-notes p { margin-top: 8px; max-width: 86ch; }
  @media (max-width: 680px) {
    dialog.card { width: 100vw; height: 100vh; height: 100dvh; max-height: none; margin: 0; border: 0; border-radius: 0; }
    .card-head { padding: calc(12px + env(safe-area-inset-top, 0px)) 16px 10px; }
    .verdict, .side, .card-notes { padding-left: 16px; padding-right: 16px; }
    .sides { grid-template-columns: 1fr; }
    .side { border-right: 0; border-bottom: 1px solid var(--line-strong); }
  }
  @media (prefers-reduced-motion: no-preference) {
    dialog.card[open] { animation: card-in .16s ease-out; }
    @keyframes card-in { from { opacity: 0; transform: translateY(10px); } }
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>HLM27 GM report cards</h1>
    <p class="lede">Every GM graded on the trade value they took in versus sent out, across <b id="n-trades"></b> GM-to-GM trades from <b id="d-first"></b> to <b id="d-last"></b>. Click a team to see every entry and exit, and any trade to see what each asset is worth.</p>
    <p class="meta">Through the league save of <span id="as-of"></span>. Updated <span id="built"></span>. <a id="dl" href="#" download="hlm27_trade_ledger.csv">Download the full ledger (CSV)</a><span id="dl-assets-wrap" hidden> or <a id="dl-assets" href="#" download="hlm27_trade_assets.csv">every asset traded (CSV)</a></span>.</p>
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
    <p class="note">Trade by trade, newest first. Players show their current overall and age. Click a trade to open its card.</p>
    <p class="empty" id="t-empty" hidden>No trades yet this season.</p>
    <div class="scroll">
      <table id="trades-table">
        <thead><tr><th>Date</th><th>Partner</th><th>Entries (received)</th><th>Exits (sent)</th><th class="num">Value in</th><th class="num">Value out</th><th class="num">Net</th><th>Result</th><th class="sec">Note</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <section id="every">
    <div class="head"><h2>Every trade</h2><span class="note">Newest first. Click a trade for each asset's value, at the trade and now.</span></div>
    <div class="find">
      <input type="search" id="q" placeholder="Search a player, team or pick" aria-label="Search trades" autocomplete="off">
      <span class="note" id="q-count" aria-live="polite"></span>
    </div>
    <div class="scroll">
      <table id="all-table">
        <thead><tr><th>Date</th><th class="sec">Teams</th><th>Deal</th><th class="num sec">Value moved</th><th>Result</th></tr></thead>
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
    <p id="m-cards" hidden><b>Trade cards.</b> Click any trade, in a team's list or under Every trade, to open its card: each player with position, overall, age and current contract, each pick, and what every asset is worth in the save of <span id="m-save"></span>. The game stores one value per side at the moment of a trade, not one per asset, so each side's value at the trade sits beside what the same assets are worth now; the gap is how the trade has aged. The recorded values add 5% to the players sent by one side of each trade (the league's trade difficulty, 1.05), so values now add the same 5% to those players to compare like for like. A player who has since left as a free agent or retired counts as 0, a 2027 pick counts as the player drafted with it, and a negative value means the game counts the contract as a cost.</p>
    <p><b>What it measures.</b> Asset value, not whether a trade helped a team win. Cap dumps, rentals and win-now veterans for young talent count as value lost. Where a team took picks to retain salary, that shows as value won, since the game does not price the cap cost. Three-team trades are split per asset by estimate. Players are shown with their overall and age as of the latest save, not at trade time.</p>
    <table class="cut"><thead><tr><th class="num">Minimum Edge</th><th>Grade</th></tr></thead><tbody id="cut-body"></tbody></table>
  </section>

  <footer class="foot">Calgary Flames front office, HLM27 sim league. Grades are a measure of trade value, not of who built the better team.</footer>
</div>

<dialog class="card" id="deal" aria-labelledby="deal-title">
  <header class="card-head">
    <p class="card-meta" id="deal-meta"></p>
    <h2 id="deal-title" tabindex="-1"></h2>
    <div class="card-tools">
      <button type="button" class="copy" id="deal-copy">Copy link</button>
      <button type="button" class="x" id="deal-close" aria-label="Close">&times;</button>
    </div>
  </header>
  <div class="verdict"><p class="then" id="deal-then"></p><p class="now" id="deal-now"></p></div>
  <div class="sides" id="deal-sides"></div>
  <div class="card-notes" id="deal-notes"></div>
</dialog>

<script id="data" type="application/json">__DATA__</script>
<script>
(() => {
  const D = JSON.parse(document.getElementById('data').textContent);
  const MIN = D.minTrades, FULL = D.fullTrades;
  const $ = (id) => document.getElementById(id);
  const fmtInt = (n) => Number(n).toLocaleString('en-US').replace('-', '−');
  const fmtNet = (n) => (n > 0 ? '+' : n < 0 ? '−' : '') + Number(Math.abs(n)).toLocaleString('en-US');
  const fmtPct = (v) => (v * 100).toFixed(1) + '%';
  const fmtEdge = (v) => (v > 0 ? '+' : v < 0 ? '−' : '') + (Math.abs(v) * 100).toFixed(1) + '%';
  const fmtDate = (s) => new Date(s + 'T00:00:00Z').toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'});
  const fmtLong = (s) => new Date(s + 'T00:00:00Z').toLocaleDateString('en-US', {month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC'});
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
  const csvUrl = (rows) => URL.createObjectURL(new Blob(['\ufeff' + rows.map((r) => r.map(csvCell).join(',')).join('\r\n')], {type: 'text/csv'}));
  const cols = ['date', 'trade', 'team', 'partner', 'entries', 'exits', 'players_in', 'players_out', 'picks_in', 'picks_out', 'value_in', 'value_out', 'net', 'result', 'note'];
  $('dl').href = csvUrl([cols, ...D.ledger.map((r) => cols.map((c) => r[c]))]);

  // ---- State: the picked team, or an open trade, lives in the URL hash ----
  const valid = (c) => c && by[c] ? c : null;
  let picked = valid((location.hash || '').replace(/^#/, '').toUpperCase()) || 'CGY';
  let sort = {key: 'rank', dir: 1};
  const pick = (code, scroll) => {
    picked = code; history.replaceState(null, '', '#' + code);
    render();
    if (scroll) $('team').scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
  };

  const cell = (tr, text, cls) => { const td = document.createElement('td'); td.textContent = text; if (cls) td.className = cls; tr.appendChild(td); return td; };
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };

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
  const svgEl = (tag, attrs, text) => { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (text != null) n.textContent = text; return n; };
  const renderChart = () => {
    const box = $('edge-chart'); box.replaceChildren();
    const rows = cards.filter((r) => r.trades > 0 && r.edge != null).slice().sort((a, b) => b.edge - a.edge);
    const W = Math.max(320, box.clientWidth), rowH = 20, mTop = 6, mBot = 28, mRight = 60, H = mTop + rowH * rows.length + mBot;
    const svg = svgEl('svg', {viewBox: '0 0 ' + W + ' ' + H, width: '100%', role: 'img', 'aria-label': 'Edge by team, as bars'}); box.appendChild(svg);
    const probe = svgEl('text', {'font-size': 12}, ''); svg.appendChild(probe);
    let mLeft = 0; for (const r of rows) { probe.textContent = r.team; mLeft = Math.max(mLeft, probe.getComputedTextLength()); } probe.remove(); mLeft = Math.ceil(mLeft) + 10;
    const lo = Math.min(0, ...rows.map((r) => r.edge)), hi = Math.max(0, ...rows.map((r) => r.edge));
    const step = 0.1, dLo = Math.floor(lo / step) * step, dHi = Math.ceil(hi / step) * step;
    const x = (v) => mLeft + (v - dLo) / (dHi - dLo) * (W - mLeft - mRight);
    const y = (i) => mTop + i * rowH;
    const axisY = mTop + rowH * rows.length;
    for (let v = dLo; v <= dHi + 1e-9; v += step) {
      svg.appendChild(svgEl('line', {x1: x(v), x2: x(v), y1: mTop, y2: axisY, stroke: 'var(--line)', 'stroke-width': 1}));
      svg.appendChild(svgEl('text', {x: x(v), y: axisY + 16, 'text-anchor': 'middle', 'font-size': 11, fill: 'var(--ink-soft)'}, (v > 0 ? '+' : '') + Math.round(v * 100) + '%'));
    }
    svg.appendChild(svgEl('line', {x1: x(0), x2: x(0), y1: mTop, y2: axisY, stroke: 'var(--line-strong)'}));
    const tip = document.createElement('div'); tip.className = 'tip'; tip.hidden = true; const t1 = document.createElement('div'); t1.className = 't'; const t2 = document.createElement('div'); tip.append(t1, t2); box.appendChild(tip);
    rows.forEach((r, i) => {
      const me = r.team === picked;
      svg.appendChild(svgEl('text', {x: mLeft - 6, y: y(i) + rowH / 2, dy: '0.35em', 'text-anchor': 'end', 'font-size': 12, 'font-weight': me ? 700 : 400, fill: me ? 'var(--ink)' : 'var(--ink-soft)'}, r.team));
      const bar = svgEl('rect', {x: Math.min(x(0), x(r.edge)), y: y(i) + 3, width: Math.max(1, Math.abs(x(r.edge) - x(0))), height: rowH - 6, rx: 2, fill: r.edge >= 0 ? 'var(--blue)' : 'var(--red)', opacity: me ? 1 : 0.55, style: 'cursor:pointer'});
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
      svg.appendChild(svgEl('text', {x: Math.max(x(0), x(r.edge)) + 4, y: y(i) + rowH / 2, dy: '0.35em', 'font-size': 11, fill: 'var(--ink-soft)'}, fmtEdge(r.edge)));
    });
  };

  // ---- Deals: one per trade number, newest first ----
  const rowsOf = {};
  for (const r of D.ledger) (rowsOf[r.trade] = rowsOf[r.trade] || []).push(r);
  const tradeKey = (t) => { const p = t.split('+')[0]; return p.startsWith('D#') ? 1e6 + +p.slice(2) : +p; };
  const dealIds = Object.keys(rowsOf).sort((a, b) => rowsOf[b][0].date.localeCompare(rowsOf[a][0].date) || tradeKey(b) - tradeKey(a));
  const slugOf = (t) => t.split('+')[0].replace('#', '');
  const bySlug = {};
  for (const t of dealIds) for (const p of t.split('+')) bySlug[p.replace('#', '').toUpperCase()] = t;
  const nameOf = (c) => (by[c] && by[c].name) || c;
  const leadRow = (rows, persp) => rows.find((r) => r.team === persp) || rows.find((r) => r.result === 'Win') || rows.slice().sort((a, b) => b.net - a.net || a.team.localeCompare(b.team))[0];
  const gist = (r) => { const n = parts(r.entries).length; return r.team + ' got ' + (n ? head(r.entries) + (n > 1 ? ' + ' + (n - 1) + ' more' : '') : 'nothing'); };
  const moved = (rows) => rows.length === 2 ? Math.abs(rows[0].value_in) + Math.abs(rows[0].value_out) : rows.reduce((s, r) => s + Math.abs(r.value_in), 0);

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
    const rows = D.ledger.filter((x) => x.team === picked).sort((a, b) => b.date.localeCompare(a.date) || tradeKey(b.trade) - tradeKey(a.trade));
    for (const x of rows) {
      const tr = document.createElement('tr'); tr.className = 'pick'; tr.tabIndex = 0; tr.dataset.trade = x.trade;
      cell(tr, fmtDate(x.date)); cell(tr, x.partner); cell(tr, x.entries, 'text'); cell(tr, x.exits, 'text');
      cell(tr, fmtInt(x.value_in), 'num'); cell(tr, fmtInt(x.value_out), 'num');
      const n = +x.net; cell(tr, fmtNet(n), 'num ' + (n > 0 ? 'win' : n < 0 ? 'loss' : 'even'));
      cell(tr, x.result, x.result === 'Win' ? 'win' : x.result === 'Loss' ? 'loss' : 'even');
      cell(tr, x.note || '', 'text sec');
      tb.appendChild(tr);
    }
  };

  // ---- Every trade ----
  const fold = (s) => String(s).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const P = D.people || {}, K = D.picks || {}, DEALS = D.deals || {}, SAVE = D.save;
  const hay = {};
  for (const t of dealIds) {
    let s = [t, fmtLong(rowsOf[t][0].date), ...rowsOf[t].map((r) => r.team + ' ' + nameOf(r.team) + ' ' + r.entries)].join(' ');
    for (const m of (DEALS[t] || {}).moves || []) {
      const id = m.a.slice(2);
      if (m.a[0] === 'p') s += ' ' + ((P[id] || {}).n || ''); else if (K[id] && K[id].dr) s += ' ' + ((P[K[id].dr] || {}).n || '');
    }
    hay[t] = fold(s);
  }
  const renderAll = () => {
    const q = fold($('q').value.trim()), words = q ? q.split(/\s+/) : [];
    const tb = $('all-table').tBodies[0]; tb.replaceChildren();
    let shown = 0;
    for (const t of dealIds) {
      if (words.length && !words.every((w) => hay[t].includes(w))) continue;
      shown++;
      const rows = rowsOf[t], lead = leadRow(rows, null);
      const ordered = [lead, ...rows.filter((r) => r !== lead)];
      const tr = document.createElement('tr'); tr.className = 'pick'; tr.tabIndex = 0; tr.dataset.trade = t;
      cell(tr, fmtDate(rows[0].date));
      cell(tr, ordered.map((r) => r.team).join('–'), 'sec');
      cell(tr, ordered.map(gist).join('; '), 'gist');
      cell(tr, fmtInt(moved(rows)), 'num sec');
      const wins = rows.filter((r) => r.result === 'Win').sort((a, b) => b.net - a.net);
      cell(tr, wins.length ? wins.map((r) => r.team + ' ' + fmtNet(r.net)).join(', ') : 'Even', wins.length ? '' : 'even');
      tb.appendChild(tr);
    }
    $('q-count').textContent = words.length ? shown + ' of ' + dealIds.length + ' trades' : dealIds.length + ' trades';
  };
  $('q').addEventListener('input', renderAll);

  // ---- Trade card ----
  const ORD = ['', '1st', '2nd', '3rd', '4th', '5th', '6th', '7th'];
  const WORD = {Win: 'a win', Loss: 'a loss', Even: 'even'};
  const listJoin = (a) => a.length < 3 ? a.join(' and ') : a.slice(0, -1).join(', ') + ' and ' + a[a.length - 1];
  const pickName = (k) => k.y + ' ' + (ORD[k.r] || 'R' + k.r) + ' round (' + k.o + ')';
  const assetOf = (m) => {
    const id = m.a.slice(2);
    if (m.a[0] === 'p') { const p = P[id] || {n: id}; return {kind: 'p', p, v: p.v ?? null}; }
    const k = K[id] || {}, d = k.dr ? P[k.dr] || {} : null;
    return {kind: 'k', k, d, v: d ? d.v ?? null : k.v ?? null};
  };
  const sideNow = (deal, team, dir) => {
    let raw = 0, mk = 0;
    for (const m of deal.moves) if ((dir === 'in' ? m.t : m.f) === team) { const v = assetOf(m).v || 0; raw += v; if (m.mk) mk += v; }
    const now = Math.round(raw + 0.05 * mk);
    return {raw, markup: now - raw, now};
  };
  const callOf = (vin, vout) => {
    const mv = Math.abs(vin) + Math.abs(vout), bal = mv ? (vin - vout) / mv : 0;
    return {net: vin - vout, bal, res: Math.abs(bal) < D.evenBand ? 'Even' : vin > vout ? 'Win' : 'Loss'};
  };
  const share = (bal) => (Math.abs(bal) * 100).toFixed(1) + '% of the value moved';

  const thenLine = (rows, lead) => {
    const band = '±' + Math.round(D.evenBand * 100) + '%';
    if (rows.length === 2) {
      const c = callOf(lead.value_in, lead.value_out);
      if (lead.result === 'Even') return 'Even trade: ' + nameOf(lead.team) + ' came out ' + (lead.net >= 0 ? 'ahead' : 'behind') + ' by ' + fmtInt(Math.abs(lead.net)) + ', ' + share(c.bal) + ', inside the ' + band + ' band.';
      return nameOf(lead.team) + ' ' + (lead.result === 'Win' ? 'won' : 'lost') + ' the trade by ' + fmtInt(Math.abs(lead.net)) + ', ' + share(c.bal) + '.';
    }
    const s = rows.slice().sort((a, b) => b.net - a.net);
    return 'Three-team trade: ' + s.map((r) => nameOf(r.team) + ' ' + fmtNet(r.net) + ', ' + WORD[r.result]).join('; ') + '.';
  };
  const nowLine = (deal, rows, lead) => {
    if (deal.parts.every((p) => p.est)) return 'Values estimated from the ' + fmtLong(SAVE.date) + ' save, since this trade came after it.';
    const label = 'With ' + fmtLong(SAVE.date) + ' values: ';
    const now = (r) => callOf(sideNow(deal, r.team, 'in').now, sideNow(deal, r.team, 'out').now);
    if (rows.length === 2) {
      const c = now(lead);
      return label + nameOf(lead.team) + ' ' + fmtNet(c.net) + ' (' + (Math.abs(c.bal) * 100).toFixed(1) + '%), ' + (c.res === lead.result ? 'still ' : 'now ') + WORD[c.res] + '.';
    }
    return label + rows.map((r) => ({r, c: now(r)})).sort((a, b) => b.c.net - a.c.net).map(({r, c}) => nameOf(r.team) + ' ' + fmtNet(c.net)).join(', ') + '.';
  };

  const assetItem = (m, multi, three, est) => {
    const a = assetOf(m), li = el('li', 'asset');
    const topLine = el('div', 'a-top'), nm = el('span', 'a-name');
    const flags = [];
    let metas = [];
    if (a.kind === 'p') {
      const p = a.p;
      nm.textContent = p.n || '';
      metas.push([p.pos, p.ovr ? p.ovr + ' OVR' : '', p.age ? 'age ' + p.age : ''].filter(Boolean).join(', '));
      if (p.con && !p.x) metas.push(p.con);
      if (p.x === 'ret') flags.push('Retired, so no value now');
      else if (p.x === 'fa') flags.push('Free agent now, so no value');
      else if (p.org && p.org !== m.t && !est) flags.push('Now with ' + p.org);
      if (m.ret) flags.push(m.f + ' kept ' + m.ret + '% of his salary');
    } else {
      nm.textContent = pickName(a.k);
      if (a.d) {
        metas.push('Used: #' + a.k.no + ' overall, ' + (a.d.n || ''));
        metas.push([a.d.pos, a.d.ovr ? a.d.ovr + ' OVR' : '', a.d.age ? 'age ' + a.d.age : ''].filter(Boolean).join(', '));
        if (a.d.x === 'fa') flags.push('Free agent now'); else if (a.d.org && a.d.org !== m.t && !est) flags.push('Now with ' + a.d.org);
      } else if (a.k.y) {
        metas.push('Not used yet' + (a.k.own && a.k.own !== m.t && !est ? ', now owned by ' + a.k.own : ''));
      }
    }
    if (three) metas.unshift('From ' + m.f);
    if (multi) nm.appendChild(el('span', 'a-part', '#' + m.part));
    const val = el('span', 'a-val' + (a.v == null ? ' none' : a.v < 0 ? ' neg' : ''), a.v == null ? '—' : fmtInt(a.v));
    topLine.append(nm, val); li.appendChild(topLine);
    for (const t of metas) if (t) li.appendChild(el('div', 'a-meta', t));
    if (flags.length) li.appendChild(el('div', 'a-flag', flags.join('. ') + '.'));
    li._v = a.v ?? -Infinity;
    return li;
  };
  const totals = (rows) => {
    const dl = el('dl', 'tot');
    for (const [cls, label, value] of rows) { const d = el('div', cls); d.append(el('dt', '', label), el('dd', '', value)); dl.appendChild(d); }
    return dl;
  };

  const renderDeal = (tid, persp) => {
    const rows = rowsOf[tid], deal = DEALS[tid], lead = leadRow(rows, persp);
    const order = [lead, ...rows.filter((r) => r !== lead)];
    const date = rows[0].date, three = rows.length > 2;
    const partIds = tid.split('+');
    $('deal-meta').textContent = fmtLong(date) + ', ' + (tid.startsWith('D#') ? 'posted in Discord as ' + tid
      : partIds.length > 1 ? 'trades ' + listJoin(partIds) + ', graded as one deal' : 'trade ' + tid);
    $('deal-title').textContent = order.map((r) => nameOf(r.team)).join('–');
    const thenEl = $('deal-then');
    thenEl.textContent = thenLine(rows, lead);
    thenEl.className = 'then ' + (three ? '' : lead.result === 'Win' ? 'win' : lead.result === 'Loss' ? 'loss' : 'even');
    $('deal-now').textContent = deal && SAVE ? nowLine(deal, rows, lead) : '';
    $('deal-now').hidden = !(deal && SAVE);
    const box = $('deal-sides'); box.replaceChildren(); box.style.setProperty('--n', order.length);
    for (const r of order) {
      const sec = el('section', 'side' + (persp && r.team === persp ? ' me' : ''));
      sec.appendChild(el('h3', '', nameOf(r.team) + ' received'));
      const ul = el('ul', 'assets');
      if (deal) {
        const estParts = new Set(deal.parts.filter((p) => p.est).map((p) => p.id));
        const lis = deal.moves.filter((m) => m.t === r.team).map((m) => assetItem(m, partIds.length > 1, three, estParts.has(m.part)));
        lis.sort((a, b) => b._v - a._v);
        ul.append(...lis);
        for (const h of deal.holds || []) if (h.team === r.team) {
          const li = el('li', 'asset hold'); const t = el('div', 'a-top');
          t.append(el('span', 'a-name', 'Took on ' + h.pct + '% of ' + ((P[h.p] || {}).n || 'a player') + '’s salary'), el('span', 'a-val none', '—'));
          li.append(t, el('div', 'a-meta', 'Cap cost only; the game gives it no value'));
          ul.appendChild(li);
        }
        if (!ul.children.length) ul.appendChild(el('li', 'asset a-meta', 'Nothing'));
      } else {
        for (const p of parts(r.entries)) { const li = el('li', 'asset'); li.appendChild(el('div', 'a-name', p)); ul.appendChild(li); }
        if (!ul.children.length) ul.appendChild(el('li', 'asset a-meta', 'Nothing'));
      }
      sec.appendChild(ul);
      const est = deal && deal.parts.every((p) => p.est);
      const atLabel = est ? 'Estimate at the trade' : three ? 'At the trade (estimate)' : 'At the trade';
      if (deal && SAVE) {
        const s = sideNow(deal, r.team, 'in');
        const lines = [];
        if (s.markup) lines.push(['', '5% trade markup on players', fmtNet(s.markup)]);
        lines.push(['sum', 'Value now', fmtInt(s.now)]);
        lines.push(['was', atLabel, fmtInt(r.value_in)]);
        sec.appendChild(totals(lines));
      } else {
        sec.appendChild(totals([['sum', atLabel, fmtInt(r.value_in)]]));
      }
      box.appendChild(sec);
    }
    const notes = $('deal-notes'); notes.replaceChildren();
    const add = (t) => notes.appendChild(el('p', '', t));
    if (partIds.length > 1) add('Entered in the game as ' + partIds.length + ' trades the same day, since a trade takes at most 5 assets per side; the tag on each asset shows its part.');
    if (three) add('Three-team trade: the game records one value for what each team sends, so each team’s value at the trade is split per asset by estimate.');
    if (deal && deal.parts.some((p) => p.est)) add('Posted in Discord after the latest save, so the save has no recorded value for it; values at the trade are estimated from the save (players plus 5%, picks as is).');
    if (SAVE && deal) add('Value now is each asset’s value in the save of ' + fmtLong(SAVE.date) + '. At the trade is the value the game recorded for the side when the deal was made. A negative value means the game counts the contract as a cost.');
    else add('Built without the league save, so the card lists the assets without per-asset values.');
  };

  const dlg = $('deal');
  let openId = null, opener = null, pushed = false;
  const showDeal = (tid, persp) => {
    renderDeal(tid, persp); openId = tid;
    if (!dlg.open) dlg.showModal();
    $('deal-title').focus({preventScroll: true});
    dlg.scrollTop = 0;
  };
  const openFrom = (tid, persp, row) => {
    opener = row;
    const h = '#trade-' + slugOf(tid);
    if (location.hash !== h) { history.pushState(null, '', h); pushed = true; }
    showDeal(tid, persp);
  };
  dlg.addEventListener('close', () => {
    openId = null;
    if (/^#trade-/i.test(location.hash)) { if (pushed) { pushed = false; history.back(); } else history.replaceState(null, '', '#' + picked); }
    if (opener && document.contains(opener)) opener.focus();
    opener = null;
  });
  dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
  $('deal-close').addEventListener('click', () => dlg.close());
  $('deal-copy').addEventListener('click', async () => {
    const b = $('deal-copy'), url = location.href.split('#')[0] + '#trade-' + slugOf(openId);
    try { await navigator.clipboard.writeText(url); b.textContent = 'Link copied'; } catch (e) { window.prompt('Copy this link', url); }
    setTimeout(() => { b.textContent = 'Copy link'; }, 1800);
  });
  for (const [id, persp] of [['trades-table', () => picked], ['all-table', () => null]]) {
    const t = $(id);
    t.addEventListener('click', (e) => { const tr = e.target.closest('tr[data-trade]'); if (tr) openFrom(tr.dataset.trade, persp(), tr); });
    t.addEventListener('keydown', (e) => { if (e.key !== 'Enter') return; const tr = e.target.closest('tr[data-trade]'); if (tr) openFrom(tr.dataset.trade, persp(), tr); });
  }
  const route = () => {
    const h = (location.hash || '').replace(/^#/, ''), m = /^trade-(.+)$/i.exec(h);
    const tid = m && bySlug[m[1].toUpperCase()];
    if (tid) { if (openId !== tid) showDeal(tid, null); return; }
    if (dlg.open) { pushed = false; dlg.close(); }
    const c = valid(h.toUpperCase()); if (c && c !== picked) { picked = c; render(); }
  };
  addEventListener('popstate', route);
  addEventListener('hashchange', route);

  // ---- Every asset, as CSV ----
  if (SAVE) {
    $('m-cards').hidden = false; $('m-save').textContent = fmtLong(SAVE.date);
    const acols = ['date', 'trade', 'part', 'from', 'to', 'asset', 'type', 'position', 'ovr', 'age', 'contract_now', 'now_with', 'value_now', 'plus_5pct_at_trade'];
    const out = [acols];
    for (const t of dealIds.slice().reverse()) {
      const deal = DEALS[t]; if (!deal) continue;
      for (const m of deal.moves) {
        const a = assetOf(m);
        if (a.kind === 'p') out.push([rowsOf[t][0].date, t, m.part, m.f, m.t, a.p.n, 'player', a.p.pos, a.p.ovr, a.p.age, a.p.con, a.p.x === 'ret' ? 'Retired' : a.p.x === 'fa' ? 'FA' : a.p.org, a.v, m.mk ? 'yes' : '']);
        else out.push([rowsOf[t][0].date, t, m.part, m.f, m.t, pickName(a.k) + (a.d ? ', used on ' + a.d.n : ''), a.d ? 'pick, used' : 'pick', a.d ? a.d.pos : '', a.d ? a.d.ovr : '', a.d ? a.d.age : '', '', a.d ? (a.d.x === 'fa' ? 'FA' : a.d.org) : a.k.own, a.v, '']);
      }
    }
    $('dl-assets').href = csvUrl(out); $('dl-assets-wrap').hidden = false;
  }

  // ---- Cutoffs ----
  const cb = $('cut-body');
  for (const c of cuts.slice().reverse()) { const tr = document.createElement('tr'); cell(tr, c.min < -1 ? 'no floor' : fmtEdge(c.min), 'num'); cell(tr, c.grade); cb.appendChild(tr); }

  const render = () => { renderCards(); renderChart(); renderTeam(); };
  render(); renderAll();
  let tmr; addEventListener('resize', () => { clearTimeout(tmr); tmr = setTimeout(renderChart, 120); });
  if (location.hash && valid(location.hash.slice(1).toUpperCase())) $('team').scrollIntoView();
  route();
})();
</script>
</body>
</html>
"""

html = TEMPLATE.replace("__DATA__", payload)

# GitHub Pages lets browsers cache a page for 10 minutes. So index.html is a tiny
# loader that never changes; it fetches report.html with a fresh query string on
# every visit, which skips both the browser and CDN caches. Commit report.html and
# the site shows it as soon as the Pages deploy finishes.
report = os.path.join(os.path.dirname(os.path.abspath(out)), "report.html")
with open(report, "w", encoding="utf-8") as f:
    f.write(html)
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
  fetch('report.html?v=' + Date.now(), {cache: 'no-store'})
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
    .then(function (html) { document.open(); document.write(html); document.close(); })
    .catch(function () { location.replace('report.html' + location.hash); });
</script>
</head>
<body><p>Loading the report cards…</p><noscript><p><a href="report.html">Open the report cards</a></p></noscript></body>
</html>
"""
with open(out, "w", encoding="utf-8") as f:
    f.write(LOADER)
print(f"wrote {out} (loader) and report.html: {len(ledger)} ledger rows, {len({r['trade'] for r in ledger})} trades, {len(teams)} teams, through {data['asOf']}")
