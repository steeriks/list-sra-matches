# Upcoming SRA matches

A live dashboard of upcoming SRA matches, pulled from [shootnscoreit.com](https://shootnscoreit.com)
and grouped by country — Sweden first, then the rest alphabetically.

**→ <https://steeriks.github.io/list-sra-matches/>**

Nothing to install or run: the page is a single self-contained `index.html` that a scheduled
job keeps up to date.

## What the page can do

- **Search** across match name and country as you type
- **Reg. Open** toggle — show only matches you can register for right now
- **Country filter** — multi-select dropdown
- **Sortable columns** — click any header (country grouping is hidden while a sort is active)
- **iCal export** — the calendar icon on a date downloads that match as an `.ics` file
- **NEW badge** — matches that showed up for the first time are flagged for 24 hours, tracked
  per browser in `localStorage`

## How it stays current

`.github/workflows/update-matches.yml` runs `fetch_sra.py` **every 6 hours**, and on manual
dispatch from the Actions tab. If the generated `index.html` differs, the bot commits it as
`Update: <timestamp> UTC` and pushes. GitHub Pages serves `main`, so the site follows
automatically.

The workflow needs three repo secrets: `SSI_EMAIL`, `SSI_PASSWORD`, `SSI_KEY`.

> **Working on this repo: `git pull --rebase` before you push.** The bot commits to `main`
> several times a day, so a local checkout goes stale quickly and a plain push is rejected.

## Running the fetcher yourself

The script reads credentials from the environment only — never hardcode them in
`fetch_sra.py`:

```
SSI_EMAIL=... SSI_PASSWORD=... SSI_KEY=... python fetch_sra.py
```

On Windows there is a `fetch_sra.bat` launcher that sets those variables. It holds them in
plaintext, so it is gitignored and has to be maintained locally.

The script overwrites `index.html` in place — the same file the workflow commits.

## Notes on the data

The SSI GraphQL API silently caps a query at roughly four months of results. `fetch_sra.py`
works around that by querying twice — from today, and from today + 90 days — then
deduplicating by event id, so matches further out still show up.

Everything lives in `fetch_sra.py`: the API calls, the grouping, and the page itself (CSS,
data and JS are written inline). There is no separate template.

`CLAUDE.md` has the architecture in more detail.
