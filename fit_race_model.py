#!/usr/bin/env python3
"""Refit the constants behind the playoff race on the Standings page (site_standings.py).

Usage:
    python fit_race_model.py [--saves ../saves]

Run it once a season, after the regular season ends, and paste what it prints into site_standings.py.

For each season in the saves, the save with the most games played is the season's record. Every first save of a
month from opening night on is a snapshot: the lineups and the results at that point, used to predict each game
played after it. The fit, in order:
  BETA      least squares of the rest-of-season goal difference per game on the lineup's average overall
            (12 forwards, 6 defencemen, starting goalie), each against the league average that day
  GAME_VAR  variance of one game's goal difference
  PRIOR_SD  how far a team's true level sat from its lineup number: the opening-night residuals of each
            complete season, less the noise a season of games leaves
  HOME, SLOPE  the log-odds of a home win, HOME + SLOPE x the strength gap, by a grid search on log-loss
  OT_SHARE  share of games that went to overtime
"""
import argparse
import collections
import glob
import math
import os
import statistics

import site_pages as sp
from site_standings import raw_overall


def snapshot(path):
    sl = sp.read_full(path)
    lg, PL = sl["Leagues"]["0"], sl["PlayerList"]
    games = [g for g in lg["SaveGames"] if not g.get("_StatType") and not g.get("Playoffs")]
    played = [g for g in games if "WinnerID" in g]
    line, rec = {}, {}
    for k, t in lg["TeamList"].items():
        lu = t.get("LineUp") or {}
        f, d, g = ([raw_overall(PL[str(i)]) for i in lu.get(key) or [] if str(i) in PL] for key in ("ForwardsIds", "DefensesIds", "GoaliesIds"))
        line[int(k)] = (statistics.mean(f) if f else 0, statistics.mean(d) if d else 0, g[0] if g else 0)
        rec[int(k)] = [0, 0]
    for g in played:
        diff = g.get("ScoreHome", 0) - g.get("ScoreAway", 0)
        rec[g["HomeID"]][0] += 1; rec[g["HomeID"]][1] += diff
        rec[g["AwayID"]][0] += 1; rec[g["AwayID"]][1] -= diff
    slim = [(g["DateTime"][:10], g["HomeID"], g["AwayID"], g.get("ScoreHome", 0) - g.get("ScoreAway", 0), bool(g.get("OT"))) for g in played]
    first = min((g["DateTime"][:10] for g in games), default="")
    return {"day": sl["LastSaveDay"][:10], "year": sl.get("Year"), "line": line, "rec": rec, "games": slim, "total": len(games), "first": first}


def solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for i in range(n):
        piv = max(range(i, n), key=lambda r: abs(M[r][i]))
        M[i], M[piv] = M[piv], M[i]
        for r in range(n):
            if r != i:
                f = M[r][i] / M[i][i]
                M[r] = [x - f * y for x, y in zip(M[r], M[i])]
    return [M[i][n] / M[i][i] for i in range(n)]


def relative(line):
    avg = [statistics.mean(v[c] for v in line.values()) for c in range(3)]
    return {t: [v[c] - avg[c] for c in range(3)] for t, v in line.items()}


def rest_of(games, day):
    out = collections.defaultdict(lambda: [0, 0])
    for d, h, a, diff, ot in games:
        if d >= day:
            out[h][0] += 1; out[h][1] += diff
            out[a][0] += 1; out[a][1] -= diff
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--saves", default=os.path.join("..", "saves"))
    a = ap.parse_args()
    snaps = []
    for p in sorted(glob.glob(os.path.join(a.saves, "*.zip"))):
        snaps.append(snapshot(p))
        print(f"read {os.path.basename(p)}: season {snaps[-1]['year']}, {len(snaps[-1]['games'])} of {snaps[-1]['total']} games played", flush=True)
    seasons = []
    for year in sorted({s["year"] for s in snaps}):
        mine = sorted((s for s in snaps if s["year"] == year and s["total"]), key=lambda s: (s["day"], len(s["games"])))
        if not mine:
            continue
        final = max(mine, key=lambda s: len(s["games"]))
        months, picks = set(), []
        for s in mine:
            if s["day"] >= s["first"] and s["day"][:7] not in months and any(g[0] >= s["day"] for g in final["games"]):
                months.add(s["day"][:7])
                picks.append(s)
        seasons.append((year, final, picks))
        print(f"season {year}: {len(final['games'])} games, snapshots {[s['day'] for s in picks]}")

    # BETA
    X, y = [], []
    for year, final, picks in seasons:
        for s in picks:
            rel, rest = relative(s["line"]), rest_of(final["games"], s["day"])
            for t, (n, diff) in rest.items():
                if n >= 10:
                    X.append(rel[t]); y.append(diff / n)
    my = statistics.mean(y)
    A = [[sum(r[i] * r[j] for r in X) for j in range(3)] for i in range(3)]
    beta = solve(A, [sum(r[i] * (v - my) for r, v in zip(X, y)) for i in range(3)])
    every = [g for year, final, picks in seasons for g in final["games"]]
    game_var = statistics.pvariance([g[3] for g in every])
    ot_share = sum(g[4] for g in every) / len(every)

    # PRIOR_SD, from the opening-night snapshot of each complete season
    left = []
    for year, final, picks in seasons:
        if picks and len(final["games"]) == final["total"]:
            rel, rest = relative(picks[0]["line"]), rest_of(final["games"], picks[0]["day"])
            res = [diff / n - sum(b * x for b, x in zip(beta, rel[t])) for t, (n, diff) in rest.items()]
            left.append(max(0.0, statistics.pvariance(res) - game_var / statistics.mean(n for n, _ in rest.values())))
    prior_sd = math.sqrt(statistics.mean(left)) if left else 0.267

    # HOME, SLOPE
    pairs = []
    for year, final, picks in seasons:
        for s in picks:
            rel, strength = relative(s["line"]), {}
            for t, (n, diff) in s["rec"].items():
                prior = sum(b * x for b, x in zip(beta, rel[t]))
                strength[t] = (prior / prior_sd ** 2 + diff / game_var) / (1 / prior_sd ** 2 + n / game_var)
            pairs += [(strength[h] - strength[aw], diff > 0) for d, h, aw, diff, ot in final["games"] if d >= s["day"]]

    def loss(h, k):
        return -sum(math.log(p if won else 1 - p) for p, won in ((1 / (1 + math.exp(-(h + k * gap))), won) for gap, won in pairs)) / len(pairs)

    best = min(((loss(hi * 0.05, ki * 0.05), hi * 0.05, ki * 0.05) for hi in range(0, 11) for ki in range(1, 41)))
    print(f"\n{len(pairs)} game predictions; log-loss {best[0]:.4f}, against {loss(best[1], 0):.4f} for a coin flip with the home edge\n")
    print(f"BETA = ({beta[0]:.3f}, {beta[1]:.3f}, {beta[2]:.3f})")
    print(f"PRIOR_SD = {prior_sd:.3f}")
    print(f"GAME_VAR = {game_var:.2f}")
    print(f"HOME, SLOPE = {best[1]:.2f}, {best[2]:.2f}")
    print(f"OT_SHARE = {ot_share:.3f}")


if __name__ == "__main__":
    main()
