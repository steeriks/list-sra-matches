# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Python script that fetches upcoming SRA (Scandinavian/Finnish reservist shooting sports) matches from the [shootnscoreit.com](https://shootnscoreit.com) GraphQL API and generates a self-contained HTML dashboard (`index.html`).

## Running the fetcher

On Windows, use the batch launcher (credentials are injected as env vars):
```
fetch_sra.bat
```

Or run manually with credentials set:
```
set SSI_EMAIL=...
set SSI_PASSWORD=...
set SSI_KEY=...
python fetch_sra.py
```

`fetch_sra.bat` is gitignored (it contains plaintext credentials) and must be maintained locally. The Python script reads only from environment variables — never hardcode credentials in `fetch_sra.py`.

## Architecture

Everything lives in `fetch_sra.py`:

1. **Auth** — GraphQL `token_auth` mutation to get a JWT.
2. **Two-window fetch** — The API silently caps results to ~4 months. To work around this, the script queries twice: `starts_after=today` and `starts_after=today+90d`, then deduplicates by event ID.
3. **Group & sort** — Events are grouped by country (`get_region_display`), sorted by date within each group. Sweden is sorted first; all other countries alphabetically.
4. **HTML generation** — The entire page (CSS + data + JS) is written inline into `index.html` in the same directory. There is no separate template file; the HTML string is built directly in `fetch_sra.py`.

## Output file

The script writes to `index.html`. `sra_matches.html` (a stale local snapshot) is gitignored, but `index.html` is **not** — the GitHub Actions bot commits it to the repo on every run.

## Deployment

GitHub Actions (`.github/workflows/update-matches.yml`) runs `fetch_sra.py` every 6 hours and on manual dispatch. If `index.html` changed, it commits and pushes it. GitHub Pages then serves the result at https://steeriks.github.io/list-sra-matches/.

Required GitHub repo secrets: `SSI_EMAIL`, `SSI_PASSWORD`, `SSI_KEY`.

## HTML features (implemented in the embedded JS)

- **Search** — live text filter across match name and country
- **Reg. Open filter** — toggle to show only matches with open registration
- **Country multi-select dropdown** — filter by one or more countries
- **Sortable columns** — click any header; country grouping is hidden while a sort is active
- **iCal export** — calendar icons on date cells trigger `.ics` download
- **NEW badge** — `localStorage` tracks seen event IDs; events appearing for the first time get a red NEW badge for 24 hours

## Local proxy (`server.py`)

`server.py` (gitignored, not in repo) is an optional local proxy on port 8765. `fetch_sra.bat` starts it if nothing is already listening on that port. `fetch_sra.py` tries `http://localhost:8765/graphql` first and falls back to the live API — so the proxy is optional.
