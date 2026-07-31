# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Python script that fetches upcoming matches from the [shootnscoreit.com](https://shootnscoreit.com) GraphQL API and generates a self-contained HTML dashboard (`index.html`).

SRA (Scandinavian/Finnish reservist shooting sports) is the point of the page and is the pre-selected discipline, but every ruleset the API returns is included — IPSC broken down per discipline, plus RESUL, PRS, DMR, IDPA, NROF, SADPA, Steel and the rest — so they can be filtered in.

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
2. **Weekly sweep** — 78 week-sized windows (`starts_after` + `starts_before`) covering 18 months, plus one open-ended tail query, deduplicated by event ID. ~80 calls, under a minute. See the cap section below for why it is shaped this way.
3. **Discipline label** — `discipline()` maps `rule` + `get_full_rule_display` to one canonical name and writes it as `data-d` on each row. Organizers type that field freely, so IPSC arrives as both `Handgun` and `IPSC Handgun`, `Action Air` and `IPSC Action Air`. Normalization is mechanical (prefix `IPSC `, shorten `Pistol Caliber Carbine` to `PCC`) rather than a lookup table, so an unseen variant still lands in the right bucket. All `rule="sr"` variants collapse to `SRA`; other rulesets already report clean labels and pass through.
4. **Group & sort** — Events are grouped by country (`get_region_display`), sorted by date within each group. Sweden is sorted first; all other countries alphabetically.
5. **HTML generation** — The entire page (CSS + data + JS) is written inline into `index.html` in the same directory. There is no separate template file; the HTML string is built directly in `fetch_sra.py`.

## The API result cap

The API truncates a query at roughly 90–100 rows. It is a **result cap, not a date cap** — earlier versions of this file claimed "~4 months", which was a misreading. `rule: "sr"` alone returns 98 events reaching ~10 months out, because SRA is sparse enough to fit inside the cap; ask for every ruleset at once and the same ~90 rows cover barely two weeks.

Consequences worth knowing before changing the fetch:

- **`rule` cannot be combined.** `rule: "sr,ip"` and `rule: ""` both return zero. One code per query, or omit the argument.
- **`starts_before` works**, which is what makes window pagination possible.
- **`sub_rule` is not a discipline.** It is not accepted as a filter argument at all (server-side `Cannot resolve keyword` error), and as a field it holds the scoring method (`nm`, `to`).
- A week of *all* rulesets is ~10 events worldwide, leaving a wide margin. `fetch_window()` still halves any window that comes back at `CAP_HINT` (80) rows or more, so growth on SSI's side cannot silently start dropping matches off the end.

**The fetch must never write a partial page.** If a window fails after its retries the script exits non-zero without touching `index.html`. The workflow commits that file unattended every 6h, so a half-fetched page would quietly replace a complete one and nobody would notice.

## Output file

The script writes to `index.html`. `sra_matches.html` (a stale local snapshot) is gitignored, but `index.html` is **not** — the GitHub Actions bot commits it to the repo on every run.

## Deployment

GitHub Actions (`.github/workflows/update-matches.yml`) runs `fetch_sra.py` every 6 hours and on manual dispatch. If `index.html` changed, it commits and pushes it. GitHub Pages then serves the result at https://steeriks.github.io/list-sra-matches/.

Required GitHub repo secrets: `SSI_EMAIL`, `SSI_PASSWORD`, `SSI_KEY`.

## HTML features (implemented in the embedded JS)

- **Search** — live text filter across match name and country
- **Reg. Open filter** — toggle to show only matches with open registration
- **Discipline multi-select dropdown** — sectioned SRA / IPSC / Other, matched against each row's `data-d`. **SRA is checked on first visit**; the selection is then remembered in `localStorage` under `sra_disciplines`, so the 6-hourly regeneration doesn't reset someone who follows IPSC. An empty selection means "show everything", the same convention as the country filter
- **Country multi-select dropdown** — filter by one or more countries
- **Sortable columns** — click any header; country grouping is hidden while a sort is active
- **iCal export** — calendar icons on date cells trigger `.ics` download
- **NEW badge** — `localStorage` tracks seen event IDs; events appearing for the first time get a red NEW badge for 24 hours

## Local proxy (`server.py`)

`server.py` (gitignored, not in repo) is an optional local proxy on port 8765. `fetch_sra.bat` starts it if nothing is already listening on that port. `fetch_sra.py` tries `http://localhost:8765/graphql` first and falls back to the live API — so the proxy is optional.
