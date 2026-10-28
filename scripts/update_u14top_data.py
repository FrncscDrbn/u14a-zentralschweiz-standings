#!/usr/bin/env python3
"""Refresh completed U14-Top Zentralschweiz Group 2 results from SIHF."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "u14top_games.json"
SOURCE = "https://www.sihf.ch/de/game-center/liga/spielplan/123-3?group=74720"

# Teams actually listed in Zentralschweiz Regular Season Group 2.
# Ostschweiz teams and Züri-Cup crossover fixtures must never enter this table.
TEAMS = [
    "Argovia Stars", "Brandis Juniors", "EHC Basel Nachwuchs I",
    "EHC Burgdorf", "EHC Olten Prospect", "HC Dragon Thun gelb",
    "HC Lugano 2 BIANCO", "HC NWU", "Hockey Innerschwyz HCI II",
    "SC Bern Future schwarz", "SC Langenthal", "SC Lyss", "EV Zug II",
]
TEAM_ALT = "|".join(re.escape(t) for t in sorted(TEAMS, key=len, reverse=True))
SCORE = re.compile(
    rf"(?:Ende|Nach OT\s*\d*|Nach SO\s*\d*|Finished)\s+"
    rf"(?P<home>{TEAM_ALT})\s+(?P<hs>\d+)\s+"
    rf"(?P<away>{TEAM_ALT})\s+(?P<as>\d+)",
    re.I,
)
GROUP_LABEL = re.compile(r"Regular Season\s+(?:Gruppe|Gr\.)\s*(\d+)\b", re.I)
MONTHS = {
    "januar": 1, "january": 1, "februar": 2, "february": 2,
    "märz": 3, "maerz": 3, "march": 3, "april": 4, "mai": 5, "may": 5,
    "juni": 6, "june": 6, "juli": 7, "july": 7, "august": 8,
    "september": 9, "oktober": 10, "october": 10, "november": 11,
    "dezember": 12, "december": 12,
}
FULL_DATE = re.compile(
    r"(?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)?\s*,?\s*"
    r"(\d{1,2})\.(\d{1,2})\.(20\d{2})", re.I
)
MONTH_HEADING = re.compile(
    r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\s+(20\d{2})\b",
    re.I,
)
DAY_HEADING = re.compile(
    r"\b(?:Mo|Di|Mi|Do|Fr|Sa|So|Mon|Tue|Wed|Thu|Fri|Sat|Sun|"
    r"Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)\.?\s+(\d{1,2})\b",
    re.I,
)


def date_in_text(text):
    """Return a date only when a full date is present in this local text block."""
    match = FULL_DATE.search(text)
    if match:
        day, month, year = map(int, match.groups())
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return None
    month_match = MONTH_HEADING.search(text)
    day_match = DAY_HEADING.search(text)
    if month_match and day_match:
        month = MONTHS[month_match.group(1).casefold()]
        year = int(month_match.group(2))
        day = int(day_match.group(1))
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return None
    return None


def game_date_for_node(node, soup):
    """Resolve a fixture date locally; never reuse the last date in the whole page."""
    current = node
    for _ in range(8):
        if current is None:
            break

        # Prefer explicit machine-readable dates attached to the fixture/card.
        for tag in ([current] if getattr(current, "attrs", None) is not None else []):
            for key, value in tag.attrs.items():
                if key in {"datetime", "data-date", "data-start-date", "data-game-date",
                           "data-match-date", "data-datetime"}:
                    values = value if isinstance(value, list) else [value]
                    for raw in values:
                        parsed = date_in_text(str(raw))
                        if parsed:
                            return parsed
                        iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", str(raw))
                        if iso:
                            try:
                                return datetime.strptime(iso.group(1), "%Y-%m-%d").date().isoformat()
                            except ValueError:
                                pass

        # Some SIHF layouts put a full date in the fixture card itself.
        local_text = current.get_text(" ", strip=True) if hasattr(current, "get_text") else ""
        if len(local_text) <= 180:
            parsed = date_in_text(local_text)
            if parsed:
                return parsed
        current = current.parent

    # Fallback: inspect only preceding siblings in the fixture's local DOM
    # context. The old implementation scanned every preceding tag on the page,
    # so all fixtures inherited the final calendar heading (e.g. Oct 31).
    day = month = year = None
    branch = node
    for _ in range(7):
        if branch is None or branch.parent is None:
            break
        sibling = branch.previous_sibling
        inspected = 0
        while sibling is not None and inspected < 30:
            inspected += 1
            text = sibling.get_text(" ", strip=True) if hasattr(sibling, "get_text") else str(sibling).strip()
            if text and len(text) <= 100:
                full = FULL_DATE.search(text)
                if full:
                    d, m, y = map(int, full.groups())
                    try:
                        return datetime(y, m, d).date().isoformat()
                    except ValueError:
                        pass
                month_match = MONTH_HEADING.search(text)
                if month is None and month_match:
                    month = MONTHS[month_match.group(1).casefold()]
                    year = int(month_match.group(2))
                day_match = DAY_HEADING.fullmatch(text.strip())
                if day is None and day_match:
                    day = int(day_match.group(1))
                if day is not None and month is not None and year is not None:
                    try:
                        return datetime(year, month, day).date().isoformat()
                    except ValueError:
                        return None
            sibling = sibling.previous_sibling
        branch = branch.parent

    return None

def main():
    response = requests.get(
        SOURCE, timeout=40,
        headers={"User-Agent": "Mozilla/5.0 (compatible; U14Top-Standings/1.0)"},
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    # SIHF splits a visible score line across multiple HTML text nodes, so
    # searching each individual string with SCORE misses every result. Find
    # status nodes first, then climb to the smallest enclosing fixture element
    # whose combined text contains the score and group label.
    candidates = []
    status_text = re.compile(r"\b(?:Ende|Nach\s+OT|Nach\s+SO|Finished)\b", re.I)
    for status in soup.find_all(string=status_text):
        current = status.parent
        for _ in range(8):
            if current is None:
                break
            text = current.get_text(" ", strip=True)
            match = SCORE.search(text)
            group_match = GROUP_LABEL.search(text)
            if match and group_match:
                # Keep the status node as well as the fixture container.
                # The container can be a broad calendar wrapper, so use the
                # status node's DOM position when resolving the fixture date.
                candidates.append((current, status, match))
                break
            current = current.parent

    games_by_key = {}
    skipped_no_date = 0
    for element, status, match in candidates:
        # Group labels must be in the fixture's local card/row. Do not reuse a
        # stale group label from a previous fixture or neighboring group.
        group = None
        current = element
        for _ in range(5):
            if current is None:
                break
            labels = list(GROUP_LABEL.finditer(current.get_text(" ", strip=True)))
            if labels:
                group = int(labels[-1].group(1))
                break
            current = current.parent
        if group != 2:
            continue

        game_date = game_date_for_node(status.parent, soup)
        if not game_date:
            skipped_no_date += 1
            continue
        home, away = match.group("home"), match.group("away")
        hs, aws = int(match.group("hs")), int(match.group("as"))
        key = (game_date, home, hs, away, aws)
        games_by_key[key] = {
            "date": game_date, "home": home, "home_score": hs,
            "away": away, "away_score": aws,
        }

    games = sorted(games_by_key.values(), key=lambda g: (g["date"], g["home"], g["away"]))
    if not games:
        raise SystemExit(
            f"No valid Zentralschweiz Group 2 results parsed "
            f"(score candidates={len(candidates)}, missing dates={skipped_no_date}); "
            "leaving data/u14top_games.json unchanged."
        )

    # Fail closed if the parser sees suspiciously uniform dates or teams outside
    # the known Group 2 roster. Never overwrite good data with a malformed scrape.
    dates = {game["date"] for game in games}
    if len(games) > 1 and len(dates) == 1:
        raise SystemExit("All parsed results have one date; refusing to overwrite data.")
    allowed = set(TEAMS)
    if any(g["home"] not in allowed or g["away"] not in allowed for g in games):
        raise SystemExit("Unexpected team in parsed results; refusing to overwrite data.")

    try:
        previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    except (OSError, json.JSONDecodeError):
        previous = {}
    changed = previous.get("source") != [SOURCE] or previous.get("games") != games
    updated_at = (
        datetime.now(timezone.utc).isoformat(timespec="seconds")
        if changed or not previous.get("updated_at") else previous["updated_at"]
    )
    payload = {"source": [SOURCE], "updated_at": updated_at, "games": games}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Parsed {len(games)} completed Zentralschweiz Group 2 games.")
    print(f"Skipped {skipped_no_date} score candidates without fixture-local dates.")


if __name__ == "__main__":
    main()
