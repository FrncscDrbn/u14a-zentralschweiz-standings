#!/usr/bin/env python3
"""Refresh completed U14-A Zentralschweiz Group 2 results from SIHF team schedules.

The league overview defaults to Group 1 in its server-rendered HTML, so read the
individual schedules of Group 2 teams instead. The same fixture can appear on both
teams' schedules; results are deduplicated before writing.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "games.json"

# Every Group 2 fixture includes at least one of these teams. The team IDs are
# the official SIHF schedule URLs, not inferred from team names.
SCHEDULES = [
    "https://www.sihf.ch/de/game-center/team/spielplan/124-3-104022",  # Argovia Stars
    "https://www.sihf.ch/de/game-center/team/spielplan/124-3-105155",  # EHC Basel Nachwuchs
    "https://www.sihf.ch/de/game-center/team/spielplan/124-3-105514",  # EHC Sursee
    "https://www.sihf.ch/de/game-center/team/spielplan/124-3-105807",  # HC NWU Black
    "https://www.sihf.ch/de/game-center/team/spielplan/124-3-105821",  # HC NWU Green
    "https://www.sihf.ch/de/game-center/team/spielplan/124-3-104011",  # HC Wohlen Freiamt
    "https://www.sihf.ch/de/game-center/team/spielplan/124-3-105874",  # LUNOXX Reinach
]
TEAMS = [
    "Argovia Stars",
    "EHC Basel Nachwuchs",
    "EHC Sursee",
    "HC NWU Black",
    "HC NWU Green",
    "HC Wohlen Freiamt",
    "Hockey Innerschwyz HCI II",
    "LUNOXX Reinach",
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
    r"(?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)?\s*,?\s*"
    r"(\d{1,2})\.(\d{1,2})\.(\d{4})",
    re.I,
)


def canonical_team(name):
    return next(t for t in TEAMS if t.casefold() == name.casefold())


def main():
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; U14A-Standings/1.0)"})
    games_by_key = {}
    diagnostics = []

    for url in SCHEDULES:
        try:
            response = session.get(url, timeout=40)
            response.raise_for_status()
        except requests.RequestException as exc:
            diagnostics.append(f"Could not fetch {url}: {exc}")
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        markers = list(GROUP.finditer(text))
        parsed_from_page = 0

        for index, marker in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
            window = text[marker.start():end]
            match = SCORE.search(window)
            if not match:
                continue

            # Date headings precede the fixture on SIHF team schedules.
            dates = list(DATE.finditer(text[:marker.start()]))
            if not dates:
                continue
            d = dates[-1]
            game_date = f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}"
            home, away = canonical_team(match.group("home")), canonical_team(match.group("away"))
            hs, aws = int(match.group("hs")), int(match.group("as"))
            key = (game_date, home, hs, away, aws)
            games_by_key[key] = {
                "date": game_date,
                "home": home, "home_score": hs,
                "away": away, "away_score": aws,
            }
            parsed_from_page += 1

        diagnostics.append(
            f"{url.rsplit('/', 1)[-1]}: HTTP {response.status_code}, "
            f"{len(text)} text chars, {len(markers)} Group 2 fixtures, "
            f"{parsed_from_page} completed results"
        )

    games = sorted(games_by_key.values(), key=lambda g: (g["date"], g["home"], g["away"]))
    if not games:
        print("DEBUG: " + " | ".join(diagnostics))
        raise SystemExit("No Group 2 results parsed; leaving data/games.json unchanged.")

    payload = {
        "source": SCHEDULES,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "games": games,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Parsed {len(games)} completed Group 2 games.")
    print(" | ".join(diagnostics))


if __name__ == "__main__":
    main()
