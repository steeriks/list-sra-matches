import urllib.request, json, sys, os
from datetime import datetime, timezone

def _pause():
    if sys.stdin.isatty():
        input("Press Enter to exit.")

EMAIL    = os.environ.get("SSI_EMAIL",    "")
PASSWORD = os.environ.get("SSI_PASSWORD", "")
KEY      = os.environ.get("SSI_KEY",      "")
ENDPOINTS = [
    "http://localhost:8765/graphql",
    "https://shootnscoreit.com/graphql/",
]
if os.environ.get("GITHUB_ACTIONS") == "true":
    ENDPOINTS = ENDPOINTS[1:]
OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

def gql(query, token=None):
    headers = {"Content-Type": "application/json", "x-api-key": KEY}
    if token:
        headers["Authorization"] = f"JWT {token}"
    body = json.dumps({"query": query}).encode()
    for url in ENDPOINTS:
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read())
            if d.get("errors"):
                raise Exception(" | ".join(e["message"] for e in d["errors"]))
            return d["data"]
        except Exception as e:
            print(f"  [{url}] {e}")
            if url == ENDPOINTS[-1]:
                raise

# ── Login ─────────────────────────────────────────────────
print("Authenticating...")
try:
    data = gql(f'mutation {{ token_auth(email: {json.dumps(EMAIL)}, password: {json.dumps(PASSWORD)}) {{ token {{ token }} success errors }} }}')
except Exception as e:
    print(f"ERROR: {e}"); _pause(); sys.exit(1)

res = data["token_auth"]
if not res["success"]:
    print(f"Login failed: {res['errors']}"); _pause(); sys.exit(1)

token = res["token"]["token"]
print("Logged in.")

# ── Fetch ──────────────────────────────────────────────────────────────────
# The API silently truncates a query at roughly 90-100 rows. It is a *result*
# cap, not the date cap this script used to assume: `rule: "sr"` alone returns
# 98 events reaching ~10 months out, because SRA is sparse enough to fit. Ask
# for every ruleset at once and the same 90-odd rows cover barely two weeks.
#
# So instead of filtering by rule (which can't be combined anyway - `rule:
# "sr,ip"` returns nothing) we sweep week by week with starts_after +
# starts_before and merge. A week of *all* rulesets is ~10 events worldwide,
# leaving a wide margin to the cap, and it gives us every discipline for free.
from zoneinfo import ZoneInfo
from datetime import timedelta, date

now_local = datetime.now(ZoneInfo("Europe/Stockholm"))
today     = now_local.strftime("%Y-%m-%d")

WEEKS      = 78    # 18 months of week-sized windows, then one open-ended tail query
CAP_HINT   = 80    # at/above this a window is suspect - split it and re-ask
MAX_SPLIT  = 6     # recursion depth guard for the splitting
RETRIES    = 2     # per window, on top of the ENDPOINTS fallback inside gql()

FIELDS = """id rule get_full_rule_display get_full_level_display
    name starts ends
    get_state_display get_region_display
    venue competitors_count
    number_of_mainmatch_competitors_approved
    registration_starts registration_closes
    is_registration_possible
    get_registration_display
    organizer { id name }
    get_full_absolute_url"""

capped_windows = []

def fetch_window(after, before=None, depth=0):
    """Events in [after, before). Splits itself if the API looks like it capped us.

    Raises on failure - the caller must not fall back to partial data, because a
    short list here is indistinguishable from "quiet week" once it reaches HTML.
    """
    args = f'starts_after: "{after}"' + (f', starts_before: "{before}"' if before else "")
    last = None
    for attempt in range(RETRIES + 1):
        try:
            rows = gql(f'{{ events({args}) {{ {FIELDS} }} }}', token).get("events", []) or []
            break
        except Exception as ex:
            last = ex
    else:
        raise Exception(f"window {after}..{before or 'end'} failed after {RETRIES + 1} tries: {last}")

    if len(rows) < CAP_HINT or not before:
        return rows

    # Suspiciously full. Halve the window and ask again so growth on SSI's side
    # never silently starts dropping matches off the end of the page.
    a, b = date.fromisoformat(after), date.fromisoformat(before)
    if depth >= MAX_SPLIT or (b - a).days <= 1:
        capped_windows.append((after, before, len(rows)))
        return rows
    mid = a + (b - a) / 2
    return (fetch_window(after, mid.isoformat(), depth + 1)
            + fetch_window(mid.isoformat(), before, depth + 1))

print("Fetching upcoming matches (all rulesets)...")
events, seen = [], set()
try:
    cursor = date.fromisoformat(today)
    for _ in range(WEEKS):
        nxt = cursor + timedelta(days=7)
        rows = fetch_window(cursor.isoformat(), nxt.isoformat())
        cursor = nxt
        for e in rows:
            if e["id"] not in seen:
                seen.add(e["id"]); events.append(e)
    for e in fetch_window(cursor.isoformat()):          # tail beyond the sweep
        if e["id"] not in seen:
            seen.add(e["id"]); events.append(e)
except Exception as e:
    # Deliberately no partial write: the workflow commits index.html unattended
    # every 6h, so a half-fetched page would quietly replace a complete one.
    print(f"ERROR: {e}\nAborting without touching {OUT_FILE}")
    _pause(); sys.exit(1)

print(f"Found {len(events)} matches across {WEEKS} weekly windows.")
if capped_windows:
    print(f"WARNING: {len(capped_windows)} window(s) still hit the result cap after "
          f"splitting - matches may be missing: {capped_windows}")

def fmt(s):
    if not s: return "TBD"
    try: return datetime.fromisoformat(s[:10]).strftime("%d %b %Y")
    except: return s[:10]

def esc(s):
    return str(s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def discipline(e):
    """Canonical discipline label for the filter dropdown.

    `get_full_rule_display` is typed by organizers, so the same discipline
    arrives under several spellings - 'Handgun' and 'IPSC Handgun', 'Action Air'
    and 'IPSC Action Air'. Normalize IPSC mechanically (prefix, and shorten the
    one long-form name) rather than with a lookup table, so a variant nobody has
    used yet still lands in the right bucket instead of vanishing into its own.
    Every other ruleset already reports a clean, consistent label.
    """
    rule = (e.get("rule") or "").strip()
    full = (e.get("get_full_rule_display") or "").strip()
    if rule == "sr":
        return "SRA"                       # 'SRA' and the long four-gun variant
    if rule == "ip":
        full = full.replace("Pistol Caliber Carbine", "PCC")
        if not full:
            return "IPSC"
        return full if full.startswith("IPSC") else f"IPSC {full}"
    return full or rule.upper() or "Unknown"

def level(e):
    """Match level, or "" when the event doesn't declare one.

    Level names are per-ruleset, not global: IPSC uses Level I/II/III, SRA uses
    Club/Area/Nationals, Steel uses Tier-1/2/3. That is why the level dropdown is
    built from whichever disciplines are currently selected instead of being a
    fixed list. Rulesets that don't use levels report '--' or '-' as a filler.
    """
    v = (e.get("get_full_level_display") or "").strip()
    return "" if v in ("--", "-") else v

# Group by country, then sort by date within each country
from collections import defaultdict, Counter
by_country = defaultdict(list)
for e in events:
    country = e.get("get_region_display") or "Unknown"
    by_country[country].append(e)
for country in by_country:
    by_country[country].sort(key=lambda e: e.get("starts") or "")
sorted_countries = sorted(by_country.keys(), key=lambda c: (0 if c == "Sweden" else 1, c))

# ── Build HTML ─────────────────────────────────────────────
now_utc_dt = datetime.now(timezone.utc)
now_utc     = now_utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
now_utc_str = now_utc_dt.strftime("%d %b %Y %H:%M UTC")

COUNTRY_CODES = {
    "Sweden":"se","Finland":"fi","Estonia":"ee","Norway":"no","Denmark":"dk",
    "Latvia":"lv","Lithuania":"lt","Poland":"pl","Germany":"de","Netherlands":"nl",
    "Belgium":"be","France":"fr","Spain":"es","Italy":"it","United Kingdom":"gb",
    "United States":"us","Canada":"ca","Australia":"au","Czech Republic":"cz",
    "Austria":"at","Switzerland":"ch","Portugal":"pt","South Africa":"za",
}

# Discipline options for the dropdown, in three sections. Counts are baked in so
# the panel can show how much each choice is worth without the page recounting.
disc_counts = Counter(discipline(e) for e in events)
def _section(pred):
    return [{"label": d, "n": n} for d, n in
            sorted(disc_counts.items(), key=lambda kv: (-kv[1], kv[0])) if pred(d)]
DISC_SECTIONS = [
    {"title": "SRA",   "items": _section(lambda d: d == "SRA")},
    {"title": "IPSC",  "items": _section(lambda d: d.startswith("IPSC"))},
    {"title": "Other", "items": _section(lambda d: d != "SRA" and not d.startswith("IPSC"))},
]

# Levels sort by standing, not alphabetically - "Level III" must not land between
# "Level I" and "Level II", and Club/Area/Nationals is a ladder too. Anything not
# listed falls to the end, alphabetically.
LEVEL_ORDER = [
    "Level I", "Level II", "Level III", "Level IV", "Level V",
    "Tier-1 (Local)", "Tier-2 (State)", "Tier-3 (Regional)",
    "Club", "Regional", "Area", "Nationals", "International",
    "Sanctioned", "Unsanctioned", "Training",
]

rows_html = ""
for country in sorted_countries:
    country_events = by_country[country]
    code = COUNTRY_CODES.get(country, "")
    country_display = f'{esc(country)} <img class="flag" src="https://flagcdn.com/20x15/{code}.png" alt="" loading="lazy">' if code else esc(country)
    rows_html += f'<tr class="country-row" data-c="{esc(country)}"><td colspan="7">{country_display}</td></tr>\n'
    for e in country_events:
        name       = esc(e.get("name", "?"))
        venue_raw  = str(e.get("venue") or "")
        if venue_raw.startswith("http"):
            venue = f'<a href="{esc(venue_raw)}" target="_blank" class="map-link">Map →</a>'
        elif venue_raw:
            venue = esc(venue_raw)
        else:
            venue = "—"
        date       = f"{fmt(e.get('starts'))} – {fmt(e.get('ends'))}"
        org        = esc((e.get("organizer") or {}).get("name") or "—")
        status     = esc(e.get("get_state_display") or "—")
        comp       = e.get("number_of_mainmatch_competitors_approved") or e.get("competitors_count") or 0
        reg_open   = fmt(e.get("registration_starts"))
        reg_close  = fmt(e.get("registration_closes"))
        reg_now    = e.get("is_registration_possible")
        raw_url    = e.get("get_full_absolute_url") or ""
        event_url  = raw_url if raw_url.startswith("http") else f"https://{raw_url}" if raw_url else ""

        reg_badge  = '<span class="reg-open">● Open</span>' if reg_now else '<span class="reg-closed">● Closed</span>'
        row_class  = "row-open" if reg_now else "row-closed"
        match_link = f'<a href="{esc(event_url)}" target="_blank" class="reg-btn">SSI</a>' if event_url else ""

        rows_html += f"""<tr class="{row_class}" data-d="{esc(discipline(e))}" data-l="{esc(level(e))}">
  <td class="name">{name}</td>
  <td>{date}</td>
  <td>{reg_open} – {reg_close}<br><small>{reg_badge}</small></td>
  <td>{venue}</td>
  <td>{org}</td>
  <td>{comp}</td>
  <td>{match_link}</td>
</tr>\n"""

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Upcoming Matches</title>
<style>
  :root {{
    --bg: #0d0f1a; --surface: #151828; --surface2: #1e2235;
    --accent: #e63946; --amber: #f4a261; --green: #2dc653;
    --text: #e8e8f0; --text2: #7a7d99; --border: #252840;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: var(--bg); color: var(--text); padding: 32px 24px; line-height: 1.5; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 4px; }}
  .meta {{ color: var(--text2); font-size: 0.85rem; margin-bottom: 16px; }}
  .toolbar {{ display: flex; gap: 12px; align-items: center; margin-bottom: 20px; flex-wrap: wrap; }}
  .search-wrap {{ position: relative; flex: 1; min-width: 200px; max-width: 360px; }}
  .search-wrap input {{
    width: 100%; background: var(--surface2); border: 1px solid var(--border);
    color: var(--text); padding: 8px 12px 8px 34px; border-radius: 8px;
    font-size: 0.88rem; outline: none;
  }}
  .search-wrap input:focus {{ border-color: var(--accent); }}
  .search-wrap::before {{ content: "⌕"; position: absolute; left: 10px; top: 50%;
    transform: translateY(-50%); color: var(--text2); font-size: 1rem; pointer-events: none; }}
  .filter-btns {{ display: flex; gap: 6px; }}
  .filter-btns button {{
    background: var(--surface2); border: 1px solid var(--border); color: var(--text2);
    padding: 7px 14px; border-radius: 8px; font-size: 0.78rem; font-weight: 700;
    cursor: pointer; text-transform: uppercase; letter-spacing: 0.05em;
  }}
  .filter-btns button.active {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
  .filter-btns button:hover:not(.active) {{ border-color: var(--text2); color: var(--text); }}
  .country-dropdown {{ position: relative; }}
  .country-trigger {{
    background: var(--surface2); border: 1px solid var(--border); color: var(--text);
    padding: 7px 12px; border-radius: 8px; font-size: 0.82rem; outline: none; cursor: pointer;
    white-space: nowrap;
  }}
  .country-trigger.active {{ border-color: var(--accent); color: var(--accent); }}
  .country-panel {{
    display: none; position: absolute; top: calc(100% + 4px); left: 0; z-index: 100;
    background: var(--surface2); border: 1px solid var(--border); border-radius: 8px;
    min-width: 180px; padding: 4px 0; max-height: 280px; overflow-y: auto;
    box-shadow: 0 4px 16px rgba(0,0,0,0.4);
  }}
  .country-panel.open {{ display: block; }}
  .country-option {{
    display: flex; align-items: center; gap: 8px; padding: 7px 14px;
    cursor: pointer; font-size: 0.85rem; color: var(--text); user-select: none;
  }}
  .country-option:hover {{ background: var(--surface); }}
  .country-option input[type=checkbox] {{ accent-color: var(--accent); cursor: pointer; width: 14px; height: 14px; }}
  .country-option.checked {{ color: var(--accent); }}
  .opt-n {{ margin-left: auto; color: var(--text2); font-size: 0.75rem; padding-left: 10px; }}
  .panel-head {{
    padding: 7px 14px 3px; color: var(--text2); font-size: 0.68rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.08em; user-select: none;
  }}
  .panel-head + .country-option {{ margin-top: 0; }}
  .panel-head.sep {{ border-top: 1px solid var(--border); margin-top: 4px; padding-top: 8px; }}
  .count {{ color: var(--text2); font-size: 0.82rem; margin-left: auto; }}
  .wrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
  th {{
    text-align: left; padding: 10px 14px; color: var(--text2); font-weight: 600;
    font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;
    border-bottom: 2px solid var(--border); white-space: nowrap;
    cursor: pointer; user-select: none;
    position: sticky; top: 0; background: var(--bg); z-index: 10;
  }}
  th:last-child {{ cursor: default; }}
  th.sort-asc::after  {{ content: " ▲"; color: var(--accent); }}
  th.sort-desc::after {{ content: " ▼"; color: var(--accent); }}
  td {{ padding: 10px 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
  tr:hover td {{ background: var(--surface); }}
  tr.country-row td {{
    background: var(--surface2); color: var(--amber);
    font-weight: 700; font-size: 0.8rem; text-transform: uppercase;
    letter-spacing: 0.08em; padding: 8px 14px; border-bottom: none;
  }}
  td.name {{ font-weight: 600; color: var(--text); }}
  .reg-open  {{ color: var(--green); font-size: 0.78rem; font-weight: 700; }}
  .reg-closed {{ color: var(--accent); font-size: 0.78rem; font-weight: 700; }}
  tr.row-open  td:first-child {{ border-left: 3px solid var(--green); }}
  tr.row-closed td:first-child {{ border-left: 3px solid #2d3055; }}
  tr.row-open {{ background: rgba(45,198,83,0.03); }}
  .reg-btn {{
    display: inline-block; background: var(--accent); color: #fff;
    text-decoration: none; font-size: 0.78rem; font-weight: 700;
    padding: 5px 12px; border-radius: 6px; white-space: nowrap;
  }}
  .reg-btn:hover {{ opacity: 0.85; }}
  tr.row-closed {{ opacity: 0.6; }}
  tr.row-closed:hover {{ opacity: 1; }}
  .map-link {{ color: var(--text2); font-size: 0.82rem; white-space: nowrap; }}
  .ical-icon {{ color: var(--text2); text-decoration: none; margin-right: 6px; font-size: 0.78em;
    opacity: 0.55; cursor: pointer; display: inline-block; vertical-align: middle; white-space: nowrap; }}
  .ical-icon:hover {{ opacity: 1; color: var(--accent); }}
  img.flag {{ width: 20px; height: 15px; vertical-align: middle; margin-left: 5px; border-radius: 2px; }}
  small {{ display: block; margin-top: 4px; }}
  .no-results {{ text-align: center; color: var(--text2); padding: 40px; display: none; }}
  @media (max-width: 700px) {{
    body {{ padding: 12px; }}
    .wrap {{ overflow-x: unset; }}
    table {{ display: block; }}
    thead {{ display: none; }}
    tbody {{ display: flex; flex-direction: column; gap: 8px; }}
    tr.country-row {{ display: block; margin-top: 4px; }}
    tr.country-row td {{ display: block; border-radius: 6px; }}
    tr:not(.country-row) {{
      display: grid;
      grid-template-columns: 1fr auto;
      grid-template-rows: auto auto auto;
      gap: 3px 10px;
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: var(--surface);
    }}
    tr.row-open  {{ border-left: 3px solid var(--green); background: var(--surface); }}
    tr.row-closed {{ border-left: 3px solid #2d3055; background: var(--surface); }}
    tr.row-open  td:first-child,
    tr.row-closed td:first-child {{ border-left: none; }}
    tr:not(.country-row) td {{ padding: 0; border: none; background: transparent; }}
    td.name         {{ grid-column: 1; grid-row: 1; }}
    td:nth-child(2) {{ grid-column: 1; grid-row: 2; font-size: 0.8rem; color: var(--text2); }}
    td:nth-child(3) {{ grid-column: 1; grid-row: 3; font-size: 0.8rem; }}
    td:nth-child(3) small {{ display: inline; margin: 0 0 0 6px; }}
    td:nth-child(4), td:nth-child(5), td:nth-child(6) {{ display: none; }}
    td:nth-child(7) {{ grid-column: 2; grid-row: 1 / span 3; align-self: center; }}
  }}
</style>
</head>
<body>
<h1>Upcoming Matches</h1>
<div class="meta">SRA, IPSC and more &nbsp;·&nbsp; <span id="gen-time" data-utc="{now_utc}">Generated {now_utc_str}</span> &nbsp;·&nbsp; {len(events)} matches found &nbsp;·&nbsp; <span id="next-update"></span></div>
<div class="toolbar">
  <div class="search-wrap"><input type="text" id="search" placeholder="Search matches or countries…" autocomplete="off"></div>
  <div class="filter-btns">
    <button class="active" data-filter="all">All</button>
    <button data-filter="open">Reg. Open</button>
  </div>
  <div class="country-dropdown" id="disc-dropdown">
    <button class="country-trigger" id="disc-trigger">All disciplines ▾</button>
    <div class="country-panel" id="disc-panel"></div>
  </div>
  <div class="country-dropdown" id="level-dropdown">
    <button class="country-trigger" id="level-trigger">All levels ▾</button>
    <div class="country-panel" id="level-panel"></div>
  </div>
  <div class="country-dropdown" id="country-dropdown">
    <button class="country-trigger" id="country-trigger">All countries ▾</button>
    <div class="country-panel" id="country-panel"></div>
  </div>
  <span class="count" id="count"></span>
</div>
<div class="wrap">
<table id="tbl">
<thead>
  <tr>
    <th data-col="0">Match</th>
    <th data-col="1">Date</th>
    <th data-col="2">Registration</th>
    <th data-col="3">Venue</th>
    <th data-col="4">Organizer</th>
    <th data-col="5">Competitors</th>
    <th></th>
  </tr>
</thead>
<tbody id="tbody">
{rows_html}
</tbody>
</table>
<div class="no-results" id="no-results">No matches found.</div>
</div>
<script>
(function() {{
  var tbody         = document.getElementById('tbody');
  var search        = document.getElementById('search');
  var countEl       = document.getElementById('count');
  var noRes         = document.getElementById('no-results');
  var filterBtns    = document.querySelectorAll('[data-filter]');
  var headers       = document.querySelectorAll('th[data-col]');
  var countryTrigger = document.getElementById('country-trigger');
  var countryPanel   = document.getElementById('country-panel');
  var discTrigger    = document.getElementById('disc-trigger');
  var discPanel      = document.getElementById('disc-panel');
  var levelTrigger   = document.getElementById('level-trigger');
  var levelPanel     = document.getElementById('level-panel');
  var levelDropdown  = document.getElementById('level-dropdown');

  var sortCol = -1, sortAsc = true;
  var activeFilter    = 'all';
  var activeCountries = new Set();

  // Discipline filter. SRA is what this page is for, so it starts checked - but
  // the choice is remembered, otherwise the bot regenerating the page every 6h
  // would reset anyone who follows IPSC instead. Empty set = show everything,
  // same convention as the country filter above.
  var DISC_KEY = 'sra_disciplines';
  var activeDisciplines;
  try {{
    var stored = localStorage.getItem(DISC_KEY);
    activeDisciplines = new Set(stored === null ? ['SRA'] : JSON.parse(stored));
  }} catch (err) {{
    activeDisciplines = new Set(['SRA']);
  }}
  function saveDisciplines() {{
    try {{ localStorage.setItem(DISC_KEY, JSON.stringify([...activeDisciplines])); }} catch (err) {{}}
  }}

  // Level filter. Level names are per-ruleset (IPSC: Level I/II/III, SRA:
  // Club/Area/Nationals), so the options are rebuilt from whatever disciplines
  // are selected rather than being one fixed list.
  var LEVEL_KEY = 'sra_levels';
  var activeLevels;
  try {{ activeLevels = new Set(JSON.parse(localStorage.getItem(LEVEL_KEY) || '[]')); }}
  catch (err) {{ activeLevels = new Set(); }}
  function saveLevels() {{
    try {{ localStorage.setItem(LEVEL_KEY, JSON.stringify([...activeLevels])); }} catch (err) {{}}
  }}

  // Build flat data rows from the rendered HTML so sorting works
  // Each entry: {{ tr, country, sortKeys }}
  // We keep country-row tr's paired with their data rows.
  function getGroups() {{
    var groups = [];
    var currentCountry = '';
    var currentCountryTr = null;
    var rows = [];
    Array.from(tbody.rows).forEach(function(tr) {{
      if (tr.classList.contains('country-row')) {{
        if (currentCountryTr) groups.push({{ label: currentCountry, labelTr: currentCountryTr, rows: rows }});
        currentCountry = tr.getAttribute('data-c') || tr.cells[0].textContent.trim();
        currentCountryTr = tr;
        rows = [];
      }} else {{
        rows.push(tr);
      }}
    }});
    if (currentCountryTr) groups.push({{ label: currentCountry, labelTr: currentCountryTr, rows: rows }});
    return groups;
  }}

  var allGroups = getGroups();

  // iCal helpers
  var ICAL_MONTHS = {{Jan:1,Feb:2,Mar:3,Apr:4,May:5,Jun:6,Jul:7,Aug:8,Sep:9,Oct:10,Nov:11,Dec:12}};
  function parseIcalDate(str) {{
    var m = str.trim().match(/^(\\d{{1,2}})\\s+([A-Za-z]+)\\s+(\\d{{4}})$/);
    if (!m || !ICAL_MONTHS[m[2]]) return null;
    return m[3] + String(ICAL_MONTHS[m[2]]).padStart(2,'0') + String(m[1]).padStart(2,'0');
  }}
  function icalNextDay(d) {{
    var dt = new Date(+d.slice(0,4), +d.slice(4,6)-1, +d.slice(6,8));
    dt.setDate(dt.getDate()+1);
    return String(dt.getFullYear()) + String(dt.getMonth()+1).padStart(2,'0') + String(dt.getDate()).padStart(2,'0');
  }}
  function triggerIcal(summary, dtstart, dtend) {{
    var uid = Date.now() + '-' + Math.random().toString(36).slice(2) + '@sra';
    var escaped = summary.split(',').join('\\\\,').split(';').join('\\\\;');
    var ics = 'BEGIN:VCALENDAR\\r\\nVERSION:2.0\\r\\nPRODID:-//SRA Matches//EN\\r\\nBEGIN:VEVENT\\r\\nUID:' + uid + '\\r\\nDTSTART;VALUE=DATE:' + dtstart + '\\r\\nDTEND;VALUE=DATE:' + dtend + '\\r\\nSUMMARY:' + escaped + '\\r\\nEND:VEVENT\\r\\nEND:VCALENDAR';
    var blob = new Blob([ics], {{type:'text/calendar;charset=utf-8'}});
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = 'event.ics';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function(){{URL.revokeObjectURL(url);}}, 1000);
  }}
  function makeIcalIcon(label, summary, dtstart, dtend) {{
    var a = document.createElement('a');
    a.href = '#'; a.className = 'ical-icon'; a.title = 'Add to calendar'; a.textContent = '📅 ' + label;
    a.addEventListener('click', function(e){{ e.preventDefault(); triggerIcal(summary, dtstart, dtend); }});
    return a;
  }}
  allGroups.forEach(function(group) {{
    group.rows.forEach(function(tr) {{
      var name = tr.cells[0] ? tr.cells[0].textContent.trim() : 'SRA Match';
      var dc = tr.cells[1], rc = tr.cells[2];
      if (dc && dc.firstChild && dc.firstChild.nodeType === 3) {{
        var txt = dc.firstChild.textContent, parts = txt.split('\\u2013');
        var s = parseIcalDate(parts[0]);
        if (s) {{
          var e2 = parts[1] ? parseIcalDate(parts[1]) : null;
          dc.setAttribute('data-v', txt);
          dc.insertBefore(makeIcalIcon('Match date', name, s, e2 ? icalNextDay(e2) : icalNextDay(s)), dc.firstChild);
        }}
      }}
      if (rc && rc.firstChild && rc.firstChild.nodeType === 3) {{
        var rtxt = rc.firstChild.textContent, rparts = rtxt.split('\\u2013');
        var rs = parseIcalDate(rparts[0]);
        if (rs) {{
          var re2 = rparts[1] ? parseIcalDate(rparts[1]) : null;
          var rdate = re2 || rs;
          var rsummary = re2 ? 'Reg deadline: ' + name : 'Reg opens: ' + name;
          rc.setAttribute('data-v', rtxt);
          rc.insertBefore(makeIcalIcon('Reg date', rsummary, rdate, icalNextDay(rdate)), rc.firstChild);
        }}
      }}
    }});
  }});

  // Flags + multi-select country dropdown
  var CODES = {json.dumps(COUNTRY_CODES)};
  function makeFlag(country) {{
    var code = CODES[country]; if (!code) return null;
    var img = document.createElement('img');
    img.className = 'flag'; img.src = 'https://flagcdn.com/20x15/' + code + '.png';
    img.alt = ''; img.loading = 'lazy'; return img;
  }}
  function updateTrigger() {{
    var n = activeCountries.size;
    while (countryTrigger.firstChild) countryTrigger.removeChild(countryTrigger.firstChild);
    if (n === 0) {{
      countryTrigger.textContent = 'All countries ▾';
    }} else if (n === 1) {{
      var c = [...activeCountries][0];
      var fi = makeFlag(c);
      if (fi) {{ fi.style.marginRight = '5px'; countryTrigger.appendChild(fi); }}
      countryTrigger.appendChild(document.createTextNode(c + ' ▾'));
    }} else {{ countryTrigger.textContent = n + ' countries ▾'; }}
    countryTrigger.classList.toggle('active', n > 0);
  }}
  allGroups.forEach(function(group) {{
    if (!group.labelTr.cells[0].querySelector('img.flag')) {{
      var hfi = makeFlag(group.label);
      if (hfi) group.labelTr.cells[0].appendChild(hfi);
    }}
    var lbl = document.createElement('label');
    lbl.className = 'country-option';
    var cb = document.createElement('input');
    cb.type = 'checkbox'; cb.value = group.label;
    cb.addEventListener('change', function() {{
      if (cb.checked) activeCountries.add(group.label);
      else activeCountries.delete(group.label);
      lbl.classList.toggle('checked', cb.checked);
      updateTrigger(); render();
    }});
    lbl.appendChild(cb);
    var ofi = makeFlag(group.label);
    if (ofi) {{ ofi.style.margin = '0 5px 0 4px'; lbl.appendChild(ofi); }}
    lbl.appendChild(document.createTextNode(group.label));
    countryPanel.appendChild(lbl);
  }});
  countryTrigger.addEventListener('click', function(e) {{
    e.stopPropagation(); countryPanel.classList.toggle('open');
  }});
  document.addEventListener('click', function() {{ countryPanel.classList.remove('open'); }});
  countryPanel.addEventListener('click', function(e) {{ e.stopPropagation(); }});

  // ── Discipline dropdown ───────────────────────────────────────────────────
  var DISC_SECTIONS = {json.dumps(DISC_SECTIONS)};
  function updateDiscTrigger() {{
    var n = activeDisciplines.size;
    discTrigger.textContent = n === 0 ? 'All disciplines ▾'
                            : n === 1 ? [...activeDisciplines][0] + ' ▾'
                            : n + ' disciplines ▾';
    discTrigger.classList.toggle('active', n > 0);
  }}
  DISC_SECTIONS.forEach(function(section, si) {{
    if (!section.items.length) return;
    var h = document.createElement('div');
    h.className = 'panel-head' + (si > 0 ? ' sep' : '');
    h.textContent = section.title;
    discPanel.appendChild(h);
    section.items.forEach(function(item) {{
      var lbl = document.createElement('label');
      lbl.className = 'country-option';
      var cb = document.createElement('input');
      cb.type = 'checkbox'; cb.value = item.label;
      cb.checked = activeDisciplines.has(item.label);
      lbl.classList.toggle('checked', cb.checked);
      cb.addEventListener('change', function() {{
        if (cb.checked) activeDisciplines.add(item.label);
        else activeDisciplines.delete(item.label);
        lbl.classList.toggle('checked', cb.checked);
        saveDisciplines(); updateDiscTrigger(); buildLevels(); render();
      }});
      lbl.appendChild(cb);
      lbl.appendChild(document.createTextNode(item.label));
      var n = document.createElement('span');
      n.className = 'opt-n'; n.textContent = item.n;
      lbl.appendChild(n);
      discPanel.appendChild(lbl);
    }});
  }});
  discTrigger.addEventListener('click', function(e) {{
    e.stopPropagation(); discPanel.classList.toggle('open');
  }});
  document.addEventListener('click', function() {{ discPanel.classList.remove('open'); }});
  discPanel.addEventListener('click', function(e) {{ e.stopPropagation(); }});
  updateDiscTrigger();

  // ── Level dropdown (rebuilt whenever the discipline selection changes) ─────
  var LEVEL_ORDER = {json.dumps(LEVEL_ORDER)};
  function matchesDiscipline(tr) {{
    return activeDisciplines.size === 0 || activeDisciplines.has(tr.getAttribute('data-d'));
  }}
  function updateLevelTrigger() {{
    var n = activeLevels.size;
    levelTrigger.textContent = n === 0 ? 'All levels ▾'
                             : n === 1 ? [...activeLevels][0] + ' ▾'
                             : n + ' levels ▾';
    levelTrigger.classList.toggle('active', n > 0);
  }}
  function buildLevels() {{
    var counts = {{}};
    allGroups.forEach(function(group) {{
      group.rows.forEach(function(tr) {{
        if (!matchesDiscipline(tr)) return;
        var lv = tr.getAttribute('data-l') || '';
        if (lv) counts[lv] = (counts[lv] || 0) + 1;
      }});
    }});
    var levels = Object.keys(counts).sort(function(a, b) {{
      var ia = LEVEL_ORDER.indexOf(a), ib = LEVEL_ORDER.indexOf(b);
      if (ia < 0) ia = LEVEL_ORDER.length;
      if (ib < 0) ib = LEVEL_ORDER.length;
      return ia !== ib ? ia - ib : a.localeCompare(b);
    }});

    // Drop selected levels the new discipline set doesn't offer, otherwise the
    // page would show nothing with no visible control explaining why.
    [...activeLevels].forEach(function(lv) {{ if (!counts[lv]) activeLevels.delete(lv); }});
    saveLevels();

    while (levelPanel.firstChild) levelPanel.removeChild(levelPanel.firstChild);
    levels.forEach(function(lv) {{
      var lbl = document.createElement('label');
      lbl.className = 'country-option';
      var cb = document.createElement('input');
      cb.type = 'checkbox'; cb.value = lv;
      cb.checked = activeLevels.has(lv);
      lbl.classList.toggle('checked', cb.checked);
      cb.addEventListener('change', function() {{
        if (cb.checked) activeLevels.add(lv); else activeLevels.delete(lv);
        lbl.classList.toggle('checked', cb.checked);
        saveLevels(); updateLevelTrigger(); render();
      }});
      lbl.appendChild(cb);
      lbl.appendChild(document.createTextNode(lv));
      var n = document.createElement('span');
      n.className = 'opt-n'; n.textContent = counts[lv];
      lbl.appendChild(n);
      levelPanel.appendChild(lbl);
    }});
    // Nothing in view declares a level (e.g. RESUL or IDPA alone) - hide the
    // control rather than offer an empty menu.
    levelDropdown.style.display = levels.length ? '' : 'none';
    updateLevelTrigger();
  }}
  levelTrigger.addEventListener('click', function(e) {{
    e.stopPropagation(); levelPanel.classList.toggle('open');
  }});
  document.addEventListener('click', function() {{ levelPanel.classList.remove('open'); }});
  levelPanel.addEventListener('click', function(e) {{ e.stopPropagation(); }});
  buildLevels();

  function cellText(tr, col) {{
    if (!tr.cells[col]) return '';
    var dv = tr.cells[col].getAttribute('data-v');
    return dv !== null ? dv.trim() : tr.cells[col].textContent.trim();
  }}

  function applySort(rows) {{
    if (sortCol < 0) return rows;
    return rows.slice().sort(function(a, b) {{
      var av = cellText(a, sortCol), bv = cellText(b, sortCol);
      // numeric sort for competitors column (5)
      if (sortCol === 5) {{
        av = parseInt(av) || 0; bv = parseInt(bv) || 0;
        return sortAsc ? av - bv : bv - av;
      }}
      return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
    }});
  }}

  function render() {{
    var q = search.value.toLowerCase().trim();
    var frag = document.createDocumentFragment();
    var shown = 0;

    allGroups.forEach(function(group) {{
      if (activeCountries.size > 0 && !activeCountries.has(group.label)) return;
      var visible = group.rows.filter(function(tr) {{
        if (!matchesDiscipline(tr)) return false;
        if (activeLevels.size > 0 && !activeLevels.has(tr.getAttribute('data-l'))) return false;
        if (activeFilter === 'open' && !tr.classList.contains('row-open')) return false;
        if (!q) return true;
        var text = tr.textContent.toLowerCase();
        return text.indexOf(q) >= 0 || group.label.toLowerCase().indexOf(q) >= 0;
      }});
      if (visible.length === 0) return;
      var sorted = applySort(visible);
      if (sortCol < 0) frag.appendChild(group.labelTr);
      sorted.forEach(function(tr) {{ frag.appendChild(tr); shown++; }});
    }});

    tbody.innerHTML = '';
    tbody.appendChild(frag);
    countEl.textContent = shown + ' match' + (shown !== 1 ? 'es' : '');
    noRes.style.display = shown === 0 ? 'block' : 'none';
  }}

  search.addEventListener('input', render);


  filterBtns.forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      filterBtns.forEach(function(b) {{ b.classList.remove('active'); }});
      btn.classList.add('active');
      activeFilter = btn.dataset.filter;
      render();
    }});
  }});

  headers.forEach(function(th) {{
    th.addEventListener('click', function() {{
      var col = parseInt(th.dataset.col);
      if (sortCol === col) {{
        sortAsc = !sortAsc;
      }} else {{
        sortCol = col; sortAsc = true;
      }}
      headers.forEach(function(h) {{ h.classList.remove('sort-asc', 'sort-desc'); }});
      th.classList.add(sortAsc ? 'sort-asc' : 'sort-desc');
      render();
    }});
  }});

  // ── Generation timestamp in viewer's local timezone ─────────────────────
  (function() {{
    var el = document.getElementById('gen-time'); if (!el) return;
    var d = new Date(el.getAttribute('data-utc'));
    el.textContent = 'Generated ' + d.toLocaleString(undefined, {{
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
    }});
  }})();

  // ── Next update countdown ─────────────────────────────────────────────────
  (function() {{
    var el = document.getElementById('next-update'); if (!el) return;
    function tick() {{
      var now = new Date(), next = new Date(now);
      var nextH = (Math.floor(now.getUTCHours() / 6) + 1) * 6;
      if (nextH >= 24) {{ next.setUTCDate(next.getUTCDate() + 1); nextH = 0; }}
      next.setUTCHours(nextH, 0, 0, 0);
      var diff = next - now;
      if (diff <= 0) {{ el.textContent = 'updating…'; return; }}
      var h = Math.floor(diff / 3600000), m = Math.floor((diff % 3600000) / 60000);
      el.textContent = 'Next update ' + (h > 0 ? h + 'h ' : '') + m + 'm';
    }}
    tick(); setInterval(tick, 60000);
  }})();

  render();
}})();
</script>
</body>
</html>"""

with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Saved to: {OUT_FILE}")
if sys.platform == "win32" and sys.stdin.isatty():
    os.startfile(OUT_FILE)
_pause()
