#!/usr/bin/env python3
"""Build the pages beside the trade report cards: team value, cap, standings and progression.

Usage:
    python site_pages.py [--saves ../saves] [--only cap,standings] [--out .]

build_report_cards.py runs this at the end of its own build and hands over the saves it has already
read; run on its own, only the newest save is read, so the progression page has no summer rollover.
"""
import argparse
import datetime
import glob
import gzip
import json
import os
import re
import zipfile
from fractions import Fraction

import site_shell

POSITIONS = {0: "LW", 1: "C", 2: "RW", 3: "LD", 4: "RD", 5: "G"}
# Overall = offence/defence blend by player type (goalies: their one rating), halves to even.
OVR_WEIGHTS = {("F", 1): 70, ("F", 2): 70, ("F", 7): 60, ("F", 0): 30, ("F", 3): 35, ("D", 4): 50, ("D", 5): 65, ("D", 6): 25}
POTENTIAL = {"F": ["Franchise", "Elite", "Top 6 F", "Top 9 F", "4th line", "Depth", "Minor", "Semipro", "Amateur"],
             "D": ["Franchise", "Elite", "Top 4 D", "Top 6 D", "7th D", "Depth", "Minor", "Semipro", "Amateur"],
             "G": ["Franchise", "Elite", "Starter", "Mid Starter", "Backup", "Depth", "Minor", "Semipro", "Amateur"]}
EPOCH = datetime.date(1970, 1, 1)


def read_full(path):
    """A save's whole live state (dynamic/d0.hlm, not the autosave under auto/), minus the league password."""
    with zipfile.ZipFile(path) as z:
        hits = [n for n in z.namelist() if n.endswith("dynamic/d0.hlm") and "/auto/" not in "/" + n]
        raw = z.read(min(hits, key=len))
    sl = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)["SportLeague"]
    sl.pop("Password", None)
    return sl


def read_member(path, name):
    """One of a save's other files (gzip JSON at the top of the zip), such as pastathlete.hlm: every player's past seasons."""
    with zipfile.ZipFile(path) as z:
        raw = z.read(min((n for n in z.namelist() if n.endswith(name) and "/auto/" not in "/" + n), key=len))
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)


def group(p):
    if p.get("$type") == "Goalie":
        return "G"
    return "D" if (p.get("Positions") or [0])[0] in (3, 4) else "F"


def overall(p):
    g = group(p)
    if g == "G":
        return round(p.get("BaseDefense", 0))
    w = OVR_WEIGHTS.get((g, p.get("_PlayerType") or 0), 50)
    x = (w * Fraction(str(p.get("BaseOffense", 0))) + (100 - w) * Fraction(str(p.get("BaseDefense", 0)))) / 100
    q, r = divmod(x, 1)
    return int(q) + (1 if r > Fraction(1, 2) or (r == Fraction(1, 2) and q % 2) else 0)


def age_on(p, day):
    b = EPOCH + datetime.timedelta(days=p["Birthday"])
    return day.year - b.year - ((day.month, day.day) < (b.month, b.day))


def full_name(p):
    return f"{p.get('FirstName', '')} {p.get('LastName', '')}".strip()


def positions(p):
    return "/".join(POSITIONS.get(x, "?") for x in p.get("Positions") or [])


def potential(p, tier=None):
    return POTENTIAL[group(p)][min(p.get("_Potential") or 0 if tier is None else tier, 8)]


class Ctx:
    """What every page builder gets: the newest save in full, plus the trimmed older saves when there are any."""

    def __init__(self, newest, states=None, saves_dir=None, out_dir="."):
        self.path, self.states, self.saves_dir, self.out_dir = newest, states, saves_dir, out_dir
        self.sl = read_full(newest)
        self.lg = self.sl["Leagues"]["0"]
        self.PL = self.sl["PlayerList"]
        self.day = self.sl["LastSaveDay"][:10]
        self.date = datetime.date.fromisoformat(self.day)
        self.season0 = self.date.year if self.date.month >= 7 else self.date.year - 1  # first year of the league year
        self.code = {int(k): t["ShortCity"] for k, t in self.lg["TeamList"].items()}
        self.league_of = {}  # a club's id in any league -> that league's abbreviation
        for L in self.sl["Leagues"].values():
            for k in L.get("TeamList") or {}:
                self.league_of[int(k)] = L.get("Abbreviation") or ""
        self.by_org = {t: [] for t in self.code}  # NHL team id -> [(player id, player)] whose NHL rights it holds
        for pid, p in self.PL.items():
            t = (p.get("TeamIds") or {}).get("0")
            if t in self.by_org:
                self.by_org[t].append((pid, p))

    def season_label(self, k=0):
        y = self.season0 + k
        return f"{y}-{(y + 1) % 100:02d}"

    def base(self):
        return {"asOf": self.day, "names": site_shell.TEAM_NAMES}


def newest_save(saves_dir):
    """The newest save by file name: YYYY-MM-DD.zip, with -v2, -v3 for same-day re-posts."""
    def key(p):
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:-v(\d+))?\.zip", os.path.basename(p))
        return (m.group(1), int(m.group(2) or 1)) if m else ("", 0)
    paths = sorted(glob.glob(os.path.join(saves_dir, "*.zip")), key=key)
    if not paths:
        raise SystemExit(f"no save zips in {saves_dir}")
    return paths[-1]


def build_all(newest, states=None, saves_dir=None, out_dir=".", only=None):
    import site_cap
    import site_progression
    import site_standings
    import site_value
    ctx = Ctx(newest, states, saves_dir, out_dir)
    builders = {"value": site_value, "cap": site_cap, "standings": site_standings, "progression": site_progression}
    for key, fname, _ in site_shell.PAGES[1:]:
        if only and key not in only:
            continue
        html, summary = builders[key].build(ctx)
        if html is None:
            print(f"skipped {fname}: {summary}", flush=True)
            continue
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as f:
            f.write(html)
        print(f"wrote {fname}: {summary}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build the team value, cap, standings and progression pages.")
    ap.add_argument("--saves", default=os.path.join("..", "saves"), help="folder of league save zips (default ../saves)")
    ap.add_argument("--only", help="comma-separated pages to build: value, cap, standings, progression")
    ap.add_argument("--out", default=".", help="folder to write the pages to")
    a = ap.parse_args()
    build_all(newest_save(a.saves), saves_dir=a.saves, out_dir=a.out, only=set(a.only.split(",")) if a.only else None)
