# U14-A Zentralschweiz — Gruppe 2

A static standings page focused on Argovia Stars and the U14-A Zentralschweiz Regular Season, Group 2.

## Publish

The repository includes a GitHub Actions workflow that publishes the root folder to GitHub Pages on each push to `main`.

1. Open **Settings → Pages** and ensure **Build and deployment → Source** is set to **GitHub Actions** if GitHub has not configured it automatically.
2. Open the **Actions** tab and check the **Deploy GitHub Pages** workflow.
3. When the first deployment succeeds, the public site should be available at:
   https://frncscdrbn.github.io/u14a-zentralschweiz-standings/

## Data refresh

The **Refresh standings data** workflow runs every six hours and can also be started manually from **Actions**. It reads the SIHF U14-A schedule, keeps Regular Season Group 2 completed scores, and commits changes to `data/games.json`.

If SIHF changes its page structure, the updater intentionally fails instead of replacing the last known-good data with an empty result. Check the workflow run logs if an update fails.

Source: [SIHF U14-A schedule](https://www.sihf.ch/de/game-center/liga/spielplan/124-3)

## Calculation notes

The page currently calculates 3 points for a win and 0 for a loss, then sorts by points, goal difference, goals scored and team name. Verify any official SIHF tie-break or special competition rules before using this as an official table. The official SIHF schedule remains the source of truth.
