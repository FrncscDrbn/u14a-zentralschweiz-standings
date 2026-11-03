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

def print_scrape_diagnostics(soup, response):
    """Print bounded diagnostics when SIHF's page no longer matches our parser."""
    page_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    print("SIHF scrape diagnostics:")
    print(f"  HTTP status: {response.status_code}")
    print(f"  Final URL: {response.url}")
    print(f"  Content-Type: {response.headers.get('Content-Type', 'unknown')}")
    print(f"  Response bytes: {len(response.content)}")
    print(f"  Page title: {soup.title.get_text(' ', strip=True) if soup.title else '(missing)'}")
    print(f"  Visible text length: {len(page_text)}")
    for label in ("Ende", "Nach OT", "Nach SO", "Finished", "Regular Season", "Gruppe", "Group"):
        print(f"  Text occurrences [{label}]: {len(re.findall(re.escape(label), page_text, re.I))}")
    for team in ("Argovia Stars", "SC Langenthal", "EHC Basel Nachwuchs I"):
        positions = [m.start() for m in re.finditer(re.escape(team), page_text, re.I)]
        print(f"  Team occurrences [{team}]: {len(positions)}")
        for pos in positions[:2]:
            start, end = max(0, pos - 160), min(len(page_text), pos + len(team) + 240)
            print(f"    Context: {page_text[start:end]}")    # Show exactly how completed fixtures are represented in the current response.
    for pos, match in enumerate(re.finditer(r"Ende", page_text, re.I), start=1):
        start, end = max(0, match.start() - 260), min(len(page_text), match.end() + 360)
        print(f"  Ende context {pos}: {page_text[start:end]}")
    status_nodes = list(soup.find_all(string=re.compile(r"Ende", re.I)))
    print(f"  Text nodes containing Ende: {len(status_nodes)}")
    for index, node in enumerate(status_nodes[:5], start=1):
        print(f"    Ende node {index}: {str(node).strip()!r}")
        parent = node.parent
        for depth in range(4):
            if parent is None:
                break
            parent_text = re.sub(r"\s+", " ", parent.get_text(" ", strip=True))
            print(f"      ancestor {depth + 1} [{parent.name}]: {parent_text[:500]}")
    print(f"  HTML text-node count: {len(soup.find_all(string=True))}")
    # Check whether completed results are embedded in page hydration scripts.
    scripts = soup.find_all("script")
    print(f"  Script elements: {len(scripts)}")
    for script in scripts:
        src = script.get("src")
        if src:
            print(f"  Script src: {src}")
        body = script.string or script.get_text(" ", strip=True)
        if body and any(team.casefold() in body.casefold() for team in ("Argovia Stars", "SC Langenthal", "EHC Basel Nachwuchs I")):
            compact = re.sub(r"\s+", " ", body)
            print("  Team-bearing script: " + compact[:1200])
    # Inspect the external SIHF game-center bundle; inline HTML has no results.
    for script in scripts:
        src = script.get("src", "")
        if "game-center.js" not in src:
            continue
        script_url = requests.compat.urljoin(response.url, src)
        try:
            js_response = requests.get(script_url, timeout=25, headers={"User-Agent": "Mozilla/5.0 (compatible; U14Top-Standings/1.0)"})
            print(f"  Game-center JS status: {js_response.status_code}")
            print(f"  Game-center JS bytes: {len(js_response.content)}")
            js = js_response.text
            urls = sorted(set(re.findall(r"""(?:https?://[^\\s"\x27<>]+|/(?:[A-Za-z0-9_?&=./%-]+))""", js)))
            for endpoint in urls:
                if any(token in endpoint.casefold() for token in ("api", "game", "spiel", "match", "fixture", "result")):
                    print("  JS endpoint candidate: " + endpoint[:300])
            for keyword in ("fetch(", "XMLHttpRequest", "axios", "ajax", "api/", "game-center"):
                for match in list(re.finditer(re.escape(keyword), js, re.I))[:3]:
                    pos = match.start()
                    print(f"  JS context [{keyword}]: {js[max(0, pos-220):pos+420]}")
        except requests.RequestException as exc:
            print(f"  Game-center JS fetch failed: {type(exc).__name__}: {exc}")
    print(f"  Elements with date attributes: {len(soup.select('[data-date], [data-datetime], time[datetime]'))}")
    # Replay the HTMX request with the originating page's cookies and browser headers.
    probe_links = soup.select('a[hx-get][data-game-id]')[:5]
    print('  Browser-style GameShort endpoint probes:', len(probe_links))
    session = requests.Session()
    session.cookies.update(response.cookies)
    browser_headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html, */*; q=0.01',
        'Referer': response.url,
        'Origin': 'https://www.sihf.ch',
        'X-Requested-With': 'XMLHttpRequest',
        'HX-Request': 'true',
        'HX-Current-URL': response.url,
    }
    for link in probe_links:
        endpoint = requests.compat.urljoin(response.url, link.get('hx-get', ''))
        try:
            detail = session.get(endpoint, timeout=25, headers=browser_headers)
            detail_soup = BeautifulSoup(detail.text, 'html.parser')
            detail_text = re.sub(r'\\s+', ' ', detail_soup.get_text(' ', strip=True))
            print('  GameShort:', 'game_id=' + str(link.get('data-game-id')), 'status=' + str(detail.status_code), 'bytes=' + str(len(detail.content)), 'content_type=' + str(detail.headers.get('Content-Type')))
            print('    Response headers:', {key: detail.headers.get(key) for key in ('HX-Trigger', 'HX-Redirect', 'Location', 'Set-Cookie') if detail.headers.get(key)})
            print('    Text:', detail_text[:1000])
            print('    HTML:', detail.text[:1800].replace('\\n', ' '))
        except requests.RequestException as exc:
            print('  GameShort request failed:', type(exc).__name__, str(exc))
    # Inspect fixture cards and links associated with SIHF game IDs.
    game_links = soup.select('a[data-game-id]')
    print('  Anchors with data-game-id:', len(game_links))
    for link in game_links[:100]:
        print('  Game link:', 'href=' + str(link.get('href')), 'game_id=' + str(link.get('data-game-id')), 'league_id=' + str(link.get('data-league-id')), 'text=' + ' '.join(link.stripped_strings)[:300])
        parent = link.parent
        for level in range(1, 4):
            if parent is None:
                break
            print('    Game link parent', level, '[' + str(parent.name) + ']:', str(parent)[:1400])
            parent = parent.parent
    # Inspect server-driven fixture loading and filtering hooks.
    htmx_elements = [tag for tag in soup.find_all(True) if any(str(key).startswith('hx-') for key in tag.attrs)]
    print('  Elements with HTMX attributes:', len(htmx_elements))
    for tag in htmx_elements[:60]:
        attrs = {key: value for key, value in tag.attrs.items() if str(key).startswith('hx-') or str(key).startswith('data-') or key in ('id', 'class')}
        print('  HTMX element:', tag.name, str(attrs)[:900])
    for form in soup.find_all('form')[:30]:
        print('  Form:', 'method=' + str(form.get('method', 'get')), 'action=' + str(form.get('action')), 'id=' + str(form.get('id')))
    for tag in soup.find_all(True):
        for key, value in tag.attrs.items():
            key_text = str(key).casefold()
            if key_text.startswith('data-') and any(word in key_text for word in ('game', 'match', 'fixture', 'league', 'group', 'phase')):
                print('  Fixture data attribute:', tag.name, key, str(value)[:400])


def main():
    # The schedule page contains fixture cards, but completed scores are loaded
    # by SIHF through each card's HTMX GameShort endpoint. Reuse the page session
    # so cookies and browser request headers are present.
    session = requests.Session()
    response = session.get(
        SOURCE, timeout=40,
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"},
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    fixture_links = soup.select("a[hx-get][data-game-id]")
    if not fixture_links:
        print_scrape_diagnostics(soup, response)
        raise SystemExit("SIHF schedule page contained no GameShort fixture cards; refusing to treat this as an empty match day.")

    browser_headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html, */*; q=0.01",
        "Referer": response.url,
        "Origin": "https://www.sihf.ch",
        "X-Requested-With": "XMLHttpRequest",
        "HX-Request": "true",
        "HX-Current-URL": response.url,
    }

    games_by_key = {}
    skipped_no_date = 0
    completed_cards = 0
    failed_cards = []
    seen_ids = set()

    for link in fixture_links:
        game_id = str(link.get("data-game-id", "")).strip()
        endpoint = link.get("hx-get", "").strip()
        if not game_id or not endpoint or game_id in seen_ids:
            continue
        seen_ids.add(game_id)

        detail_url = requests.compat.urljoin(response.url, endpoint)
        try:
            detail = session.get(detail_url, timeout=25, headers=browser_headers)
            detail.raise_for_status()
        except requests.RequestException as exc:
            failed_cards.append(f"{game_id}: {type(exc).__name__}: {exc}")
            continue

        detail_soup = BeautifulSoup(detail.text, "html.parser")
        detail_text = re.sub(r"\s+", " ", detail_soup.get_text(" ", strip=True))
        match = SCORE.search(detail_text)
        if not match:
            # Scheduled fixtures normally say "Wie geplant"; they are not
            # errors and must not be mistaken for completed results.
            continue

        # The fixture card itself identifies its league/group. Restrict the
        # scraper to Group 2 and the known Zentralschweiz team roster.
        card_text = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
        card_context = " ".join((card_text, detail_text))
        group_match = GROUP_LABEL.search(card_context)
        if not group_match or int(group_match.group(1)) != 2:
            continue

        home, away = match.group("home"), match.group("away")
        if home not in TEAMS or away not in TEAMS:
            continue

        completed_cards += 1
        game_date = game_date_for_node(link, soup)
        if not game_date:
            skipped_no_date += 1
            continue

        hs, aws = int(match.group("hs")), int(match.group("as"))
        key = (game_date, home, hs, away, aws)
        games_by_key[key] = {
            "date": game_date, "home": home, "home_score": hs,
            "away": away, "away_score": aws,
        }

    if failed_cards:
        # Do not publish a partial scrape if SIHF failed to serve any fixture
        # details; a transient endpoint error is different from an empty day.
        raise SystemExit(
            f"SIHF GameShort requests failed for {len(failed_cards)} fixture(s); "
            f"leaving {OUT.relative_to(ROOT)} unchanged. First errors: "
            + "; ".join(failed_cards[:5])
        )

    games = sorted(games_by_key.values(), key=lambda g: (g["date"], g["home"], g["away"]))

    # A valid schedule with no completed games is a normal outcome (e.g. a
    # weekday with no matches or before the first result). Keep the last known
    # results and exit successfully instead of failing the GitHub Actions job.
    if not games:
        print(
            f"SIHF schedule checked successfully: {len(seen_ids)} Group 2 fixture "
            f"cards inspected; no completed results found. "
            f"Completed cards without dates: {skipped_no_date}. "
            f"Leaving {OUT.relative_to(ROOT)} unchanged."
        )
        return

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
    print(f"Parsed {len(games)} completed Zentralschweiz Group 2 games from {len(seen_ids)} fixture cards.")
    print(f"Skipped {skipped_no_date} completed score candidates without fixture-local dates.")


if __name__ == "__main__":
    main()
