import urllib.request, json, ssl, sys, os
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
OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def gql(query, token=None):
    headers = {"Content-Type": "application/json", "x-api-key": KEY}
    if token:
        headers["Authorization"] = f"JWT {token}"
    body = json.dumps({"query": query}).encode()
    for url in ENDPOINTS:
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
            with opener.open(req, timeout=20) as r:
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

# ── Fetch ─────────────────────────────────────────────────
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
print("Fetching upcoming SRA matches...")
try:
    data = gql(f"""{{
  events(rule: "sr", starts_after: "{today}") {{
    id get_content_type_key
    name starts ends
    get_state_display get_region_display
    venue competitors_count
    number_of_mainmatch_competitors_approved
    registration_starts registration_closes
    is_registration_possible
    get_registration_display
    organizer {{ id name }}
    get_full_absolute_url
  }}
}}""", token)
except Exception as e:
    print(f"ERROR: {e}"); _pause(); sys.exit(1)

events = data.get("events", [])
print(f"Found {len(events)} matches.")

def fmt(s):
    if not s: return "TBD"
    try: return datetime.fromisoformat(s[:10]).strftime("%d %b %Y")
    except: return s[:10]

def esc(s):
    return str(s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

# Group by country, then sort by date within each country
from collections import defaultdict
by_country = defaultdict(list)
for e in events:
    country = e.get("get_region_display") or "Unknown"
    by_country[country].append(e)
for country in by_country:
    by_country[country].sort(key=lambda e: e.get("starts") or "")
sorted_countries = sorted(by_country.keys())

# ── Build HTML ─────────────────────────────────────────────
now_str = datetime.now().strftime("%d %b %Y %H:%M")

rows_html = ""
for country in sorted_countries:
    country_events = by_country[country]
    rows_html += f'<tr class="country-row"><td colspan="7">{esc(country)}</td></tr>\n'
    for e in country_events:
        name       = esc(e.get("name", "?"))
        venue      = esc(e.get("venue") or "—")
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
        match_link = f'<a href="{esc(event_url)}" target="_blank" class="reg-btn">View →</a>' if event_url else ""

        rows_html += f"""<tr class="{row_class}">
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
<title>Upcoming SRA Matches</title>
<style>
  :root {{
    --bg: #0d0f1a; --surface: #151828; --surface2: #1e2235;
    --accent: #e63946; --amber: #f4a261; --green: #2dc653;
    --text: #e8e8f0; --text2: #7a7d99; --border: #252840;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: var(--bg); color: var(--text); padding: 32px 24px; }}
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
  .count {{ color: var(--text2); font-size: 0.82rem; margin-left: auto; }}
  .wrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
  th {{
    text-align: left; padding: 10px 14px; color: var(--text2); font-weight: 600;
    font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;
    border-bottom: 2px solid var(--border); white-space: nowrap;
    cursor: pointer; user-select: none;
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
  .reg-closed {{ color: var(--text2); font-size: 0.78rem; font-weight: 700; }}
  tr.row-open  td:first-child {{ border-left: 3px solid var(--green); }}
  tr.row-closed td:first-child {{ border-left: 3px solid #2d3055; }}
  tr.row-open {{ background: rgba(45,198,83,0.03); }}
  .reg-btn {{
    display: inline-block; background: var(--accent); color: #fff;
    text-decoration: none; font-size: 0.78rem; font-weight: 700;
    padding: 5px 12px; border-radius: 6px; white-space: nowrap;
  }}
  .reg-btn:hover {{ opacity: 0.85; }}
  small {{ display: block; margin-top: 4px; }}
  .no-results {{ text-align: center; color: var(--text2); padding: 40px; display: none; }}
  @media (max-width: 700px) {{ body {{ padding: 16px; }} td, th {{ padding: 8px; }} }}
</style>
</head>
<body>
<h1>Upcoming SRA Matches</h1>
<div class="meta">Generated {now_str} &nbsp;·&nbsp; {len(events)} matches found</div>
<div class="toolbar">
  <div class="search-wrap"><input type="text" id="search" placeholder="Search matches or countries…" autocomplete="off"></div>
  <div class="filter-btns">
    <button class="active" data-filter="all">All</button>
    <button data-filter="open">Reg. Open</button>
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
  var tbody   = document.getElementById('tbody');
  var search  = document.getElementById('search');
  var countEl = document.getElementById('count');
  var noRes   = document.getElementById('no-results');
  var filterBtns = document.querySelectorAll('[data-filter]');
  var headers = document.querySelectorAll('th[data-col]');

  var sortCol = -1, sortAsc = true;
  var activeFilter = 'all';

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
        currentCountry = tr.cells[0].textContent.trim();
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

  function cellText(tr, col) {{
    return tr.cells[col] ? tr.cells[col].textContent.trim() : '';
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
      // filter rows
      var visible = group.rows.filter(function(tr) {{
        if (activeFilter === 'open' && !tr.classList.contains('row-open')) return false;
        if (!q) return true;
        var text = tr.textContent.toLowerCase();
        return text.indexOf(q) >= 0 || group.label.toLowerCase().indexOf(q) >= 0;
      }});

      if (visible.length === 0) return;

      var sorted = applySort(visible);

      // Only show country header when not sorting (sorting flattens view)
      if (sortCol < 0) {{
        frag.appendChild(group.labelTr);
      }}
      sorted.forEach(function(tr) {{ frag.appendChild(tr); }});
      shown += sorted.length;
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
