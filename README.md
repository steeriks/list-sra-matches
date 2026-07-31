# Upcoming SRA matches

A live dashboard of upcoming matches, pulled from [shootnscoreit.com](https://shootnscoreit.com)
and grouped by country — Sweden first, then the rest alphabetically.

SRA is what the page is for and is pre-selected, so it opens showing exactly the SRA matches.
Everything else the API publishes is loaded too and can be filtered in: IPSC per discipline
(Handgun, Handgun & PCC, Rifle, Shotgun, PCC, Mini Rifle, Action Air), plus RESUL, PRS, DMR,
IDPA, NROF, SADPA, NRA Precision Pistol, NTSA, Steel and more.

**→ <https://steeriks.github.io/list-sra-matches/>**

Nothing to install or run: the page is a single self-contained `index.html` that a scheduled
job keeps up to date.

## What the page can do

- **Search** across match name and country as you type
- **Reg. Open** toggle — show only matches you can register for right now
- **Discipline filter** — multi-select dropdown grouped into SRA / IPSC / Other, with a count
  next to each. **SRA is ticked to begin with**, and your choice is remembered between visits.
  Untick everything to see every discipline at once
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

The SSI GraphQL API truncates a query at roughly 90–100 rows. It is a cap on the *number of
results*, not on how far ahead you may look — SRA alone happens to fit ~10 months inside it,
which is what made it look like a four-month limit for a long time. Ask for every ruleset at
once and those same ~90 rows cover barely two weeks.

So `fetch_sra.py` sweeps in week-sized windows (`starts_after` + `starts_before`) across 18
months and merges the results by event id. A week of all rulesets worldwide is around ten
matches, far below the cap; any window that does come back suspiciously full is split in half
and re-fetched, so the page can't quietly start losing matches as SSI grows.

If a window can't be fetched, the script exits without writing `index.html` at all. A
partially fetched page would look perfectly normal and the bot would commit it over the good
one.

Everything lives in `fetch_sra.py`: the API calls, the grouping, and the page itself (CSS,
data and JS are written inline). There is no separate template.

`CLAUDE.md` has the architecture in more detail.
