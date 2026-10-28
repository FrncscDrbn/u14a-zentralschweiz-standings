#!/usr/bin/env python3
"""Refresh completed U14-Top Zentralschweiz Group 2 results from the SIHF group schedule.

This updater is deliberately separate from scripts/update_data.py and writes only
data/u14top_games.json, so the existing U14-A refresh workflow remains untouched.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "u14top_games.json"
SOURCE = "https://www.sihf.ch/de/game-center/liga/spielplan/123-3?group=74720"

TEAMS = [
    "Argovia Stars",
    "Brandis Juniors",
    "EHC Basel Nachwuchs I",
    "EHC Burgdorf",
    "EHC Olten Prospect",
    "EHC Winterthur I",
    "GCK Lions",
    "HC Dragon Thun gelb",
    "HC Lugano 2 BIANCO",
    "HC NWU",
    "Hockey Innerschwyz HCI II",
    "SC Bern Future schwarz",
    "SC Langenthal",
    "SC Lyss",
    "SC Rapperswil-Jona Lakers",
    "SC Rapperswil-Jona Lakers",
    "EV Zug II",
]
TEAM_ALT = "|".join(re.escape(t) for t in sorted(TEAMS, key=len, reverse=True))
GROUP = re.compile(r"Regular Season\s+(?:Gruppe|Gr\.)\s*2\b", re.I)
SCORE = re.compile(
    rf"(?:Ende|Nach OT\s*\d*|Nach SO\s*\d*|Finished)\s+"
    rf"(?P<home>{TEAM_ALT})\s+(?P<hs>\d+)\s+"
    rf"(?P<away>{TEAM_ALT})\s+(?P<as>\d+)",
    re.IGNORECASE,
)
DATE = re.compile(
    r"(?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)?\\s*,?\\s*"
    r"(\\d{1,2})\\.(\\d{1,2})\\.(\\d{4})",
    re.I,
)
MONTHS = {
    "januar": 1, "january": 1, "februar": 2, "february": 2,
    "märz": 3, "maerz": 3, "march": 3, "april": 4, "mai": 5, "may": 5,
    "juni": 6, "june": 6, "juli": 7, "july": 7, "august": 8,
    "september": 9, "oktober": 10, "october": 10, "november": 11,
    "dezember": 12, "december": 12,
}
MONTH_HEADING = re.compile(
    r"\\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\\s+(20\\d{2})\\b",
    re.I,
)
DAY_HEADING = re.compile(
    r"\\b(?:Mo|Di|Mi|Do|Fr|Sa|So|Mon|Tue|Wed|Thu|Fri|Sat|Sun|"
    r"Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)\\.?\\s+(\\d{1,2})\\b",
    re.I,
)


def date_for_position(text, position):
    """Read either a full German date or SIHF's month-heading + weekday/day layout."""
    full_dates = list(DATE.finditer(text[:position]))
    if full_dates:
        d = full_dates[-1]
        return f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}"

    months = list(MONTH_HEADING.finditer(text[:position]))
    if not months:
        return None
    month_heading = months[-1]
    month = MONTHS[month_heading.group(1).casefold()]
    year = int(month_heading.group(2))
    day_headings = list(DAY_HEADING.finditer(text, month_heading.end(), position))
    if not day_headings:
        return None
    day = int(day_headings[-1].group(1))
    return f"{year:04d}-{month:02d}-{day:02d}"


def canonical_team(name):
    return next(team for team in TEAMS if team.casefold() == name.casefold())


def main():
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; U14Top-Standings/1.0)"})
    response = session.get(SOURCE, timeout=40)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    page_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    # Match completed score lines directly instead of splitting the page at each
    # group label. SIHF's rendered page includes several adjacent league labels,
    # and splitting at labels can leave score lines outside the expected window.
    score_pattern = re.compile(
        rf"(?:Ende|Nach OT\s*\d*|Nach SO\s*\d*|Finished)\s+"
        rf"(?P<home>{TEAM_ALT})\s+(?P<hs>\d+)\s+"
        rf"(?P<away>{TEAM_ALT})\s+(?P<as>\d+)",
        re.IGNORECASE,
    )
    markers = list(GROUP.finditer(page_text))
    games_by_key = {}

    for match in score_pattern.finditer(page_text):
        # The immediately preceding fixture label identifies the regular-season
        # group. Ignore exhibitions and other U14-Top groups.
        context = page_text[max(0, match.start() - 180):match.start()]
        group_matches = list(GROUP.finditer(context))
        if not group_matches:
            continue
        last_group_label = group_matches[-1].group(0)
        if not re.search(r"(?:Gruppe|Gr\.)\s*2\b", last_group_label, re.I):
            continue

        game_date = date_for_position(page_text, match.start())
        if not game_date:
            continue
        home, away = canonical_team(match.group("home")), canonical_team(match.group("away"))
        home_score, away_score = int(match.group("hs")), int(match.group("as"))
        key = (game_date, home, home_score, away, away_score)
        games_by_key[key] = {
            "date": game_date,
            "home": home,
            "home_score": home_score,
            "away": away,
            "away_score": away_score,
        }

    games = sorted(games_by_key.values(), key=lambda game: (game["date"], game["home"], game["away"]))
    if not games:
        print(f"DEBUG: HTTP {response.status_code}; {len(page_text)} text chars; {len(markers)} Group 2 markers; sample: {page_text[:700]}")
        raise SystemExit("No U14-Top Group 2 results parsed; leaving data/u14top_games.json unchanged.")

    try:
        previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    except (OSError, json.JSONDecodeError):
        previous = {}
    changed = previous.get("source") != [SOURCE] or previous.get("games") != games
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds") if changed or not previous.get("updated_at") else previous["updated_at"]
    payload = {"source": [SOURCE], "updated_at": updated_at, "games": games}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Parsed {len(games)} completed U14-Top Group 2 games from SIHF.")
    print(f"Source: {SOURCE}; group markers: {len(markers)}")


if __name__ == "__main__":
    main()
