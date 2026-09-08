# Refactor Plan — BaroMe / nws_pressure_correction

**Status:** proposal only, nothing implemented.
**Drafted:** 2026-09-08

## 1. Goal

Turn the current 388-line interactive script into a small, testable library with two
thin front ends (CLI + web), and change the user contract to:

> The user types **one thing — their address**. The app returns the
> **elevation-adjusted local barometric pressure** (plus the derived Ctp).

Everything else — latitude/longitude, which weather station, the station's
elevation, the site's elevation — is resolved for them. Weather Underground is
the default source for all users, worldwide.

---

## 2. Review of the current code

### 2.1 Blocking issue for a webapp

Every calculation in [pressure_converter.py](pressure_converter.py) is welded to
`input()` and `print()`. There is no function that takes data and returns data —
`pressure()` ([pressure_converter.py:186-283](pressure_converter.py#L186-L283))
prompts, scrapes, computes, prints, and loops, all in one body. A Flask/Streamlit
view cannot call any of it. **This is the single change that unlocks everything
else:** separate computation from I/O.

### 2.2 Real bugs

| # | Where | Problem |
|---|---|---|
| 1 | [pressure_converter.py:283](pressure_converter.py#L283) | If the first attempt raises `IndexError` and the user then answers `n` to "change your lat/lon", `baro_lat_lon` was never bound → `UnboundLocalError` on the `return`. Crashes on the exact path a confused user takes. |
| 2 | [pressure_converter.py:270](pressure_converter.py#L270) | `except IndexError` only. A network failure (`URLError`), an HTTP 403/503 (`HTTPError`), or `pagesoup.find()` returning `None` (`AttributeError`, lines [128](pressure_converter.py#L128) and [137](pressure_converter.py#L137)) all escape and kill the program. The three most likely real-world failures are the three that are not handled. |
| 3 | [pressure_converter.py:367](pressure_converter.py#L367) | `if((not continue_to_inter_input) or (not continue_to_ctp_input))` — the second clause is unreachable; line [359](pressure_converter.py#L359) already broke out. |
| 4 | [pressure_converter.py:356-371](pressure_converter.py#L356-L371) | Answering `n` to the Ctp prompt `break`s past the "rerun the program?" prompt, so the program exits silently with no goodbye. The rerun loop only works if you say yes to everything. |
| 5 | [pressure_converter.py:154](pressure_converter.py#L154) | `nws_or_wunderground` reads the menu choice with `get_num_input` (a float reader) and compares against `int(1)`. Entering `1.5` prints "Please enter a valid input" and re-loops forever with no hint why. |
| 6 | [pressure_converter.py:64](pressure_converter.py#L64) | Bare `except:` swallows `KeyboardInterrupt` and `SystemExit` — Ctrl-C will not reliably quit the number prompt. |
| 7 | [requirements.txt](requirements.txt) | The file is **UTF-16 encoded** (that is why it displays as `b e a u t i f u l...`). `pip install -r` fails or misparses on most platforms. Must be rewritten as UTF-8. |
| 8 | [.gitignore](.gitignore) | Contains `\venv` — a Windows backslash with no trailing newline. It matches nothing. Should be `venv/` and `.venv/`. |
| 9 | [pressure_converter.py:296](pressure_converter.py#L296) | Local variable `ctp` shadows the enclosing function `ctp`. Harmless today, a trap the moment anyone adds recursion or a second call. |

### 2.3 Style / structure

- Six-space indentation throughout; not PEP 8, and it fights every editor and formatter.
- Stray semicolons ([lines 42-46](pressure_converter.py#L42-L46), [55](pressure_converter.py#L55)).
- `soup_check()` ([lines 75-97](pressure_converter.py#L75-L97)) is dead debug code shipped in the main module.
- [debug_get_pressure](debug_get_pressure) is an extensionless near-duplicate of the Weather Underground scraper. It will drift out of sync with the real one. Delete it — the history keeps it.
- No tests, no package layout, no linter config, no `pyproject.toml`.
- The `origin/address_entry` branch adds `from geopy.geocoders import Nominatim` and instantiates `Nominatim(user_agent="tutorial")` in `main()` but never calls it, and never adds `geopy` to requirements. Fold the intent in properly; discard the stub.

### 2.4 Domain / correctness issues — the ones worth caring about

These matter more than the style points, because the output feeds a Ctp correction.

**(a) The scraping approach is structurally fragile.**
Weather Underground's site is a client-rendered Angular app. The selectors in
`wunderground()` — `"test-false wu-unit wu-unit-pressure ng-star-inserted"`
([line 128](pressure_converter.py#L128)) and `"wx-data ng-star-inserted"`
([line 137](pressure_converter.py#L137)) — are framework-generated class names
that change on any WU frontend deploy, and `ng-star-inserted` in particular is an
Angular runtime artifact, not a stable API. **There is a documented JSON API that
returns exactly these values.** I verified it live — see §3.

**(b) The two providers pull two different elevations, and neither is quite right.**
The NWS path pulls the *forecast point's* elevation for the entered lat/lon
([lines 113-120](pressure_converter.py#L113-L120)). The WU path pulls the
*weather station's* elevation ([lines 137-143](pressure_converter.py#L137-L143)).
Those are different physical quantities, and the one the user actually wants is a
third: **the elevation at their own address**.

Measured, for the coordinates already hard-coded in the debug script (40.307, -75.148):

| Quantity | Value |
|---|---|
| Nearest WU station `KPADOYLE21` reported elevation | 380 ft |
| USGS elevation at the queried point | 325 ft |
| Difference | **55 ft → ~0.055 inHg → ~1.4 mmHg → ~0.18% in Ctp** |

For a clinic doing output constancy at the 1% level, a silent 0.2% bias from
using the wrong elevation is worth eliminating.

**(c) The pressure conversion is a rule of thumb, and its error is not negligible.**
[Line 249](pressure_converter.py#L249) uses `25.4 * (P_inHg − elev_ft/1000)` — the
"1 inHg per 1000 ft" approximation. Against the standard-atmosphere barometric
formula `P_station = P_msl · (1 − 0.0065·h/288.15)^5.25588`, starting from
29.92 inHg:

| Elevation (ft) | Linear (mmHg) | Barometric (mmHg) | Δ (mmHg) | Ctp error |
|---:|---:|---:|---:|---:|
| 0 | 759.97 | 759.97 | 0.00 | 0.00% |
| 500 | 747.27 | 746.34 | 0.93 | −0.12% |
| 1000 | 734.57 | 732.90 | 1.66 | −0.23% |
| 2000 | 709.17 | 706.63 | 2.54 | −0.36% |
| 3000 | 683.77 | 681.11 | 2.65 | −0.39% |
| 5000 | 632.97 | 632.33 | 0.64 | −0.10% |
| 7000 | 582.17 | 586.41 | −4.25 | +0.73% |

Fine near sea level, drifting to ~0.4% through the elevations where most of the
US actually lives, and reversing sign above ~6000 ft. Recommendation: compute
with the barometric formula, and keep the linear result available as a labelled
cross-check so historical numbers stay reproducible.

**(d) Ctp reference temperature — a question, not a defect.**
[Line 296](pressure_converter.py#L296) uses 20.0 °C and 760.0 mmHg. That matches
**IAEA TRS-398**. **AAPM TG-51** references 22 °C. The code hard-codes one
convention with no label. This should become a named, selectable constant with the
protocol shown in the output, so a user cannot misread which one they got.
*Flagging for your call — I am not assuming which protocol the clinic runs.*

---

## 3. Data sources — verified live, 2026-09-08

I probed each of these rather than assuming. Results:

| Purpose | Endpoint | Verified | Key? | CORS |
|---|---|---|---|---|
| Nearest WU station | `api.weather.com/v3/location/near?product=pws` | yes — returns 10 nearest PWS with id, name, lat/lon, `qcStatus`, `updateTimeUtc` | yes | `*` |
| Current observation | `api.weather.com/v2/pws/observations/current` | yes — returns `imperial.pressure` (inHg, sea-level adjusted) and `imperial.elev` (station ft), plus `obsTimeUtc`, `neighborhood`, `qcStatus` | yes | `*` |
| Elevation (US) | `epqs.nationalmap.gov/v1/json` | yes — returned 325.33 ft for the test point | no | `*` |
| Geocode (US) | `geocoding.geo.census.gov/.../onelineaddress` | yes — exact street-address match | no | none (JSONP only) |
| Forecast / fallback | `api.weather.gov` | yes — reachable | no | — |

Sample observation payload (station `KPADOYLE21`, live):
`pressure = 30.28` inHg, `elev = 380` ft, `qcStatus = 1`, `neighborhood = "Doylestown Boro Fairgrounds"`.
This confirms your read that WU reports **sea-level-adjusted** pressure — 30.28 inHg
at 380 ft is only plausible as an altimeter setting, not a station reading.

**Two things I could not verify from this network** — its TLS proxy blocks those
hosts, which is not evidence they are broken: `nominatim.openstreetmap.org`,
`api.open-meteo.com`, and `wunderground.com` itself. Confirm from the deploy target.

**One negative result worth recording:** WU's own `v3/location/search` is a
*place* search, not a street geocoder. Querying "1600 Pennsylvania Ave NW
Washington DC" returned "North Washington, Apollo, Pennsylvania". **We cannot
geocode addresses with the WU key alone** — a separate geocoder is required.

### 3.1 The API key question — needs your decision

The working key I used (`e1f10a1e...`) is the one Weather Underground's *own
website* embeds in its JavaScript. It works, and it is already public, but:

- Using it from a server is a grey area under WU's terms.
- It can rotate without notice, or get IP-rate-limited.

Options, in the order I would suggest considering them:

1. **Register a free WU PWS API key.** Clean and supported — but WU grants these
   to people who *contribute* a personal weather station. If the clinic does not
   run one, this is a barrier.
2. **Ship WU as the default (as you asked), key injected via a `WU_API_KEY`
   environment variable**, defaulting to the public one, with a documented
   fallback provider if it starts failing.
3. **Make the provider pluggable** so Open-Meteo (no key, worldwide, no ToS
   friction) or NWS can take over automatically on failure.

The plan below assumes **2 + 3**: WU is the default everywhere, the key is
configurable, and the abstraction makes a fallback a config change rather than a
rewrite.

---

## 4. Target architecture

```
nws_pressure_correction/
├── src/barome/
│   ├── __init__.py
│   ├── config.py          # API key(s), reference T/P, unit factors, HTTP timeouts
│   ├── models.py          # frozen dataclasses: Location, Station, Observation, PressureResult
│   ├── geocode.py         # address str          -> Location
│   ├── elevation.py       # lat, lon             -> elevation_ft + source
│   ├── physics.py         # PURE. no network, no I/O. fully unit-tested.
│   ├── providers/
│   │   ├── base.py          # Protocol: nearest_station(), current_observation()
│   │   ├── wunderground.py  # DEFAULT
│   │   ├── nws.py           # fallback, US only
│   │   └── openmeteo.py     # fallback, worldwide, keyless
│   └── service.py         # pressure_for_address(addr) -> PressureResult  <-- the seam
├── cli.py                 # thin; keeps today's interactive flow working
├── web/app.py             # thin; Streamlit or Flask
├── tests/
├── pyproject.toml
└── plan.md
```

**The one contract both front ends call:**

```python
def pressure_for_address(
    address: str,
    *,
    provider: str = "wunderground",
    method: Method = Method.BAROMETRIC,
) -> PressureResult: ...
```

```python
@dataclass(frozen=True)
class PressureResult:
    # what the user typed, and what we decided it meant
    address_query: str
    resolved_address: str
    lat: float
    lon: float
    # which station, and how far away — always shown, never hidden
    station_id: str
    station_name: str
    station_distance_mi: float
    station_elev_ft: float
    obs_time_utc: datetime
    obs_age_minutes: float
    # the site's own elevation, and where that number came from
    site_elev_ft: float
    elev_source: str
    # the numbers
    pressure_msl_inhg: float
    pressure_station_mmhg: float
    pressure_station_inhg: float
    pressure_station_hpa: float
    pressure_station_kpa: float
    pressure_station_pa: float
    method: Method
    # provenance and honesty
    source_urls: dict[str, str]
    warnings: list[str]
```

`warnings` carries the things a user must not miss: station is 14 miles away,
observation is 3 hours stale, `qcStatus` is −1, elevation fell back to the
station's because the address is outside the US DEM, and so on. The existing code
prints the source URL "for the user to verify" — keep that instinct, and make it
structured.

---

## 5. Phased work

Each phase leaves the repo working. No phase requires the next.

**Phase 0 — hygiene** *(~30 min)*
Rewrite `requirements.txt` as UTF-8; fix `.gitignore` (`venv/`, `.venv/`,
`__pycache__/`, `.env`); delete `debug_get_pressure`; add `pyproject.toml` and a
`ruff` config; reindent to 4 spaces.

**Phase 1 — extract the pure core** *(~2 h)*
Move the math into `physics.py` as pure functions: `msl_to_station_pressure()`
(both methods), `convert_pressure_units()`, `ctp()`, `intercomparison()`.
Write tests **first** against today's outputs so the refactor is provably
behaviour-preserving, then add the barometric-formula cases from §2.4(c) as the
new expected values. Fixes bug #9. No network code moves yet.

**Phase 2 — replace scraping with APIs** *(~3 h)*
Build `providers/wunderground.py` on the two verified endpoints. Add
`geocode.py` (Nominatim primary for worldwide coverage, US Census for exact US
street matches) and `elevation.py` (USGS for the US, Open-Meteo elsewhere).
Retire the BeautifulSoup selectors and `soup_check()`. Drop `bs4` / `soupsieve`
from requirements. Fixes bug #2 and the fragility in §2.4(a).

**Phase 3 — the service seam** *(~1 h)*
Write `service.py` implementing the contract above, including the elevation
correctness fix from §2.4(b): use the *address's* elevation, not the station's,
and warn when falling back. Rewrite `cli.py` as a thin caller — one address
prompt, not two coordinate prompts. Fixes bugs #1, #3, #4, #5.

**Phase 4 — the web app** *(~3 h)*
One text input, one button, one results card: the corrected pressure large and
first, then the unit table, then a collapsible "how we got this" panel showing
the resolved address, station name and distance, observation timestamp, both
elevations, and the source links. Optional second panel for Ctp (temperature
input) and intercomparison, preserving today's features.

**Phase 5 — deploy** *(~1 h)* — see §6.

**Later, optional:** cache observations for ~5 min per station — WU updates every
few minutes, so there is no reason to re-hit the API on every reload; let the user
override the auto-picked station from the nearest-10 list; log nothing that
identifies a patient or a site.

---

## 6. Free hosting options

| Option | Cost | Cold start | Keeps Python? | Notes |
|---|---|---|---|---|
| **Streamlit Community Cloud** ← recommended | free | ~30-60 s after idle | yes | Deploys straight from this GitHub repo on push. One codebase serves CLI and web. Secrets UI for `WU_API_KEY`. Least work by a wide margin. |
| Hugging Face Spaces | free | ~20-40 s | yes | Streamlit or Gradio. Equivalent to the above; pick on preference. |
| **Static page on GitHub Pages** | free | **none** | no — rewrite in JS | Genuinely viable: I confirmed `api.weather.com` and USGS both send `Access-Control-Allow-Origin: *`, so a browser can call them directly with no backend at all. Zero maintenance, never sleeps. Cost: the logic lives in JS and diverges from the Python. |
| Render / Fly.io free tier | free | ~50 s | yes | Real Flask app. More control, more config, and free tiers keep changing. |
| PythonAnywhere free | free | none | yes | Always-on, but the free tier's outbound allowlist would need checking against `api.weather.com`. |

**Recommendation: Streamlit Community Cloud.** For a clinic checking pressure a
few times a day, a 40-second wake is a non-issue, and it keeps one Python
codebase that the CLI also uses. If the cold start turns out to annoy people, the
static GitHub Pages route is the escape hatch — and §4's clean separation means
only the thin layer gets rewritten, not the logic.

---

## 7. Decisions needed before implementation

1. **Ctp reference temperature** — 20 °C (TRS-398, what the code does now) or
   22 °C (TG-51)? Or selectable, defaulting to which?
2. **Pressure formula** — switch the default to the barometric formula, or keep
   the linear one as default for continuity with historical records?
3. **WU API key** — is there a personal weather station available to get a free
   official key, or ship with the public one plus an env-var override?
4. **Scope of the web app** — address-and-pressure only, or carry Ctp and
   intercomparison across too? This plan assumes all three, with the latter two
   collapsed by default.
5. **Keep the NWS provider?** It is now redundant for the default flow, but it is
   a useful independent cross-check and a fallback if the WU key dies.

## 8. Explicitly out of scope

Accounts / auth, storing results, mobile apps, patient data of any kind, and any
claim of medical-device or regulatory status. This stays a convenience calculator
whose sources are always shown so the user can verify them — which is the right
instinct the current program already has.
