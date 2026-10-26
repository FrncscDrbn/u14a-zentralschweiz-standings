#!/usr/bin/env python3
"""Refresh completed Regular Season Gr. 2 results from the official SIHF schedule.

The updater is deliberately fail-closed: if the SIHF page structure changes and no
matches can be parsed, it exits without replacing the last known-good JSON.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "games.json"
URL = "https://www.sihf.ch/de/game-center/liga/spielplan/124-3"
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
SCORE = re.compile(
    rf"(?:Ende|Nach OT\s*\d*|Nach SO\s*\d*|Finished)\s+"
    rf"(?P<home>{TEAM_ALT})\s+(?P<hs>\d+)\s+"
    rf"(?P<away>{TEAM_ALT})\s+(?P<as>\d+)",
    re.IGNORECASE,
)
DATE = re.compile(r"(?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)?\s*,?\s*(\d{1,2})\.(\d{1,2})\.(\d{4})", re.I)

def main():
    response = requests.get(URL, timeout=40, headers={"User-Agent": "U14A-Standings/1.0 (GitHub Actions)"})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    # Keep spaces between separate HTML elements; normalize whitespace for matching.
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    games = []
    seen = set()
    markers = list(re.finditer(r"Regular Season Gr\.\s*2", text, re.I))
    for index, marker in enumerate(markers):
        # Restrict parsing to this fixture, so a later result cannot be assigned to it.
        end = markers[index + 1].start() if index + 1 < len(markers) else min(len(text), marker.start() + 500)
        window = text[marker.start():end]
        match = SCORE.search(window)
        if not match:
            continue
        home, away = match.group("home"), match.group("away")
        home = next((t for t in TEAMS if t.casefold() == home.casefold()), home)
        away = next((t for t in TEAMS if t.casefold() == away.casefold()), away)
        hs, aws = int(match.group("hs")), int(match.group("as"))
        key = (home, hs, away, aws)
        if key in seen:
            continue
        seen.add(key)
        prefix = text[max(0, marker.start() - 220):marker.start()]
        dates = list(DATE.finditer(prefix))
        game_date = None
        if dates:
            d = dates[-1]
            game_date = f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}"
        games.append({
            "date": game_date or "",
            "home": home, "home_score": hs,
            "away": away, "away_score": aws,
        })
    if not games:
        raise SystemExit("No Group 2 results parsed; leaving data/games.json unchanged.")
    games.sort(key=lambda g: (g["date"], g["home"], g["away"]))
    payload = {
        "source": URL,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "games": games,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Parsed {len(games)} completed Group 2 games.")
if __name__ == "__main__":
    main()
