#!/usr/bin/env python3
"""Build the HLM27 GM report cards site straight from the official league saves.

Usage:
    python build_report_cards.py [--saves ../saves] [index.html]

Writes index.html (a small loader that never changes) and report.html (the page)
next to it; commit report.html after each update.

Reads every save in --saves (zips of the game's Save folder, named by game date).
The ledger, one row per team per trade, comes from the saves' trade histories: a
save's history resets at the season rollover, so the trades are the union across
all saves, plus the ones the daily trade recap mails still hold. Grades, ranks and
the chart are computed in the page itself. The latest save gives today's ratings,
contracts and values; the older saves give each player's overall on the trade day.
"""
import argparse
import datetime
import glob
import gzip
import json
import math
import os
import re
import zipfile
from collections import defaultdict

ap = argparse.ArgumentParser(description="Build the HLM27 GM report cards page.")
ap.add_argument("out", nargs="?", default="index.html", help="loader file to write; report.html goes next to it")
ap.add_argument("--saves", default=os.path.join("..", "saves"), help="folder of league save zips (default ../saves)")
args = ap.parse_args()
out = args.out

TEAM_NAMES = {"ANA": "Anaheim", "BOS": "Boston", "BUF": "Buffalo", "CAR": "Carolina", "CBJ": "Columbus", "CGY": "Calgary",
              "CHI": "Chicago", "COL": "Colorado", "DAL": "Dallas", "DET": "Detroit", "EDM": "Edmonton", "FLA": "Florida",
              "LAK": "Los Angeles", "MIN": "Minnesota", "MTL": "Montreal", "NJD": "New Jersey", "NSH": "Nashville",
              "NYI": "NY Islanders", "NYR": "NY Rangers", "OTT": "Ottawa", "PHI": "Philadelphia", "PIT": "Pittsburgh",
              "SEA": "Seattle", "SJS": "San Jose", "STL": "St. Louis", "TBL": "Tampa Bay", "TOR": "Toronto", "UTA": "Utah",
              "VAN": "Vancouver", "VGK": "Vegas", "WPG": "Winnipeg", "WSH": "Washington"}
# Grade cutoffs (minimum Edge) and sample-size limits, decided with Zachary.
CUTOFFS = [(-9.99, "F"), (-0.10, "D-"), (-0.085, "D"), (-0.065, "D+"), (-0.04, "C-"), (-0.02, "C"), (0, "C+"),
           (0.02, "B-"), (0.04, "B"), (0.07, "B+"), (0.10, "A-"), (0.15, "A"), (0.25, "A+")]
MIN_TRADES, FULL_TRADES = 3, 8
cutoffs = [{"min_edge": m, "grade": g} for m, g in CUTOFFS]
min_trades, full_trades = MIN_TRADES, FULL_TRADES

# The game caps a trade at 5 assets per side, so a bigger deal gets entered as
# several trades on the same day between the same two teams. Those are combined
# into one: any same-day group between the same teams where one part hits the cap.
# KEEP_SEPARATE lists groups to leave split anyway (by any one of their trade ids);
# EXTRA_MERGES lists other groups to combine, as tuples of trade ids.
ASSET_CAP = 5
# Pulock (MTL-NYI), Nylander (OTT-TOR), Kuznetsov (CGY-NJD, July 1 2027), Meyers (CAR-SEA, July 1 2027): separate deals
KEEP_SEPARATE = {"3837", "3972", "4049", "4042"}
# Calgary's Oct 6, 2027 deals, each entered as several trades with a 7th-round pick passed back and forth (confirmed by Zachary).
EXTRA_MERGES = [("4098", "4099"), ("4100", "4101", "4102", "4103")]
# A trade counts as Even when its balance, net value / total value moved, is
# within this band either way: close enough that both sides' AI GMs would take it.
EVEN_BAND = 0.10
# GM names: fill this in once and they show on the cards.
GM_NAMES = {}

# In the recorded values the game adds 5% to the players sent by every participant
# after the first (the league's trade difficulty, 1.05), so those players are flagged
# to carry the same 5% today.
#
# Overall at the trade: ratings only move on the 2nd of each month (Nov to Mar),
# reported in each team's progression mail with the new overall, plus the odd point
# from completed training and the season rollover. Those mails sit in every save, so
# the overall on any date is the nearest earlier save's overall plus the changes
# reported up to that date. On a tick day the tick lands before that day's trades.
TRADE_MARKUP_FROM_PARTICIPANT = 1
POSITIONS = {0: "LW", 1: "C", 2: "RW", 3: "LD", 4: "RD", 5: "G"}
JUNIOR, COLLEGE = {"2", "3", "4"}, {"5", "6", "7", "8", "9", "10"}
# Overall = offence/defence blend by player type (goalies: their one rating), halves to even.
OVR_WEIGHTS = {("F", 1): 70, ("F", 2): 70, ("F", 7): 60, ("F", 0): 30, ("F", 3): 35,
               ("D", 4): 50, ("D", 5): 65, ("D", 6): 25}
# Potential tiers (save's _Potential, 0 = best) and the badge colour, which the game
# sets from motivation (_Motivation; 5 = potential reached, shown grey).
POTENTIAL = {"F": ["Franchise", "Elite", "Top 6 F", "Top 9 F", "4th line", "Depth", "Minor", "Semipro", "Amateur"],
             "D": ["Franchise", "Elite", "Top 4 D", "Top 6 D", "7th D", "Depth", "Minor", "Semipro", "Amateur"],
             "G": ["Franchise", "Elite", "Starter", "Mid Starter", "Backup", "Depth", "Minor", "Semipro", "Amateur"]}
PLAYER_KEYS = ("$type", "FirstName", "LastName", "Positions", "_PlayerType", "BaseOffense", "BaseDefense", "Birthday",
               "TeamIds", "_ContractStatus", "Values", "_Potential", "_Motivation", "Drafted")
MAIL_TYPES = ("ProgressionMailArgs", "TrainingCompletedMailArgs", "DailyTradeRecapMailArgs")


def read_save(path):
    """The parts of a save the build needs, from its live state: dynamic/d0.hlm (gzip JSON), not the autosave under auto/."""
    with zipfile.ZipFile(path) as z:
        hits = [n for n in z.namelist() if n.endswith("dynamic/d0.hlm") and "/auto/" not in "/" + n]
        raw = z.read(min(hits, key=len))
    j = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
    sl = j["SportLeague"]
    lg = sl["Leagues"]["0"]
    players = {}
    for pid, p in sl["PlayerList"].items():
        q = {k: p[k] for k in PLAYER_KEYS if k in p}
        c = p.get("Contract")
        if c:
            q["Contract"] = {k: c[k] for k in ("LeagueId", "Salaries", "Length") if k in c}
        players[pid] = q
    return {
        "day": sl["LastSaveDay"][:10],
        "code": {int(k): t["ShortCity"] for k, t in lg["TeamList"].items()},
        "leagues": {str(k): v.get("Abbreviation") or "" for k, v in sl["Leagues"].items()},
        "picks": [{k: p.get(k) for k in ("Year", "Round", "Original", "Owner", "_Value", "CachedValueExpiration")} for p in lg["PickList"]],
        "players": players,
        # salary a team kept on a player it traded: (team id, player id, trade day, yearly amount)
        "dead": [(int(k), str(c.get("PlayerId")), (c.get("DaySigned") or "")[:10], (c.get("Salaries") or [0])[min(c.get("SeasonPassed") or 0, len(c.get("Salaries") or [0]) - 1)])
                 for k, t in lg["TeamList"].items() for c in t.get("DeadCapSpace") or [] if c.get("IsRetainedContract")],
        "mails": [m for m in sl.get("Mails") or [] if (m.get("Args") or {}).get("$type") in MAIL_TYPES],
        "trades": [t for t in j.get("TradeHistory") or [] if not t.get("GeneratedByAI")],
    }


def money(x):
    if x >= 1_000_000:
        s = f"{x / 1e6:.3f}".rstrip("0")
        return "$" + (s + "0" if s.endswith(".") else s) + "M"
    return f"${round(x / 1000)}K"


def pos_group(p):
    if p.get("$type") == "Goalie":
        return "G"
    return "D" if (p.get("Positions") or [0])[0] in (3, 4) else "F"


def overall(p):
    g = pos_group(p)
    if g == "G":
        return round(p.get("BaseDefense", 0))
    w = OVR_WEIGHTS.get((g, p.get("_PlayerType") or 0), 50)
    return round((w * p.get("BaseOffense", 0) + (100 - w) * p.get("BaseDefense", 0)) / 100)


def season_of(day):
    """League year, which turns over on July 1 (contracts, free agency)."""
    y = int(day[:4]) - (int(day[5:7]) < 7)
    return f"{y}-{(y + 1) % 100:02d}"


def _num(t):
    return int(t)


paths = sorted(glob.glob(os.path.join(args.saves, "*.zip")))
if not paths:
    raise SystemExit(f"no save zips in {args.saves}")
states = []
for p in paths:
    states.append(read_save(p))
    print(f"read {os.path.basename(p)}: {states[-1]['day']}, {len(states[-1]['trades'])} trades in its history", flush=True)
states.sort(key=lambda s: (s["day"], len(s["trades"])))
state = states[-1]
code = state["code"]
PL = state["players"]
save_day = datetime.date.fromisoformat(state["day"])
snaps = [(s["day"], s["players"]) for s in states]

# Every GM-to-GM trade: the histories of all saves, plus the trades only the recap mails still hold.
history = {}
for s in states:
    for m in s["mails"]:
        a = m.get("Args") or {}
        if a.get("$type") == "DailyTradeRecapMailArgs":
            for t in a.get("Trades") or []:
                if not t.get("GeneratedByAI") and all(p["TeamId"] in code for p in t["Participants"]):
                    history.setdefault(str(t["Id"]), t)
for s in states:
    for t in s["trades"]:
        if all(p["TeamId"] in code for p in t["Participants"]):
            history[str(t["Id"])] = t


# Salary retained by the sender is not in the trade history; it shows up as dead cap on the sending
# team, dated the trade day. Share kept = that amount / the player's full cap hit in the same save.
retained = {}
for s_ in states:
    full = defaultdict(int)
    for team_id, pid, day, amount in s_["dead"]:
        full[pid] += amount
    for team_id, pid, day, amount in s_["dead"]:
        sal = ((s_["players"].get(pid) or {}).get("Contract") or {}).get("Salaries") or [0]
        if (pid, day, team_id) not in retained and sal[0] + full[pid] > 0:
            retained[(pid, day, team_id)] = round(100 * amount / (sal[0] + full[pid]))


# A player sent twice by the same team on one day (a re-entered trade): the retention goes with the last one.
last_sent = {}
for tid_, t_ in history.items():
    for p_ in t_["Participants"]:
        for a_ in p_["PlayersId"]:
            k_ = (str(a_["Athlete"]), t_["Date"][:10], p_["TeamId"])
            last_sent[k_] = max(last_sent.get(k_, 0), int(tid_))


def kept_by(p, day, tid):
    """{player id: % of salary kept} for one trade participant: its own Contracts entries, plus dead cap from that day."""
    k = {str(c["Item1"]): round(c["Item2"] * 100) for c in p.get("Contracts") or []}
    for a in p["PlayersId"]:
        key = (str(a["Athlete"]), day, p["TeamId"])
        pct = retained.get(key) if last_sent.get(key) == int(tid) else None
        if pct:
            k.setdefault(str(a["Athlete"]), pct)
    return k


def age_on(p, day):
    b = datetime.date(1970, 1, 1) + datetime.timedelta(days=p["Birthday"])
    d = datetime.date.fromisoformat(day)
    return d.year - b.year - ((d.month, d.day) < (b.month, b.day))


def value_now(pid):
    """The game's cached trade value: the latest save that holds one (the cache empties on some days)."""
    for _, pl in reversed(snaps):
        v = ((pl.get(pid) or {}).get("Values") or {}).get("0")
        if v is not None:
            return v
    return None


# ---- Each asset's value at the trade ---------------------------------------------
# The trade history keeps only each side's total (ValueOutSum). A pick's cached value carries the
# day it was computed (CachedValueExpiration: day of the year, year), so a save holding the value
# from the trade day gives it exactly. A player's is his cached value in the trade-day save (one
# that already holds the trade first), else the nearest save. The opening save has no pick values
# and stale player values, so saves without pick values are skipped. Each side is then made to add
# up to its recorded total: the gap goes to its players, in proportion to their size, since the
# game's adjustments (the 5% and a 10% boost on some players, apparently the receiving team's
# needs) only move players.
value_states = [s for s in states if any(p.get("_Value") is not None for p in s["picks"])]
value_days = [datetime.date.fromisoformat(s["day"]) for s in value_states]
holds_trade = [{str(t["Id"]) for t in s["trades"]} for s in value_states]
pick_maps = [{(p["Year"], p["Round"], p["Original"]): p for p in s["picks"]} for s in value_states]


def base_value(kind, key, tid, day):
    """One asset's own value on the trade day, before the trade's adjustments."""
    d = datetime.date.fromisoformat(day)
    if kind == "k":
        stamp = (d.timetuple().tm_yday, d.year)
        for pm in pick_maps:
            x = pm.get(key) or {}
            c = x.get("CachedValueExpiration") or {}
            if x.get("_Value") is not None and (c.get("Item1"), c.get("Item2")) == stamp:
                return x["_Value"]
    same = [i for i, s in enumerate(value_states) if s["day"] == day]
    order = [i for i in same if tid in holds_trade[i]] + [i for i in reversed(same) if tid not in holds_trade[i]]
    order += sorted((i for i in range(len(value_states)) if value_states[i]["day"] != day),
                    key=lambda i: (abs((value_days[i] - d).days), value_days[i] > d))
    for i in order:
        if kind == "p":
            v = ((value_states[i]["players"].get(key) or {}).get("Values") or {}).get("0")
        else:
            v = (pick_maps[i].get(key) or {}).get("_Value")
        if v is not None:
            return v
    return None


def round_to(total, vals):
    """Round to integers that still add up to total (largest remainder)."""
    out = [math.floor(v) for v in vals]
    for j in sorted(range(len(vals)), key=lambda j: out[j] - vals[j])[:round(total) - sum(out)]:
        out[j] += 1
    return out


_splits = {}


def split_at_trade(tid, t):
    """{(participant index, "p" or "k", id): value at the trade}, each side adding up to its recorded
    total, and the participants whose split is estimated (several assets that don't add up as is)."""
    if tid not in _splits:
        _splits[tid] = _split_at_trade(tid, t)
    return _splits[tid]


def _split_at_trade(tid, t):
    day = t["Date"][:10]
    out, loose = {}, []
    for i, p in enumerate(t["Participants"]):
        mk = 1.05 if i >= TRADE_MARKUP_FROM_PARTICIPANT else 1
        w = {}
        for a in p["PlayersId"]:
            v = base_value("p", str(a["Athlete"]), tid, day)
            w[("p", str(a["Athlete"]))] = None if v is None else v * mk
        for k in p["PicksId"]:
            w[("k", str(k["Id"]))] = base_value("k", (int(k["Year"]), int(k["Round"]), int(k["OriginalTeam"])), tid, day)
        if not w:
            continue
        total = p.get("ValueOutSum") or 0
        gap = total - sum(v for v in w.values() if v is not None)
        if len(w) > 1 and (None in w.values() or abs(gap) > max(1.5, 0.004 * abs(total))):
            loose.append(i)
        w = {k: v or 0 for k, v in w.items()}
        movers = [k for k in w if k[0] == "p" and w[k]] or [k for k in w if w[k]] or list(w)
        size = sum(abs(w[k]) for k in movers)
        for k in movers:
            w[k] += gap * (abs(w[k]) / size if size else 1 / len(movers))
        for k, v in zip(w, round_to(total, list(w.values()))):
            out[(i,) + k] = v
    return out, loose


def trade_rows(tid, t):
    """One ledger row per team: what it got and sent, with the game's recorded value of each side."""
    ps = t["Participants"]
    sides = [code[p["TeamId"]] for p in ps]
    at_trade = split_at_trade(tid, t)[0]
    got = [[] for _ in ps]  # (text, kind, sender index, value at the trade)
    third = defaultdict(list)
    for i, p in enumerate(ps):
        sent = {str(a["Athlete"]) for a in p["PlayersId"]}
        kept = kept_by(p, t["Date"][:10], tid)
        for pid, pct in kept.items():
            if pid not in sent:
                third[i].append(pct)
        for nm, a in zip(p["PlayersName"], p["PlayersId"]):
            pid = str(a["Athlete"])
            q = PL.get(pid)
            text = nm + (f" ({overall(q)}, {age_on(q, state['day'])})" if q else "")
            if pid in kept:
                text += f" [sender keeps {kept[pid]}% of salary]"
            got[a.get("TeamIndex", 0)].append((text, "p", i, at_trade.get((i, "p", pid), 0)))
        for k in p["PicksId"]:
            orig = int(k["OriginalTeam"])
            text = f"{k['Year']} R{k['Round']} ({code.get(orig, orig)})"
            got[k.get("TeamId", 0)].append((text, "k", i, at_trade.get((i, "k", str(k["Id"])), 0)))
    rows = []
    for i, team in enumerate(sides):
        ins = got[i]
        outs = [x for j, g in enumerate(got) if j != i for x in g if x[2] == i]
        if len(ps) == 2:
            vin, vout, note = ps[1 - i].get("ValueOutSum") or 0, ps[i].get("ValueOutSum") or 0, ""
            partner = sides[1 - i]
        else:  # each sender's recorded value, split across what it sent by each asset's value at the trade
            note = "3-team trade: values split per asset"
            vin, vout = sum(x[3] for x in ins), ps[i].get("ValueOutSum") or 0
            if third[i]:
                note += "; " + "; ".join(f"retains {pct}% of a salary" for pct in third[i])
            senders = list(dict.fromkeys(sides[x[2]] for x in ins))
            partner = ", ".join(senders + [s for s in sides if s != team and s not in senders])
        rows.append({
            "date": t["Date"][:10], "season": season_of(t["Date"][:10]), "trade": tid, "team": team, "partner": partner,
            "entries": "; ".join(x[0] for x in ins) or "—", "exits": "; ".join(x[0] for x in outs) or "—",
            "players_in": sum(x[1] == "p" for x in ins), "players_out": sum(x[1] == "p" for x in outs),
            "picks_in": sum(x[1] == "k" for x in ins), "picks_out": sum(x[1] == "k" for x in outs),
            "value_in": vin, "value_out": vout, "net": vin - vout, "result": "", "note": note,
        })
    return rows


ledger = [r for tid in sorted(history, key=_num) for r in trade_rows(tid, history[tid])]
teams = [{"team": c, "name": TEAM_NAMES.get(c, c), "gm": GM_NAMES.get(c, "")} for c in sorted(code.values())]

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
merge_sets += [list(m) for m in EXTRA_MERGES if all(t in by_trade for t in m)]

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
            "date": parts[0]["date"], "season": parts[0]["season"], "trade": new_id, "team": team, "partner": parts[0]["partner"],
            "entries": join("entries"), "exits": join("exits"),
            **{k: sum(p[k] for p in parts) for k in ("players_in", "players_out", "picks_in", "picks_out", "value_in", "value_out")},
            "note": "; ".join([f"Combined from {len(tids)} trades entered the same day (the game allows {ASSET_CAP} assets per side)"] + notes),
        }
        row["net"] = row["value_in"] - row["value_out"]
        combined.append(row)
ledger = [d for d in ledger if d["trade"] not in merged_ids] + combined
ledger.sort(key=lambda d: (d["date"], _num(d["trade"].split("+")[0]), d["team"]))
print("combined", len(merge_sets), "split deals:", ", ".join("+".join(sorted(m, key=_num)) for m in merge_sets))

for d in ledger:
    vin, vout = d["value_in"], d["value_out"]
    moved = abs(vin) + abs(vout)
    bal = (vin - vout) / moved if moved else 0.0
    d["result"] = "Even" if abs(bal) < EVEN_BAND else ("Win" if vin > vout else "Loss")


# ---- Trade cards: every asset, from the league saves ----------------------------
def build_cards(deal_ids):
    team_leagues = state["leagues"]
    pick_list = {f"{p['Year']}{p['Round']:02d}{p['Original']:02d}": p for p in state["picks"]}
    season0 = save_day.year if save_day.month >= 7 else save_day.year - 1
    per_round = len(code)
    drafted = {}
    for pid, p in PL.items():
        for d in p.get("Drafted") or []:
            if "League" not in d and str(d.get("PickId", "-1")) not in ("-1", ""):
                drafted[str(d["PickId"])] = (pid, (d["Round"] - 1) * per_round + d["Pick"])

    # Rating history: one snapshot per save, plus the dated changes from every save's mails.
    ticks, trained, seen_mail = defaultdict(list), defaultdict(list), set()
    for s in states:
        for m in s["mails"]:
            if m.get("Id") in seen_mail:
                continue
            seen_mail.add(m.get("Id"))
            a, day = m.get("Args") or {}, (m.get("Date") or "")[:10]
            if a.get("$type") == "ProgressionMailArgs":
                for x in a.get("Players") or []:
                    ticks[str(x["Item1"])].append((day, x.get("Item3") or 0))
            elif a.get("$type") == "TrainingCompletedMailArgs":
                trained[str(a.get("Player"))].append(day)

    def ovr_on(pid, day):
        have = [(d, pl[pid]) for d, pl in snaps if pid in pl]
        if not have:
            return None
        moved = lambda a, b: sum(x for d, x in ticks.get(pid, []) if a < d <= b)
        before = [h for h in have if h[0] <= day]
        if not before:  # trade before the first save: walk back from it
            d0, p0 = have[0]
            return overall(p0) - moved(day, d0)
        d0, p0 = before[-1]
        v = overall(p0) + moved(d0, day)
        later = [h for h in have if h[0] > d0]
        if later:  # a point the mails don't explain (training): date it by the first training mail
            d1, p1 = later[0]
            rest = overall(p1) - overall(p0) - moved(d0, d1)
            when = min([t for t in trained.get(pid, []) if d0 < t <= d1] or [d1])
            if rest and when <= day:
                v += rest
        return v

    def contract(p):
        con = p.get("Contract") or {}
        lid = con.get("LeagueId")
        if lid is not None and str(lid) != "0":
            ab = team_leagues.get(str(lid), "")
            return f"College ({ab})" if str(lid) in COLLEGE else f"Junior ({ab})" if str(lid) in JUNIOR else f"{ab} contract"
        sal = con.get("Salaries") or []
        if p.get("_ContractStatus") == 2:
            return "RFA, unsigned"
        if sal and sal[0] > 0 and con.get("Length"):
            last = season0 + con["Length"] - 1
            return f"{money(sal[0])} through {last}-{(last + 1) % 100:02d}"
        return "Unsigned draft pick" if p.get("_ContractStatus") == 3 else "Unsigned"

    people, picks = {}, {}

    def person(pid, short=None):
        e = people.get(pid)
        if e is None:
            p = PL.get(pid)
            old = next((pl[pid] for _, pl in reversed(snaps) if pid in pl), None)
            src = p or old
            if src is None:
                e = {"n": short or "Unknown player", "x": "ret"}
            else:
                g = pos_group(src)
                e = {"n": f"{src.get('FirstName', '')} {src.get('LastName', '')}".strip(),
                     "pos": "/".join(POSITIONS.get(x, "?") for x in src.get("Positions") or []),
                     "pot": POTENTIAL[g][min(src.get("_Potential") or 0, 8)],
                     "mot": min(src.get("_Motivation") or 0, 5)}
                if p is None:  # in an older save, gone from the latest: retired
                    e["x"] = "ret"
                else:
                    org_id = (p.get("TeamIds") or {}).get("0")
                    e.update({"age": age_on(p, state["day"]), "ovr": overall(p), "v": value_now(pid)})
                    if org_id in code:
                        e["org"], e["con"] = code[org_id], contract(p)
                    else:
                        e["x"], e["con"] = "fa", "Free agent"
            people[pid] = e
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

    def then(m, pid, day):
        """Overall and age on the trade day."""
        src = PL.get(pid) or next((pl[pid] for _, pl in reversed(snaps) if pid in pl), None)
        if src is not None:
            m["ot"], m["at"] = ovr_on(pid, day), age_on(src, day)

    def from_history(tid):
        t = history[tid]
        day = t["Date"][:10]
        ps = t["Participants"]
        sides = [code.get(p["TeamId"], str(p["TeamId"])) for p in ps]
        at_trade, loose = split_at_trade(tid, t)
        split_loose.extend((tid, sides[i]) for i in loose)
        moves, holds = [], []
        for i, p in enumerate(ps):
            kept = kept_by(p, day, tid)
            for nm, a in zip(p["PlayersName"], p["PlayersId"]):
                pid, to = str(a["Athlete"]), sides[a.get("TeamIndex", 0)]
                person(pid, nm)
                m = {"a": "p:" + pid, "f": sides[i], "t": to, "part": tid, "s": nm, "vt": at_trade.get((i, "p", pid))}
                if i >= TRADE_MARKUP_FROM_PARTICIPANT:
                    m["mk"] = 1
                if i in loose:
                    m["ve"] = 1
                if pid in kept:
                    m["ret"] = kept[pid]
                then(m, pid, day)
                moves.append(m)
            for k in p["PicksId"]:
                m = {"a": pick(str(k["Id"]), int(k["Year"]), int(k["Round"]), code.get(int(k["OriginalTeam"]), k["OriginalTeam"])),
                     "f": sides[i], "t": sides[k.get("TeamId", 0)], "part": tid, "vt": at_trade.get((i, "k", str(k["Id"])))}
                if i in loose:
                    m["ve"] = 1
                moves.append(m)
            for c in p.get("Contracts") or []:
                person(str(c["Item1"]))
                holds.append({"team": sides[i], "p": str(c["Item1"]), "pct": round(c["Item2"] * 100), "part": tid})
        return moves, holds

    deals = {}
    for tid in deal_ids:
        moves, holds, parts = [], [], []
        for p in tid.split("+"):
            mv, hd = from_history(p)
            moves += mv
            holds += hd
            parts.append({"id": p})
        deals[tid] = {"parts": parts, "moves": moves}
        if holds:
            deals[tid]["holds"] = holds
    return people, picks, deals


deal_ids = sorted({d["trade"] for d in ledger}, key=lambda t: _num(t.split("+")[0]))
split_loose = []
people, pick_info, deals = build_cards(deal_ids)
save_info = {"date": state["day"]}
print(f"trade cards: {len(deals)} deals, {sum(len(d['moves']) for d in deals.values())} assets, "
      f"today's numbers from the {state['day']} save, rating history from {len(states)} saves")
n_sides = sum(1 for d in deals.values() for p in d["parts"] for q in history[p["id"]]["Participants"] if q["PlayersId"] or q["PicksId"])
print(f"values at the trade: {len(split_loose)} of {n_sides} sides sent several assets whose trade-day values don't add up "
      f"to the recorded total, so the split is estimated (trade, sender): " + ", ".join(f"{t} {s}" for t, s in split_loose))
for d in ledger:
    if d["note"].startswith("3-team"):
        print(f"3-team {d['trade']} {d['team']}: value in {d['value_in']}, out {d['value_out']}")

data = {
    "ledger": ledger, "cutoffs": cutoffs, "teams": teams,
    "minTrades": min_trades, "fullTrades": full_trades, "evenBand": EVEN_BAND,
    "asOf": state["day"],
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
    --scrim: rgba(17, 32, 58, .55); --bar: #7f8ea3; --gone: .3;
    --sans: "Helvetica Neue", Helvetica, Arial, "Segoe UI", Roboto, sans-serif;
    padding-top: env(safe-area-inset-top, 0px); padding-bottom: env(safe-area-inset-bottom, 0px);
  }
  @media (prefers-color-scheme: dark) { :root {
    --ice: #0e1726; --paper: #15213a; --ink: #edf2f8; --ink-soft: #9fb0c6; --line: #2a3850; --line-strong: #46587a;
    --blue: #6aa6ee; --blue-soft: #1c3458; --red: #f0636b; --red-soft: #4b1f24; --stamp: #f0636b; --hover: #1d2d4a;
    --scrim: rgba(3, 8, 16, .66); --bar: #5d7090; --gone: .42;
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
  .season { margin-top: 12px; font-size: 14px; }
  .season select { font: inherit; color: var(--ink); background: var(--paper); border: 1px solid var(--line-strong); border-radius: 4px; padding: 6px 10px; margin-left: 6px; }
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
  .side { margin: 0; padding: 12px 22px 18px; border-right: 1px solid var(--line); min-width: 0; display: flex; flex-direction: column; }
  .side:last-child { border-right: 0; }
  .side-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; padding-bottom: 7px; border-bottom: 1px solid var(--line-strong); }
  .side h3 { font-size: 15px; font-weight: 700; margin: 0; }
  .side.me h3 { color: var(--blue); }
  .col-l { color: var(--ink-soft); font-size: 12px; white-space: nowrap; }
  .pot { display: inline-block; padding: 0 6px; border-radius: 3px; font-size: 12px; font-weight: 700; line-height: 18px; vertical-align: 1px; white-space: nowrap; color: #fff; }
  .pot.m0 { background: #2f6fd6; } .pot.m1 { background: #2b8a3e; } .pot.m2 { background: #e8890c; color: #2b1700; }
  .pot.m3 { background: #d03b3b; } .pot.m4 { background: #7f1d1d; } .pot.m5 { background: #6f7a89; }
  .a-ovr { font-size: 14px; font-variant-numeric: tabular-nums; margin-top: 1px; }
  .d { font-size: 12px; font-weight: 700; margin-left: 2px; }
  .d.up { color: var(--blue); } .d.down { color: var(--red); } .d.flat { color: var(--ink-soft); font-weight: 400; }
  .legend { line-height: 2; }
  .legend .pot { margin: 0 1px; }
  .assets { list-style: none; margin: 0; padding: 0; }
  .asset { padding: 9px 0 8px; border-bottom: 1px solid var(--line); }
  .a-top { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
  .a-name { font-weight: 600; overflow-wrap: anywhere; }
  .a-val { font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .a-val .was { color: var(--ink-soft); font-weight: 400; }
  .a-val.none, .a-val .none { color: var(--ink-soft); font-weight: 400; }
  /* Value at the trade -> today: a bar per asset, on one scale for the whole card. */
  .a-bar { display: flex; align-items: center; gap: 10px; margin: 5px 0 4px; }
  .vbar { position: relative; flex: 1; min-width: 4rem; height: 8px; }
  .vbar.big { height: 12px; }
  .vbar i { position: absolute; top: 0; bottom: 0; }
  .vbar .kept { background: var(--bar); }
  .vbar .up { background: var(--blue); } .vbar .down { background: var(--red); }
  .vbar .gone { opacity: var(--gone); }
  .vbar .rr { border-radius: 0 4px 4px 0; } .vbar .rl { border-radius: 4px 0 0 4px; }
  .vbar .zero { top: -3px; bottom: -3px; width: 1px; margin-left: -0.5px; background: var(--ink-soft); }
  .a-chg { flex: none; min-width: 4.6em; text-align: right; font-size: 13px; font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .a-chg.up { color: var(--blue); } .a-chg.down { color: var(--red); } .a-chg.flat { color: var(--ink-soft); font-weight: 400; }
  .total { margin: 0; margin-top: auto; padding-top: 12px; }
  .total .a-name, .total .a-val { font-weight: 700; }
  @media (forced-colors: active) { .vbar .kept { background: GrayText; } .vbar .up, .vbar .down { background: CanvasText; } }
  .a-meta { color: var(--ink-soft); font-size: 13px; }
  .a-flag { color: var(--ink); font-size: 13px; }
  .a-part { display: inline-block; margin-left: 6px; padding: 0 5px; border: 1px solid var(--line-strong); border-radius: 3px; color: var(--ink-soft); font-size: 12px; font-weight: 400; vertical-align: 1px; }
  .asset.hold .a-name { font-weight: 400; }
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
    <p class="lede">Every GM graded on the trade value they took in versus sent out, across <b id="n-trades"></b> GM-to-GM trades<span id="range"> from <b id="d-first"></b> to <b id="d-last"></b></span>. Click a team to see every entry and exit, and any trade to see what each asset is worth.</p>
    <p class="meta">Through the league save of <span id="as-of"></span>. Updated <span id="built"></span>. <a id="dl" href="#" download="hlm27_trade_ledger.csv">Download the full ledger (CSV)</a><span id="dl-assets-wrap" hidden> or <a id="dl-assets" href="#" download="hlm27_trade_assets.csv">every asset traded (CSV)</a></span>.</p>
    <p class="season"><label for="season">Season</label> <select id="season"></select></p>
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
    <p><b>Source.</b> The official league saves' trade histories: every GM-to-GM trade since the league opened in September 2026. AI trades in the game's other leagues are left out. A season runs from July 1 to June 30, the league year; pick one at the top of the page to grade it alone.</p>
    <p><b>Value.</b> The game's own trade valuation of each side at the time of the deal, as the save records it. Value in is what a team received; value out is what it sent. A trade is a Win or a Loss for a team only when the gap is more than <b id="m-band"></b> of the value moved; inside that band it is Even, a deal both sides' AI GMs would accept. Even trades count as neither a win nor a loss, but their value still counts toward Edge.</p>
    <p><b>Edge.</b> (value in − value out) ÷ (value in + value out): value won as a share of value moved, so a busy GM and a quiet one compare fairly. The grade comes from Edge using the cutoffs below. A team needs at least <b id="m-min"></b> trades for a grade (fewer shows INC) and <b id="m-full"></b> for a full grade; in between, the grade carries an asterisk.</p>
    <p><b>Combined trades.</b> The game allows at most 5 assets per side in one trade, so bigger deals get entered as several trades on the same day between the same two teams. Those are combined into one deal here and graded as a whole; their trade number joins the parts, like 3844+3845+3846.</p>
    <p id="m-cards" hidden><b>Trade cards.</b> Click any trade to see every asset: each player's overall and potential at the trade and today, and each asset's value at the trade and today. At the trade, each side's recorded value is split across its assets by their values in the save of the trade day; where those don't add up to it, the gap is spread over the side's players. Today is the save of <span id="m-save"></span> (or the last save that holds a value). A player who has since left as a free agent or retired counts as 0, and a used pick counts as the player drafted with it.</p>
    <p><b>What it measures.</b> Asset value, not whether a trade helped a team win. Cap dumps, rentals and win-now veterans for young talent count as value lost. Where a team took picks to retain salary, that shows as value won, since the game does not price the cap cost. In a three-team trade, what each team sent is split between the other two by each asset's value on the trade day. Players are shown with their overall and age as of the latest save, not at trade time.</p>
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

  // ---- Cards, computed from the ledger ----
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
  const cuts = D.cutoffs.map((c) => ({min: +c.min_edge, grade: c.grade})).sort((a, b) => a.min - b.min);
  // The season picked at the top filters the ledger; everything below is recomputed from it.
  const SEASONS = [...new Set(D.ledger.map((r) => r.season))].sort().reverse();
  const seasonName = (s) => s.slice(0, 4) + '–' + s.slice(5);
  let season = '', LED, by, cards, graded;
  const compute = () => {
    LED = season ? D.ledger.filter((r) => r.season === season) : D.ledger;
    by = {};
    const blank = (code, name, gm) => ({team: code, name, gm, trades: 0, wins: 0, losses: 0, evens: 0, players_in: 0, players_out: 0, picks_in: 0, picks_out: 0, value_in: 0, value_out: 0, best: null, worst: null, top_in: null, top_out: null});
    for (const t of D.teams) by[t.team] = blank(t.team, t.name, t.gm || '');
    for (const r of LED) {
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
    cards = Object.values(by).map((t) => {
      const moved = t.value_in + t.value_out, edge = moved > 0 ? (t.value_in - t.value_out) / moved : null;
      let grade = '-';
      if (t.trades > 0 && t.trades < MIN) grade = 'INC';
      else if (t.trades >= MIN) { let g = cuts[0].grade; for (const c of cuts) if (edge >= c.min) g = c.grade; grade = g + (t.trades < FULL ? '*' : ''); }
      return {...t, grade, edge, rank: null, net: t.value_in - t.value_out, win_pct: t.trades ? t.wins / t.trades : null,
        biggest_win: t.best ? t.best.tag : '', biggest_loss: t.worst ? t.worst.tag : '', top_in: t.top_in ? t.top_in.text : '', top_out: t.top_out ? t.top_out.text : ''};
    });
    graded = cards.filter((r) => r.trades >= MIN);
    for (const r of graded) r.rank = graded.filter((o) => o.edge > r.edge).length + 1;
    cards.sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99) || b.trades - a.trades || a.team.localeCompare(b.team));
    const ids = new Set(LED.map((r) => r.trade)), dates = LED.map((r) => r.date).sort();
    $('n-trades').textContent = fmtInt(ids.size); $('range').hidden = !dates.length;
    if (dates.length) { $('d-first').textContent = fmtDate(dates[0]); $('d-last').textContent = fmtDate(dates[dates.length - 1]); }
  };
  compute();
  const cardOf = (code) => cards.find((c) => c.team === code);

  // ---- Header ----
  $('as-of').textContent = fmtDate(D.asOf); $('built').textContent = fmtDate(D.built);
  $('m-min').textContent = MIN; $('m-band').textContent = Math.round(D.evenBand * 100) + '%'; $('m-full').textContent = FULL;
  const csvCell = (v) => { const s = String(v ?? ''); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const csvUrl = (rows) => URL.createObjectURL(new Blob(['\ufeff' + rows.map((r) => r.map(csvCell).join(',')).join('\r\n')], {type: 'text/csv'}));
  const cols = ['date', 'season', 'trade', 'team', 'partner', 'entries', 'exits', 'players_in', 'players_out', 'picks_in', 'picks_out', 'value_in', 'value_out', 'net', 'result', 'note'];
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
  const tradeKey = (t) => +t.split('+')[0];
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
    const rows = LED.filter((x) => x.team === picked).sort((a, b) => b.date.localeCompare(a.date) || tradeKey(b.trade) - tradeKey(a.trade));
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
    let shown = 0, total = 0;
    for (const t of dealIds) {
      if (season && rowsOf[t][0].season !== season) continue;
      total++;
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
    $('q-count').textContent = words.length ? shown + ' of ' + total + ' trades' : total + ' trades';
  };
  $('q').addEventListener('input', renderAll);

  // ---- Trade card ----
  const ORD = ['', '1st', '2nd', '3rd', '4th', '5th', '6th', '7th'];
  const WORD = {Win: 'a win', Loss: 'a loss', Even: 'even'};
  const listJoin = (a) => a.length < 3 ? a.join(' and ') : a.slice(0, -1).join(', ') + ' and ' + a[a.length - 1];
  const pickName = (k) => k.y + ' ' + (ORD[k.r] || 'R' + k.r) + ' round (' + k.o + ')';
  // A player who has left as a free agent or retired is worth nothing today.
  const worth = (p) => p.x ? 0 : p.v ?? null;
  const assetOf = (m) => {
    const id = m.a.slice(2);
    if (m.a[0] === 'p') { const p = P[id] || {n: id}; return {kind: 'p', p, v: worth(p)}; }
    const k = K[id] || {}, d = k.dr ? P[k.dr] || {} : null;
    return {kind: 'k', k, d, v: d ? worth(d) : k.v ?? null};
  };
  // The game adds 5% to the players one side sends (trade difficulty 1.05); a shown value carries it the same way.
  const shown = (m, v) => v == null ? null : m.mk ? Math.round(v * 1.05) : v;
  const nowOf = (m) => shown(m, assetOf(m).v);
  const sideNow = (deal, team, dir) => {
    let now = 0;
    for (const m of deal.moves) if ((dir === 'in' ? m.t : m.f) === team) now += nowOf(m) || 0;
    return {now};
  };
  const callOf = (vin, vout) => {
    const mv = Math.abs(vin) + Math.abs(vout), bal = mv ? (vin - vout) / mv : 0;
    return {net: vin - vout, bal, res: Math.abs(bal) < D.evenBand ? 'Even' : vin > vout ? 'Win' : 'Loss'};
  };
  const share = (bal) => (Math.abs(bal) * 100).toFixed(1) + '% of the value moved';
  const MOT = ['Absolute', 'High', 'Medium', 'Low', 'Poor', 'Reached'];

  const thenLine = (rows, lead) => {
    const band = '±' + Math.round(D.evenBand * 100) + '%';
    if (rows.length === 2) {
      const c = callOf(lead.value_in, lead.value_out);
      if (lead.result === 'Even') return 'At the trade: even. ' + nameOf(lead.team) + ' came out ' + (lead.net >= 0 ? 'ahead' : 'behind') + ' by ' + fmtInt(Math.abs(lead.net)) + ', ' + share(c.bal) + ', inside the ' + band + ' band.';
      return 'At the trade: ' + nameOf(lead.team) + ' ' + (lead.result === 'Win' ? 'won' : 'lost') + ' by ' + fmtInt(Math.abs(lead.net)) + ', ' + share(c.bal) + '.';
    }
    const s = rows.slice().sort((a, b) => b.net - a.net);
    return 'At the trade (three teams): ' + s.map((r) => nameOf(r.team) + ' ' + fmtNet(r.net) + ', ' + WORD[r.result]).join('; ') + '.';
  };
  const nowLine = (deal, rows, lead) => {
    const now = (r) => callOf(sideNow(deal, r.team, 'in').now, sideNow(deal, r.team, 'out').now);
    if (rows.length === 2) {
      const c = now(lead);
      return 'Today: ' + nameOf(lead.team) + ' ' + fmtNet(c.net) + ', ' + share(c.bal) + ', ' + (c.res === lead.result ? 'still ' : 'now ') + WORD[c.res] + '.';
    }
    return 'Today: ' + rows.map((r) => ({r, c: now(r)})).sort((a, b) => b.c.net - a.c.net).map(({r, c}) => nameOf(r.team) + ' ' + fmtNet(c.net)).join(', ') + '.';
  };

  // Potential badge, coloured the way the game colours it: by motivation, grey once reached.
  const badge = (p) => {
    if (!p || !p.pot) return null;
    const b = el('span', 'pot m' + (p.mot ?? 0), p.pot);
    b.title = 'Potential ' + p.pot + ', motivation ' + MOT[p.mot ?? 0];
    return b;
  };
  const delta = (a, b) => {
    const d = b - a;
    return el('span', 'd ' + (d > 0 ? 'up' : d < 0 ? 'down' : 'flat'), d > 0 ? '+' + d : d < 0 ? '−' + Math.abs(d) : 'no change');
  };
  // Value at the trade and today, drawn as one bar on a scale shared by the whole card. Grey is value
  // kept, solid blue value gained, faded red value lost. Below zero (a contract worth less than nothing)
  // faded blue is negative value shed and solid red negative value taken on.
  const scaleOf = (vals) => {
    let lo = 0, hi = 0;
    for (const v of vals) if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    return {lo, hi: hi > lo ? hi : lo + 1};
  };
  const valueBar = (then, now, sc, big) => {
    const b = el('span', 'vbar' + (big ? ' big' : ''));
    b.setAttribute('aria-hidden', 'true');
    const at = (v) => (v - sc.lo) / (sc.hi - sc.lo) * 100;
    const top = Math.max(0, then ?? 0, now ?? 0), bottom = Math.min(0, then ?? 0, now ?? 0);
    const span = (a, c, cls, inner) => {  // inner: the end that touches the grey part, kept 2px apart
      const lo = Math.min(a, c), hi = Math.max(a, c), w = at(hi) - at(lo);
      if (w < 0.1) return;
      const gap = inner != null && w > 3 ? 2 : 0, s = el('i', cls);
      s.style.left = 'calc(' + at(lo) + '% + ' + (inner === lo ? gap : 0) + 'px)';
      s.style.width = 'calc(' + w + '% - ' + gap + 'px)';
      if (hi === top && top > 0) s.classList.add('rr');
      if (lo === bottom && bottom < 0) s.classList.add('rl');
      b.appendChild(s);
    };
    if (sc.lo < 0) { const z = el('i', 'zero'); z.style.left = at(0) + '%'; b.appendChild(z); }
    if (then == null || now == null) { span(0, then ?? now ?? 0, 'kept' + (now == null ? ' gone' : '')); return b; }
    const dir = now > then ? 'up' : 'down';
    if (then * now < 0) { span(then, 0, dir + ' gone'); span(0, now, dir); return b; }
    const kept = Math.abs(then) < Math.abs(now) ? then : now, far = kept === then ? now : then;
    span(0, kept, 'kept');
    if (far !== kept) span(kept, far, dir + (far === now ? '' : ' gone'), kept || null);
    return b;
  };
  const fromTo = (then, now, est) => {
    const v = el('span', 'a-val'), was = el('span', 'was', (then == null ? '—' : fmtInt(then)) + ' → ');
    if (est) was.title = 'Estimated: this side’s assets did not add up to its recorded value, so the gap is spread over its players';
    v.append(was, el('span', now == null ? 'none' : '', now == null ? '—' : fmtInt(now)));
    return v;
  };
  const change = (then, now) => {
    const d = then == null || now == null ? null : now - then;
    return el('span', 'a-chg ' + (d > 0 ? 'up' : d < 0 ? 'down' : 'flat'), d == null ? '' : d ? fmtNet(d) : '±0');
  };
  const valueRow = (then, now, sc, big) => { const row = el('div', 'a-bar'); row.append(valueBar(then, now, sc, big), change(then, now)); return row; };
  const assetItem = (m, multi, three, sc) => {
    const a = assetOf(m), li = el('li', 'asset');
    const topLine = el('div', 'a-top'), nm = el('span', 'a-name');
    const lines = [], flags = [];
    if (a.kind === 'p') {
      const p = a.p;
      nm.append(p.n || '');
      const b = badge(p); if (b) nm.append(' ', b);
      // Overall at the trade and now: the improved-or-not signal.
      const ovr = el('div', 'a-ovr');
      if (p.x === 'ret') ovr.append('OVR ' + (m.ot ?? '—') + ' at the trade, retired since');
      else if (m.ot != null && p.ovr != null) { ovr.append('OVR ' + m.ot + ' → ' + p.ovr + ' '); ovr.appendChild(delta(m.ot, p.ovr)); }
      else if (p.ovr != null) ovr.append('OVR ' + p.ovr);
      if (ovr.childNodes.length) lines.push(ovr);
      const age = m.at != null ? 'age ' + m.at + ' at the trade' : p.age ? 'age ' + p.age : '';
      lines.push(el('div', 'a-meta', [p.pos, age].filter(Boolean).join(', ') + (p.con && !p.x ? '. ' + p.con : '')));
      if (p.x === 'fa') flags.push('Free agent now, so no value');
      else if (p.org && p.org !== m.t) flags.push('Now with ' + p.org);
      if (m.ret) flags.push(m.f + ' kept ' + m.ret + '% of his salary');
    } else {
      nm.append(pickName(a.k));
      if (a.d) {
        const used = el('div', 'a-meta');
        used.append('Used: #' + a.k.no + ' overall, ' + (a.d.n || '') + ' ');
        const b = badge(a.d); if (b) used.appendChild(b);
        lines.push(used);
        lines.push(el('div', 'a-meta', [a.d.pos, a.d.ovr != null ? 'OVR ' + a.d.ovr : '', a.d.age ? 'age ' + a.d.age : ''].filter(Boolean).join(', ')));
        if (a.d.x === 'fa') flags.push('Free agent now'); else if (a.d.org && a.d.org !== m.t) flags.push('Now with ' + a.d.org);
      } else if (a.k.y) {
        lines.push(el('div', 'a-meta', 'Not used yet' + (a.k.own && a.k.own !== m.t ? ', now owned by ' + a.k.own : '')));
      }
    }
    if (three) lines.unshift(el('div', 'a-meta', 'From ' + m.f));
    if (multi) nm.append(' ', el('span', 'a-part', '#' + m.part));
    const then = m.vt ?? null, now = shown(m, a.v);
    topLine.append(nm, fromTo(then, now, m.ve)); li.append(topLine, valueRow(then, now, sc));
    li.append(...lines);
    if (flags.length) li.appendChild(el('div', 'a-flag', flags.join('. ') + '.'));
    li._v = Math.max(then ?? -Infinity, now ?? -Infinity);
    return li;
  };
  const renderDeal = (tid, persp) => {
    const rows = rowsOf[tid], deal = DEALS[tid], lead = leadRow(rows, persp);
    const order = [lead, ...rows.filter((r) => r !== lead)];
    const date = rows[0].date, three = rows.length > 2;
    const partIds = tid.split('+');
    $('deal-meta').textContent = fmtLong(date) + ', ' + (partIds.length > 1 ? 'trades ' + listJoin(partIds) + ', graded as one deal' : 'trade ' + tid);
    $('deal-title').textContent = order.map((r) => nameOf(r.team)).join('–');
    const thenEl = $('deal-then');
    thenEl.textContent = thenLine(rows, lead);
    thenEl.className = 'then ' + (three ? '' : lead.result === 'Win' ? 'win' : lead.result === 'Loss' ? 'loss' : 'even');
    $('deal-now').textContent = deal && SAVE ? nowLine(deal, rows, lead) : '';
    $('deal-now').hidden = !(deal && SAVE);
    const box = $('deal-sides'); box.replaceChildren(); box.style.setProperty('--n', order.length);
    // What each team received, at the trade and today; every bar on the card shares one scale.
    const sums = {};
    for (const r of order) {
      sums[r.team] = {then: 0, now: 0};
      for (const m of deal ? deal.moves : []) if (m.t === r.team) { sums[r.team].then += m.vt || 0; sums[r.team].now += nowOf(m) || 0; }
    }
    const sc = scaleOf(deal ? [...deal.moves.flatMap((m) => [m.vt, nowOf(m)]), ...Object.values(sums).flatMap((s) => [s.then, s.now])] : []);
    for (const r of order) {
      const sec = el('section', 'side' + (persp && r.team === persp ? ' me' : ''));
      const hd = el('div', 'side-head');
      hd.append(el('h3', '', nameOf(r.team) + ' received'));
      if (deal) hd.append(el('span', 'col-l', 'At the trade → today'));
      sec.appendChild(hd);
      const ul = el('ul', 'assets');
      if (deal) {
        const lis = deal.moves.filter((m) => m.t === r.team).map((m) => assetItem(m, partIds.length > 1, three, sc));
        lis.sort((a, b) => b._v - a._v);
        ul.append(...lis);
        for (const h of deal.holds || []) if (h.team === r.team) {
          const li = el('li', 'asset hold'); const t = el('div', 'a-top');
          t.append(el('span', 'a-name', 'Took on ' + h.pct + '% of ' + ((P[h.p] || {}).n || 'a player') + '’s salary'), el('span', 'a-val none', '—'));
          li.append(t, el('div', 'a-meta', 'Cap cost only; the game gives it no value'));
          ul.appendChild(li);
        }
        if (!ul.children.length) ul.appendChild(el('li', 'asset a-meta', 'Nothing'));
        const tot = el('div', 'total'), t = el('div', 'a-top'), s = sums[r.team];
        t.append(el('span', 'a-name', 'Total'), fromTo(s.then, s.now));
        tot.append(t, valueRow(s.then, s.now, sc, true));
        sec.append(ul, tot);
      } else {
        for (const p of parts(r.entries)) { const li = el('li', 'asset'); li.appendChild(el('div', 'a-name', p)); ul.appendChild(li); }
        if (!ul.children.length) ul.appendChild(el('li', 'asset a-meta', 'Nothing'));
        sec.append(ul, el('p', 'total a-meta', 'Game’s value at the trade: ' + fmtInt(r.value_in)));
      }
      box.appendChild(sec);
    }
    const notes = $('deal-notes'); notes.replaceChildren();
    if (!(SAVE && deal)) notes.appendChild(el('p', '', 'Built without the league save, so the card lists the assets without values.'));
    notes.hidden = !notes.children.length;
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
    // Values as the card shows them: both carry the game's 5% where it applied.
    const acols = ['date', 'trade', 'part', 'from', 'to', 'asset', 'type', 'position', 'ovr_at_trade', 'ovr_now', 'potential', 'motivation', 'age_at_trade', 'contract_now', 'now_with', 'value_at_trade', 'value_now', 'plus_5pct_at_trade', 'value_at_trade_estimated'];
    const out = [acols];
    for (const t of dealIds.slice().reverse()) {
      const deal = DEALS[t]; if (!deal) continue;
      for (const m of deal.moves) {
        const a = assetOf(m), vals = [m.vt ?? '', nowOf(m) ?? '', m.mk ? 'yes' : '', m.ve ? 'yes' : ''];
        if (a.kind === 'p') out.push([rowsOf[t][0].date, t, m.part, m.f, m.t, a.p.n, 'player', a.p.pos, m.ot ?? '', a.p.ovr ?? '', a.p.pot || '', a.p.pot ? MOT[a.p.mot ?? 0] : '', m.at ?? '', a.p.con, a.p.x === 'ret' ? 'Retired' : a.p.x === 'fa' ? 'FA' : a.p.org, ...vals]);
        else out.push([rowsOf[t][0].date, t, m.part, m.f, m.t, pickName(a.k) + (a.d ? ', used on ' + a.d.n : ''), a.d ? 'pick, used' : 'pick', a.d ? a.d.pos : '', '', a.d ? a.d.ovr ?? '' : '', a.d ? a.d.pot || '' : '', a.d && a.d.pot ? MOT[a.d.mot ?? 0] : '', '', '', a.d ? (a.d.x === 'fa' ? 'FA' : a.d.org) : a.k.own, ...vals]);
      }
    }
    $('dl-assets').href = csvUrl(out); $('dl-assets-wrap').hidden = false;
  }

  // ---- Cutoffs ----
  const cb = $('cut-body');
  for (const c of cuts.slice().reverse()) { const tr = document.createElement('tr'); cell(tr, c.min < -1 ? 'no floor' : fmtEdge(c.min), 'num'); cell(tr, c.grade); cb.appendChild(tr); }

  const render = () => { renderCards(); renderChart(); renderTeam(); };
  const seasonSel = $('season');
  seasonSel.replaceChildren(new Option('All seasons', ''), ...SEASONS.map((s) => new Option(seasonName(s), s)));
  seasonSel.addEventListener('change', () => { season = seasonSel.value; compute(); render(); renderAll(); });
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
print(f"wrote {out} (loader) and report.html: {len(ledger)} ledger rows, {len({r['trade'] for r in ledger})} deals, {len(teams)} teams, through {data['asOf']}")
