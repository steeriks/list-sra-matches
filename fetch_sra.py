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
sorted_countries = sorted(by_country.keys(), key=lambda c: (0 if c == "Sweden" else 1, c))

# ── Build HTML ─────────────────────────────────────────────
now_str = datetime.now().strftime("%d %b %Y %H:%M")

COUNTRY_FLAGS = {
    "Sweden":"🇸🇪","Finland":"🇫🇮","Estonia":"🇪🇪","Norway":"🇳🇴","Denmark":"🇩🇰",
    "Latvia":"🇱🇻","Lithuania":"🇱🇹","Poland":"🇵🇱","Germany":"🇩🇪","Netherlands":"🇳🇱",
    "Belgium":"🇧🇪","France":"🇫🇷","Spain":"🇪🇸","Italy":"🇮🇹","United Kingdom":"🇬🇧",
    "United States":"🇺🇸","Canada":"🇨🇦","Australia":"🇦🇺","Czech Republic":"🇨🇿",
    "Austria":"🇦🇹","Switzerland":"🇨🇭","Portugal":"🇵🇹",
}

rows_html = ""
for country in sorted_countries:
    country_events = by_country[country]
    flag = COUNTRY_FLAGS.get(country, "")
    country_display = f"{esc(country)} {flag}" if flag else esc(country)
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
  tr.row-closed {{ opacity: 0.6; }}
  tr.row-closed:hover {{ opacity: 1; }}
  .map-link {{ color: var(--text2); font-size: 0.82rem; white-space: nowrap; }}
  .ical-icon {{ color: var(--text2); text-decoration: none; margin-right: 6px; font-size: 0.78em;
    opacity: 0.55; cursor: pointer; display: inline-block; vertical-align: middle; white-space: nowrap; }}
  .ical-icon:hover {{ opacity: 1; color: var(--accent); }}
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
<h1>Upcoming SRA Matches</h1>
<div class="meta">Generated {now_str} &nbsp;·&nbsp; {len(events)} matches found</div>
<div class="toolbar">
  <div class="search-wrap"><input type="text" id="search" placeholder="Search matches or countries…" autocomplete="off"></div>
  <div class="filter-btns">
    <button class="active" data-filter="all">All</button>
    <button data-filter="open">Reg. Open</button>
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

  var sortCol = -1, sortAsc = true;
  var activeFilter    = 'all';
  var activeCountries = new Set();

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
  var FLAGS = {{
    'Sweden':'🇸🇪','Finland':'🇫🇮','Estonia':'🇪🇪','Norway':'🇳🇴','Denmark':'🇩🇰',
    'Latvia':'🇱🇻','Lithuania':'🇱🇹','Poland':'🇵🇱','Germany':'🇩🇪','Netherlands':'🇳🇱',
    'Belgium':'🇧🇪','France':'🇫🇷','Spain':'🇪🇸','Italy':'🇮🇹','United Kingdom':'🇬🇧',
    'United States':'🇺🇸','Canada':'🇨🇦','Australia':'🇦🇺','Czech Republic':'🇨🇿',
    'Austria':'🇦🇹','Switzerland':'🇨🇭','Portugal':'🇵🇹'
  }};
  function updateTrigger() {{
    var n = activeCountries.size;
    if (n === 0) {{ countryTrigger.textContent = 'All countries ▾'; }}
    else if (n === 1) {{
      var c = [...activeCountries][0];
      var f = FLAGS[c] || '';
      countryTrigger.textContent = (f ? f + ' ' : '') + c + ' ▾';
    }} else {{ countryTrigger.textContent = n + ' countries ▾'; }}
    countryTrigger.classList.toggle('active', n > 0);
  }}
  allGroups.forEach(function(group) {{
    var flag = FLAGS[group.label] || '';
    if (flag && !group.labelTr.cells[0].textContent.includes(flag)) {{
      group.labelTr.cells[0].textContent += ' ' + flag;
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
    lbl.appendChild(document.createTextNode(' ' + (flag ? flag + ' ' : '') + group.label));
    countryPanel.appendChild(lbl);
  }});
  countryTrigger.addEventListener('click', function(e) {{
    e.stopPropagation(); countryPanel.classList.toggle('open');
  }});
  document.addEventListener('click', function() {{ countryPanel.classList.remove('open'); }});
  countryPanel.addEventListener('click', function(e) {{ e.stopPropagation(); }});

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
