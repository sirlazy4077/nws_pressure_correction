# Refactor Plan — BaroMe / nws_pressure_correction

**Status:** proposal only, nothing implemented.
**Drafted:** 2026-09-08 · **Revised:** 2026-09-08 (geocoding, elevation,
barometric formula, Ctp toggle defaulting to TG-51)
**Revised:** 2026-09-08 (protocol auto-selection by country, calculation trace)
**Revised:** 2026-09-09 (WU public key primary, Open-Meteo + NWS fallbacks, panel layout)
**Revised:** 2026-09-09 (panel 3 intercomparison against a local instrument)
**Revised:** 2026-09-09 (panel 3 reports Ctp difference only; input validation for bug #10)

## 1. Goal

Turn the current 388-line interactive script into a small, testable library with two
thin front ends (CLI + web), and change the user contract to:

> The user types **one thing — their address**. The app returns the
> **elevation-adjusted local barometric pressure** (plus the derived Ctp).

Everything else — latitude/longitude, which weather station, the station's
elevation, the site's elevation — is resolved for them. Weather Underground is
the default source for all users, worldwide.

The **Ctp reference protocol** is auto-selected from the same address — US
addresses get **AAPM TG-51 (22 °C)**, everywhere else gets **IAEA TRS-398
(20 °C)** — and stays overridable by hand at any time (§5.4). So it costs the
user no extra input, but it is never silent: which protocol was used, and
whether it was chosen automatically or by hand, is stated on every result.

A third panel compares that result against the clinic's own barometer and
thermometer, and reports the one difference that matters — in Ctp (§5.7).

And because a number a physicist cannot check is a number they should not trust,
the tool **shows its whole chain of reasoning** (§5.5): the address as entered
and as resolved, the coordinates, the elevation and its source, the station and
its distance, and every formula with its actual values substituted in — all with
links back to the sources.

**Sources.** Weather Underground is the primary provider for everyone, reached
through the public key its own site uses (§3.1). Because that key carries no
guarantee, two keyless fallbacks ship alongside it from day one: **Open-Meteo**
worldwide, and **NWS** for US addresses. Whichever answers is named on the
result.

**New runtime dependency:** `geopy` (for Nominatim and Photon geocoding).
`beautifulsoup4` / `soupsieve` are *removed* — the scraping they supported is
replaced by JSON APIs. Net dependency count goes down.

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
| 10 | [pressure_converter.py:323](pressure_converter.py#L323) | `intercomp_temps_percent` divides by `temp_round` — an uncaught `ZeroDivisionError` at exactly 0 °C, unbounded near it. The quantity is also unsound in itself (a percentage of an interval scale). Two further division-by-zero paths reachable from user input, `P = 0` and `T = −273.2 °C`, are fixed at the same time. All three addressed by input validation in §5.7. |

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
US actually lives, and reversing sign above ~6000 ft.

**DECIDED — the linear rule of thumb is dropped as the default.** The barometric
formula (the "Barometric" column above) becomes the sole computation path. The
linear value will still be computed and shown in the detail panel, clearly
labelled *"legacy 1 inHg/1000 ft approximation"*, so numbers in existing records
remain reproducible and the two can be eyeballed against each other. See
[§5.3](#53-pressure-correction) for the implementation.

**CONFIRMED:** "the table method" means the **standard-atmosphere barometric
formula** — the one that produced the correct column above — not a published
lookup chart. That is the calculation to implement:

```
P_station = P_msl · (1 − L·h / T₀) ^ (g·M / (R·L))
          = P_msl · (1 − 0.0065·h / 288.15) ^ 5.25588
```

with `h` in metres, `L` = 0.0065 K/m (tropospheric lapse rate), `T₀` = 288.15 K
(ISA sea-level temperature), and the exponent 5.25588 following from standard
gravity, the molar mass of dry air, and the universal gas constant.

**(d) Ctp reference temperature — resolved into a user-facing toggle,
defaulting to TG-51.**
[Line 296](pressure_converter.py#L296) hard-codes 20.0 °C and 760.0 mmHg with no
label. That matches **IAEA TRS-398**; **AAPM TG-51** references 22 °C. Both ship,
selectable, with **TG-51 (22 °C) as the default** — this is a US clinic, and
TG-51 is the US standard, while TRS-398 is the international one. Design in
[§5.4](#54-ctp-reference-protocol-toggle).

⚠️ **This changes current behaviour.** Today's script always computes at 20 °C.
Because the two protocols differ only by a constant ratio of reference
temperatures, switching the default shifts *every* Ctp by exactly
`(273.2+20)/(273.2+22) − 1` = **−0.6775%**, uniformly, regardless of the measured
temperature or pressure. That is a real step change against historical records,
not rounding — it needs to be called out in the release notes and visible in the
UI, which is what §5.4's always-restate-the-protocol rule is for.

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

**One negative result worth recording:** WU's own `v3/location/search` is a
*place* search, not a street geocoder. Querying "1600 Pennsylvania Ave NW
Washington DC" returned "North Washington, Apollo, Pennsylvania". **We cannot
geocode addresses with the WU key alone** — a separate geocoder is required.
That investigation is §3.2; elevation is §3.3.

*Verification note:* this workstation sits behind a TLS-intercepting proxy whose
certificate chain Python's bundled CA store rejects. Everything below was
therefore verified through PowerShell, which validates against the Windows
certificate store and reaches these hosts correctly. All results are live
responses, not assumptions — but re-confirm reachability from whatever host you
finally deploy to.

### 3.1 The WU API key — DECIDED (options 2 + 3)

WU's API is not publicly available: the free PWS key requires *contributing* a
personal weather station, which the clinic does not have. Option 1 is therefore
off the table, and the public-key route becomes the primary method rather than a
convenience.

**Adopted: options 2 + 3 together.**

- **(2) The public key is primary.** `e1f10a1e...` — the key Weather
  Underground's own website embeds in its JavaScript — is what ships, injected
  via a `WU_API_KEY` environment variable so a real key can replace it later
  without a code change.
- **(3) Providers are pluggable, with automatic fallback.** Because the primary
  route depends on a key that can rotate or be IP-rate-limited without notice,
  the fallbacks are not a nice-to-have — they are what keeps the tool working on
  the day the key stops. They must be built in the same phase, not deferred.

The honest framing for the README: this is the same request the WU website makes
from a browser. It works today; it carries no uptime guarantee; the tool degrades
to a keyless source rather than failing when it stops.

### 3.1.1 Provider chain — all three verified live

| # | Provider | Coverage | Key? | Returns | Verified |
|---|---|---|---|---|---|
| 1 | **Weather Underground PWS** | worldwide | public key | sea-level pressure, station elev, `qcStatus` | ✅ §3 |
| 2 | **Open-Meteo** | worldwide | **none** | `pressure_msl` + `surface_pressure` + grid elevation | ✅ below |
| 3 | **NWS** | US only | **none** | altimeter setting (see the trap below) | ✅ below |

**The unifying abstraction: every provider's only job is to return `P_msl`.**
The elevation correction is provider-independent and happens once, in
`physics.py`, against the user's own elevation. This keeps the §5.5 trace
identical in shape no matter which source answered, and means adding a fourth
provider later never touches the maths.

**Open-Meteo** (`api.open-meteo.com/v1/forecast`) returns, in a single keyless
request: `pressure_msl`, `surface_pressure`, **and** the grid elevation. Live at
the test point: `pressure_msl = 1022.6 hPa`, `surface_pressure = 1010.8 hPa`,
`elevation = 99.0 m`. Because it also serves the elevation API from §3.3, it
covers **both** halves of the fallback in one dependency, worldwide, with no key
and no ToS friction. That makes it the first fallback for everyone.

> **A useful accident:** passing `&elevation=<metres>` makes Open-Meteo
> recompute `surface_pressure` for *that* elevation. So it will do our
> correction for us — which gives an independent check on §5.3's formula. At
> 99 m our formula lands within **0.014%** of theirs; at 325 m, within
> **0.060%** (0.44 mmHg). Two independent implementations agreeing to under a
> tenth of a percent is good evidence the formula is right. We still use *our*
> formula as the single correction path so the trace reads the same for every
> provider — but the Open-Meteo value is worth keeping as a regression test.

**NWS** (`api.weather.gov`): `/points/{lat},{lon}` → `observationStations` →
`/stations/{id}/observations/latest`.

⚠️ **A trap worth the whole investigation.** The field named
`barometricPressure` is **not station pressure** despite its name — it is the
**altimeter setting**, i.e. already sea-level adjusted. Verified by checking
high-elevation stations, where the two readings cannot be confused:

| Station | Elevation | `barometricPressure` | If read as station pressure → implied MSL |
|---|---:|---:|---|
| KJFK | 3 m | 1024.04 hPa | 1024 hPa — ambiguous at sea level |
| KDYL | 120 m | 1023.71 hPa | 1038 hPa — suspicious |
| KABQ | 1631 m | 1026.41 hPa | **1250 hPa — impossible** |
| KLXV (Leadville) | 3026 m | 1037.93 hPa | **1505 hPa — impossible** |

Taken literally at Leadville the error is **+47%**. Read correctly as an
altimeter setting it implies a station pressure of 715.8 hPa, which is right for
3000 m. A sea-level-only test would never have caught this, which is why the
high-elevation check was worth doing.

Two more NWS facts that shape the implementation:

- **`seaLevelPressure` was `null` at all four stations tested** (`qualityControl:
  "Z"`). It cannot be relied on; use `barometricPressure` and treat it as MSL.
- **KDEN returned no `barometricPressure` at all.** Null readings are normal, so
  the provider must walk down the `observationStations` list rather than trusting
  the first entry, and honour the `qualityControl` flag (`"V"` = validated).

**Cross-validation.** Normalised to MSL and corrected to the same user point,
NWS and Open-Meteo agree to **0.109%** (0.82 mmHg, ~0.11% in Ctp) — comfortably
inside the noise this tool is trying to remove, and a good routine sanity check
once both are built.

**Fallback policy.** WU → Open-Meteo → NWS (US only). Falling back is never
silent: it raises a `warning` on the result and is written into the §5.5 trace,
so a user always knows which source produced their number and that the preferred
one was unavailable.

### 3.2 Geocoder — address to lat/lon

All four candidates are free and keyless. Tested with
`1600 Pennsylvania Ave NW, Washington, DC 20500`:

| Service | Result | Coverage | Key? | Python lib | Verdict |
|---|---|---|---|---|---|
| **US Census** | exact street match | US only | no | none — 15-line custom adapter | ✅ primary for US |
| **Nominatim** (OSM) | 38.8976, −77.0366 "White House" | worldwide | no | **`geopy` built-in** | ✅ primary worldwide |
| **Photon** (Komoot) | 38.8978, −77.0366, structured fields | worldwide | no | **`geopy` built-in** | ✅ fallback |
| Maps.co / LocationIQ / OpenCage | — | worldwide | **yes, signup** | varies | ✗ rejected: key required |

Photon on non-US addresses, verified live:

- `Rua Augusta 100, Lisboa, Portugal` → 38.7101, −9.1374
- `1 Chome-1 Oshiage, Sumida City, Tokyo, Japan` → 35.7103, 139.8134

**Library decision.** I checked geopy's actual `__all__` rather than assuming:
it ships `Nominatim` and `Photon` as first-class geocoders (alongside ~30 others,
mostly key-required commercial ones). It does **not** ship a US Census geocoder —
that one is a short custom function against a plain JSON endpoint. Rate limiting
for Nominatim's 1-request/second policy comes from
`geopy.extra.rate_limiter.RateLimiter` (note: that lives in `geopy.extra`, not in
`geopy.geocoders`).

So: **`geopy` covers two of the three, and the third is ~15 lines of custom code.**
No GitHub-sourced or hand-rolled geocoding engine is needed.

**Chain, in order.** US Census → Nominatim → Photon. Census goes first because
for US addresses it gives a true rooftop/street-interpolated match with no rate
limit and no usage policy to honour; Nominatim and Photon then provide worldwide
coverage. Each is tried until one returns a result; `Location.source` records
which one answered so the user can see it.

**Nominatim usage policy** (must be respected or the clinic's IP gets blocked):
max 1 request/second, a genuine identifying `User-Agent` (this project will send
`barome/<version> (<contact email>)`), and no bulk querying. All three are
satisfied by a clinic looking up an address a few times a day, and the caching in
§5.2 makes repeat lookups free.

### 3.3 Elevation — lat/lon to the address's own elevation

Five free keyless sources, all verified live at 40.307, −75.148:

| Source | Reading | Dataset / resolution | Coverage | CORS |
|---|---:|---|---|---|
| Open-Meteo | 324.80 ft | Copernicus GLO-90 | worldwide | yes |
| **USGS EPQS** | **325.33 ft** | NED, 1 m | US only | `*` |
| OpenTopoData `ned10m` | 325.39 ft | NED, 10 m | US only | yes |
| Open-Elevation | 331.36 ft | SRTM 30 m | worldwide | yes |
| OpenTopoData `srtm30m` | 334.65 ft | SRTM, 30 m | worldwide | yes |
| OpenTopoData `aster30m` | 337.93 ft | ASTER, 30 m | worldwide | yes |

**The important result: total spread across all six is 13.1 ft.** That is
0.013 inHg → 0.33 mmHg → **0.044% in Ctp**. Which elevation service you pick is
effectively irrelevant at the precision that matters here.

That reframes §2.4(b) usefully: the 55 ft station-vs-address error is **four
times larger than the entire disagreement between every available elevation
dataset**. Fixing *which point* we ask about matters; agonising over *which
service* answers does not.

**Chain, in order.** USGS EPQS → Open-Meteo → OpenTopoData. USGS first for its
1 m US resolution and `*` CORS (which keeps the static-hosting option in §6
open); Open-Meteo as the worldwide default because it is fast, keyless and
unmetered; OpenTopoData last as it caps public use at 1000 calls/day and
1 call/second. `elev_source` on the result records which answered.

**Python libraries considered and rejected.** `elevation` and `SRTM.py` both work
by downloading multi-megabyte SRTM tiles and reading them locally. That buys
offline capability the clinic does not need, at the cost of large downloads, GDAL
dependencies, and 30 m data that is *worse* than the 1 m USGS figure. A plain
HTTP call is the better engineering here — no library required.

---

## 4. Target architecture

```
nws_pressure_correction/
├── src/barome/
│   ├── __init__.py
│   ├── config.py          # API key(s), Ctp protocol default, unit factors, timeouts
│   ├── models.py          # frozen dataclasses: Location, Station, Observation, PressureResult
│   ├── geocode.py         # address str -> Location   (Census -> Nominatim -> Photon)
│   ├── elevation.py       # lat, lon    -> elevation_ft + source  (USGS -> Open-Meteo -> OpenTopo)
│   ├── physics.py         # PURE. no network, no I/O. fully unit-tested.
│   ├── providers/
│   │   ├── base.py          # Protocol: every provider returns P_msl + metadata
│   │   ├── wunderground.py  # PRIMARY   - public key, worldwide
│   │   ├── openmeteo.py     # FALLBACK 1 - keyless, worldwide, also serves elevation
│   │   └── nws.py           # FALLBACK 2 - keyless, US only, altimeter-setting quirk
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
    country_code: str | None   # drives the §5.4 protocol auto-selection
    geocoder: str              # which of the chain answered
    # where the pressure came from — always shown, never hidden
    provider: str              # "wunderground" | "openmeteo" | "nws"
    provider_fallback: bool    # True if the primary was unavailable
    station_id: str | None     # None for Open-Meteo, which is a model grid not a station
    station_name: str | None
    station_distance_mi: float | None
    station_elev_ft: float | None   # displayed, but NOT used in the correction
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
    pressure_station_mmhg_linear: float   # legacy cross-check, §5.3
    method: Method
    # Ctp protocol: suggested here, applied in the Ctp panel (§5.4)
    suggested_ctp_protocol: CtpProtocol   # from country_code; the panel-2 default
    suggested_ctp_reason: str             # human-readable, displayed in panel 2
    # provenance and honesty (§5.5)
    trace: list[TraceStep]
    source_urls: dict[str, str]
    warnings: list[str]
```

Note that `PressureResult` deliberately holds no Ctp *value*, and only a
*suggested* protocol. Ctp depends on a temperature the user supplies afterwards
and on a protocol they can flip at any time, so both live in the Ctp panel
(§5.4). Keeping them out of this dataclass is what lets panel 1 stand alone as
"the pressure at this address" and lets the panel-2 override recompute from
cached values instead of re-running the whole chain.

A second `CtpResult` dataclass carries what panel 2 produces —
`ctp`, `temperature_c`, `protocol`, `protocol_source`
(`"auto"` | `"manual"` | `"env"`), `protocol_reason`, and its own trace steps.

`warnings` carries the things a user must not miss: station is 14 miles away,
observation is 3 hours stale, `qcStatus` is −1, elevation fell back to the
station's because the address is outside the US DEM, and so on. The existing code
prints the source URL "for the user to verify" — keep that instinct, and make it
structured.

---

## 5. Implementation detail for the new components

### 5.1 `geocode.py`

```python
GEOCODER_CHAIN = ("census", "nominatim", "photon")

@dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    display_name: str     # what we echo back so the user can confirm the match
    source: str           # "census" | "nominatim" | "photon"
    confidence: str        # "exact" | "interpolated" | "approximate"

def geocode(address: str, chain=GEOCODER_CHAIN) -> Location:
    """First geocoder in the chain that returns a hit, wins.
    Raises GeocodingError only if every provider fails or returns nothing."""
```

- **Census** (`_geocode_census`): a plain `GET` on
  `geocoding.geo.census.gov/geocoder/locations/onelineaddress` with
  `benchmark=2020&format=json`, reading `result.addressMatches[0].coordinates`.
  ~15 lines, no dependency. Skipped immediately if the address has a non-US
  country hint.
- **Nominatim / Photon**: `geopy.geocoders.Nominatim` and `.Photon`, both wrapped
  in `geopy.extra.rate_limiter.RateLimiter(min_delay_seconds=1)` and constructed
  with the identifying `user_agent` string from §3.2.

**Always echo the match back.** `display_name` goes in the results panel, because
a geocoder that silently resolves a typo'd address to somewhere 40 miles away is
the most likely way this tool produces a confidently wrong number. If
`confidence` is `approximate`, that becomes a `warning` on the result.

### 5.2 `elevation.py`

```python
ELEVATION_CHAIN = ("usgs", "openmeteo", "opentopodata")

def elevation_ft(lat: float, lon: float, chain=ELEVATION_CHAIN) -> tuple[float, str]:
    """Returns (feet, source_name). USGS returns feet directly via units=Feet;
    the other two return metres and are converted (x 3.28084)."""
```

Each is a single JSON `GET`, parsed as: USGS `.value`; Open-Meteo `.elevation[0]`;
OpenTopoData `.results[0].elevation`. USGS returns a sentinel of `-1000000` for
off-grid points — treat that as a miss and fall through, which is what makes the
chain work for non-US addresses without a country check.

**Caching.** One `functools.lru_cache` on `(round(lat,4), round(lon,4))`.
A clinic re-checks the same address all day; its elevation does not change. This
also keeps Nominatim's rate policy comfortably satisfied. Weather observations
get a separate short TTL cache (~5 min) since those *do* change.

### 5.3 Pressure correction

Per the decision in §2.4(c), `physics.py` implements both, with barometric as the
default and the only value shown as *the* answer:

```python
class Method(StrEnum):
    BAROMETRIC = "barometric"   # DEFAULT
    LINEAR     = "linear"       # legacy, shown as cross-check only

def msl_to_station_pressure(p_msl_inhg: float, elev_ft: float,
                            method: Method = Method.BAROMETRIC) -> float:
    if method is Method.BAROMETRIC:
        h = elev_ft * 0.3048                       # ft -> m
        return p_msl_inhg * (1 - 0.0065 * h / 288.15) ** 5.25588
    return p_msl_inhg - elev_ft / 1000.0           # legacy 1 inHg/1000 ft
```

Constants (`0.0065` K/m lapse rate, `288.15` K sea-level standard temperature,
exponent `5.25588`) become named module constants, not literals. The unit
conversions currently inlined at
[pressure_converter.py:259-267](pressure_converter.py#L259-L267) move into a
single `convert_pressure_units()` returning a dict, with `0.03937` replaced by
the exact `1/25.4`.

Tests assert the §2.4(c) table row by row — that table becomes the fixture.

### 5.4 Ctp reference protocol toggle

```python
class CtpProtocol(StrEnum):
    TG_51   = "TG-51"     # 22.0 C, 101.325 kPa   <- DEFAULT (AAPM, US standard)
    TRS_398 = "TRS-398"   # 20.0 C, 101.325 kPa      (IAEA, international)

REFERENCE_TEMP_C = {CtpProtocol.TG_51: 22.0, CtpProtocol.TRS_398: 20.0}
DEFAULT_CTP_PROTOCOL = CtpProtocol.TG_51

def ctp(temp_c: float, pressure_mmhg: float,
        protocol: CtpProtocol = DEFAULT_CTP_PROTOCOL) -> float:
    t_ref = REFERENCE_TEMP_C[protocol]
    return ((273.2 + temp_c) / (273.2 + t_ref)) * (REFERENCE_PRESSURE_MMHG / pressure_mmhg)
```

**The default is selected automatically from the resolved address**, then
overridable by hand. US → TG-51 (22 °C); everywhere else → TRS-398 (20 °C).

```python
US_CODES = {"US", "PR", "GU", "VI", "AS", "MP"}   # defensive; see note below

def auto_protocol(country_code: str | None) -> tuple[CtpProtocol, str]:
    """Returns (protocol, human-readable reason). The reason is displayed, always."""
    if not country_code:
        return CtpProtocol.TG_51, "country could not be resolved — defaulted to US standard"
    cc = country_code.upper()
    if cc in US_CODES:
        return CtpProtocol.TG_51, f"address resolved to {cc} → AAPM TG-51 (US standard)"
    return CtpProtocol.TRS_398, f"address resolved to {cc} → IAEA TRS-398 (international standard)"
```

**The country code is already free** — every geocoder in the §3.2 chain supplies
it, verified live:

| Geocoder | Field | Format |
|---|---|---|
| Census | — | US-only by construction; implies `US` |
| Nominatim | `address.country_code` (needs `addressdetails=1`) | **lowercase** — `us` |
| Photon | `properties.countrycode` | **uppercase** — `US` |

Note the case mismatch between the two: normalise with `.upper()` before
comparing, or this silently misroutes every Nominatim-resolved address to
TRS-398. That is exactly the class of bug this plan exists to prevent, so it gets
a test.

I also checked the US territories, since they are the obvious edge case:
Guam, USVI, American Samoa, the Northern Marianas and Puerto Rico **all return
`US`** from Photon rather than their own ISO codes. So `US_CODES` above is
belt-and-braces against a geocoder that behaves differently, not a live
dependency — but it costs nothing and it is the difference between a clinic in
San Juan getting TG-51 and getting a silently wrong protocol.

**Manual override, after the calculation.** The auto-selection is a starting
point, never a lock. Because `ctp()` is pure and both the temperature and the
corrected pressure are already known by then, flipping the protocol recomputes
**instantly and locally — no re-geocode, no new network call**. The user can
toggle back and forth and watch the number move.

The displayed state always says which of the two it is in:

- `Protocol: TG-51 (22 °C) — auto-selected: address resolved to US`
- `Protocol: TRS-398 (20 °C) — manually overridden (auto-selection was TG-51)`

`PressureResult` carries both `ctp_protocol` and `ctp_protocol_source`
(`"auto"` | `"manual"` | `"env"`), plus the reason string, so the provenance
survives into the §5.5 trace and any exported record.

**Precedence:** explicit user override > `BAROME_CTP_PROTOCOL` env var (a site
pinning its house standard) > auto-selection from country. An env-var pin
suppresses auto-selection and says so in the display, so a physicist never
wonders why the toggle "isn't working".

Note this is a **deliberate change from current behaviour**, which is
unconditionally 20 °C: see the −0.6775% shift documented in §2.4(d). It is the
one place in this refactor where output moves for a reason other than a bug fix,
so it should be the loudest line in the release notes.

Surfaced in both front ends:

- **Web — in the Ctp panel only (panel 2), not the pressure panel.** A two-option
  radio directly above the Ctp result: `(•) 22 °C — AAPM TG-51` /
  `( ) 20 °C — IAEA TRS-398`, pre-selected from `suggested_ctp_protocol` and
  annotated with its reason. Changing it re-renders from cached values.
  Selection persists in session state.
- **CLI:** `--protocol {tg-51,trs-398}` overrides; omitted, it auto-selects and
  prints the reason.
- **Config:** `BAROME_CTP_PROTOCOL` pins a site's house standard.

**Panel placement.** The toggle belongs with the Ctp calculation because it only
affects Ctp — it has no bearing whatsoever on the corrected pressure. Putting it
in panel 1 would imply the pressure depends on the protocol, which it does not,
and would clutter the one answer most users came for. Panel 1 is the pressure at
your address, full stop; panel 2 is where a clinical convention gets chosen, next
to the number it changes. See §5.6 for the full layout.

The protocol appears in every rendering, never as a bare number. The failure mode
being designed out is a physicist reading a Ctp without knowing which reference
produced it — and at a uniform 0.6775%, that ambiguity is larger than the
elevation error this whole refactor exists to fix.

### 5.5 "Show your work" — the calculation trace

Every number the tool reports must be traceable to its inputs without reading the
source. This is the feature that makes the output checkable rather than trusted,
which matters more here than anywhere else in the design: the current script's
one genuinely good instinct is printing the source URL so the user can verify it,
and this generalises that instinct to the whole chain.

**Data model.** Each stage appends a step; the result carries the list.

```python
@dataclass(frozen=True)
class TraceStep:
    stage: str              # "geocode" | "elevation" | "station" | "observation"
                            # | "correction" | "units" | "ctp"
    provider: str           # which service actually answered
    inputs: dict[str, Any]
    output: dict[str, Any]
    expression: str | None  # the formula with real numbers substituted in
    url: str | None         # the exact request, so the user can click it
    note: str | None        # e.g. "census returned no match — fell through to nominatim"
```

**Rendering.** A panel, expanded by default in the web app and printed in full by
the CLI, reading top to bottom as the calculation actually ran. With live values
from the verified test point:

```
1. ADDRESS
   You entered : 123 Main St, Doylestown, PA 18901
   Resolved to : Doylestown, Bucks County, Pennsylvania, 18901, United States
   Geocoder    : US Census (exact street match)
   Coordinates : 40.30700, -75.14800
   Country     : US   (suggests AAPM TG-51 in the Ctp panel - see step 7)
   [verify]      https://geocoding.geo.census.gov/geocoder/...

2. YOUR ELEVATION  (at your address, not the station's)
   Elevation   : 325.33 ft  (99.16 m)
   Source      : USGS EPQS, NED 1 m dataset
   [verify]      https://epqs.nationalmap.gov/v1/json?x=-75.148&y=40.307...

3. PRESSURE SOURCE
   Provider    : Weather Underground  (primary)
   Station     : KPADOYLE21 "Doylestown Boro Fairgrounds"
   Distance    : 0.7 mi from your address
   Station elev: 380 ft   (not used in the calculation - shown for comparison)
   Observed    : 2026-09-08 13:00 local  (14 minutes ago)
   Quality     : qcStatus 1 (passed)
   [verify]      https://www.wunderground.com/dashboard/pws/KPADOYLE21

4. REPORTED PRESSURE  (sea-level adjusted - every provider normalises to this)
   P_msl       : 30.28 inHg

5. ELEVATION CORRECTION  (standard-atmosphere barometric formula)
   P_station = P_msl x (1 - 0.0065 x h / 288.15) ^ 5.25588
             = 30.28 x (1 - 0.0065 x 99.16 / 288.15) ^ 5.25588
             = 30.28 x 0.98830
             = 29.9257 inHg
             = 760.11 mmHg
   Cross-check : legacy 1 inHg/1000 ft rule gives 760.85 mmHg  (+0.74 mmHg)

6. YOUR PRESSURE, IN OTHER UNITS
   760.11 mmHg | 29.926 inHg | 1013.40 hPa | 101.340 kPa | 101340 Pa

--- steps 1-6 are panel 1: the pressure at your address. -------------------
--- step 7 is panel 2, and only appears once you enter a temperature. ------
--- step 8 is panel 3 (§5.7), only if you compare against your own meter. --

7. Ctp
   Protocol    : AAPM TG-51, 22.0 C reference  [auto-selected: country = US]
   Your temp   : 21.5 C
   Ctp = (273.2 + T) / (273.2 + T_ref) x (760.0 / P)
       = (273.2 + 21.5) / (273.2 + 22.0) x (760.0 / 760.11)
       = 0.99831 x 0.99985
       = 0.9982
   If TRS-398 (20.0 C) were selected instead: 1.0050   (+0.68%)
```

Five deliberate choices in that layout:

- **Formulas are shown with the actual numbers substituted**, not just symbolically
  and not just as a result. A physicist can check any line with a calculator,
  which is the entire point.
- **The station's elevation is displayed but explicitly marked unused.** It is the
  number the old code wrongly used (§2.4(b)); showing it beside the one now used
  makes the fix legible instead of invisible.
- **The unselected protocol's Ctp is shown too.** It costs one multiplication and
  removes any doubt about the §2.4(d) default change.
- **Every external fact carries its verify link.** Station and elevation links are
  human-readable pages where possible, not raw API URLs.
- **The provider is named in step 3, and a fallback says so.** If WU was
  unavailable and Open-Meteo answered, step 3 reads
  `Provider : Open-Meteo (fallback - Weather Underground unavailable)`, with the
  same line raised as a warning. A number from a different source than usual
  should never look identical to one from the usual source.

When a fallback provider answers, step 3 shapes itself to what that source
actually is. Open-Meteo is a model grid, not a station, so it reports its grid
cell and resolution instead of a station id and distance — the trace should not
invent a station that does not exist. The NWS variant names the observing
station and notes that its `barometricPressure` field is being read as an
altimeter setting, per §3.1.1.

**Export.** A "copy as text" button (and `--trace` on the CLI) emits exactly the
block above, timestamped, for pasting into a QA log. Clinics keep records; the
tool should hand them something paste-ready rather than making them retype it.

**Warnings render inline, at the step they belong to**, not collected in a
footer — a station 14 miles away or a 3-hour-old observation is flagged in
step 3 where the user is already looking.

### 5.6 Web app layout — two panels

The split is by *what the user is asking for*, and the rule is that panel 1 must
be complete and correct on its own for someone who only wants the pressure.

```
┌─ PANEL 1 ─ PRESSURE ──────────────────────────────────────────┐
│  Address:  [ 123 Main St, Doylestown PA 18901        ] [Go]   │
│                                                               │
│      760.11 mmHg                                              │
│      at 123 Main St, Doylestown PA 18901 (325 ft)             │
│      Weather Underground - KPADOYLE21, 0.7 mi - 14 min ago    │
│                                                               │
│      29.926 inHg | 1013.40 hPa | 101.340 kPa | 101340 Pa      │
│                                                               │
│  ▾ Show your work                    [copy as text]           │
│      steps 1-6 of the §5.5 trace                              │
└───────────────────────────────────────────────────────────────┘

┌─ PANEL 2 ─ Ctp  (optional) ───────────────────────────────────┐
│  Temperature:  [ 21.5 ] °C                                    │
│                                                               │
│  Reference protocol:                                          │
│    (•) 22 °C - AAPM TG-51        auto-selected: address is US │
│    ( ) 20 °C - IAEA TRS-398                                   │
│                                                               │
│      Ctp = 0.9982        (TG-51, 22 °C reference)             │
│      with TRS-398 instead: 1.0050  (+0.68%)                   │
│                                                               │
│  ▾ Show your work                                             │
│      step 7 of the §5.5 trace                                 │
└───────────────────────────────────────────────────────────────┘

┌─ PANEL 3 ─ Intercomparison  (optional) ───────────────────────┐
│  Your measured pressure:  [ 757.0 ]  [ mmHg ▾ ]               │
│  Your measured temp:      [ 21.8  ] °C   (optional)           │
│                           blank = reuse panel 2's 21.5 °C     │
│                                                               │
│      Ctp   calculated  0.9982                                 │
│            yours       1.0033                                 │
│            difference  +0.0051      (+0.513%)                 │
│                                                               │
│            both at TG-51, 22 °C - inherited from panel 2      │
│                                                               │
│  ▾ Show your work                                             │
│      step 8 of the §5.5 trace                                 │
└───────────────────────────────────────────────────────────────┘
```

Consequences worth stating, because they constrain the implementation:

- **Panel 1 never mentions a protocol**, since none is involved in producing that
  number. Its trace ends at step 6.
- **Panel 2 does not re-fetch anything.** It reads the cached `PressureResult`,
  so both the temperature and the protocol radio recompute instantly. This is the
  reason `PressureResult` holds no Ctp value (§4).
- **Panels 2 and 3 stay collapsed until used.** A user who wants only the
  pressure sees only panel 1 and is done.
- **Each panel exports its own trace**, and the top-level "copy as text" emits
  whichever panels the user has actually filled in — a pressure-only lookup
  should not paste a Ctp section into the QA log.

### 5.7 Panel 3 — intercomparison against a local instrument

**What it answers:** *my barometer and thermometer in the vault read X and Y —
how far is the Ctp they give me from the Ctp this tool derived?*

**Panel 3 reports one thing: the difference between two Ctp values.** Not a
pressure difference, not a temperature difference. Pressure and temperature are
*inputs* to the second Ctp, and they are echoed back so the user can confirm what
was entered, but they are not reported as differences. Ctp is what propagates
into a dose measurement, so Ctp is what the comparison is about.

```python
@dataclass(frozen=True)
class IntercomparisonResult:
    # what the user measured — echoed for verification, not compared
    local_pressure_mmhg: float
    local_pressure_input: float      # as typed, before unit conversion
    local_pressure_unit: str         # "mmHg" | "inHg" | "hPa" | "kPa"
    local_temp_c: float
    local_temp_inherited: bool       # True if panel 2's temperature was reused
    # the comparison
    ctp_calculated: float
    ctp_local: float
    d_ctp: float
    d_ctp_pct: float
    protocol: CtpProtocol            # inherited from panel 2, never chosen here
    trace: list[TraceStep]
```

**Inputs.**

1. **Measured pressure — required**, with a **unit dropdown**
   (mmHg / inHg / hPa / kPa). The dropdown is not a convenience: a clinic
   barometer reading 1013 hPa typed into a field expecting mmHg is a silent
   33% error that produces a plausible-looking number. Converting explicitly
   makes the unit part of the record.
2. **Measured temperature — optional.** Left blank it reuses panel 2's value and
   says so (`local_temp_inherited`). Filled in, the second Ctp comes entirely
   from the clinic's own instrument pair.

**The protocol is inherited from panel 2 and is not selectable here.** Both Ctp
values must use the same reference or the comparison silently mixes an instrument
difference with a 0.6775% convention difference (§2.4(d)) — the result would be
uninterpretable. The panel states which protocol both sides used.

**Output.** With the worked example:

```
   Your readings : 757.00 mmHg (entered as 757.0 mmHg), 21.8 C

   Ctp
       calculated  0.9982
       yours       1.0033
       difference  +0.0051      (+0.513%)

   both at AAPM TG-51, 22 C reference
```

**A domain fix carried over from the current code.** Today's `intercomparison()`
([pressure_converter.py:322-332](pressure_converter.py#L322-L332)) reports four
figures — absolute and percent differences in temperature and in pressure — and
no Ctp comparison at all. One of those, the *percent difference in Celsius*, is
not a sound quantity: Celsius is an interval scale with an arbitrary zero, so
dividing by it gives a number that depends on where you sit on the scale rather
than on the physics. The same **+0.3 °C** difference reports as +1.40% at 21.5 °C,
**+30%** at 1 °C, **−15%** at −2 °C, and raises **ZeroDivisionError** at exactly
0 °C (bug #10). Reporting Ctp instead retires all four figures and the unsound
one with them.

**Addressing the division-by-zero properly (bug #10).** Deleting the Celsius
percentage removes the specific crash, but not the class of bug — `ctp()` itself
divides by pressure, and the percent difference divides by `ctp_calculated`.
Both are reachable from user input:

| Input | Consequence |
|---|---|
| `P = 0` | `760.0 / P` → `ZeroDivisionError` |
| `T = −273.2 °C` | `(273.2 + T)` → 0, so `ctp` → 0, so the percent difference divides by zero |

So the fix belongs at the **input boundary**, not at each division. `physics.py`
validates before computing and raises a domain error with a readable message
instead of letting an arithmetic exception escape:

```python
ABSOLUTE_ZERO_C = -273.15
PLAUSIBLE_PRESSURE_MMHG = (225.0, 825.0)   # ~9000 m up to a record sea-level high
PLAUSIBLE_TEMP_C        = (-50.0, 60.0)

def _validate(temp_c: float, pressure_mmhg: float) -> None:
    if pressure_mmhg <= 0:
        raise PhysicsInputError("Pressure must be greater than zero.")
    if temp_c <= ABSOLUTE_ZERO_C:
        raise PhysicsInputError(f"Temperature must be above absolute zero ({ABSOLUTE_ZERO_C} °C).")
```

Values outside the *plausible* ranges are not rejected — they are accepted with a
warning, since the tool should not refuse to work somewhere unusual. Only the
physically impossible is refused. Both bounds get tests, including the exact
`P = 0` and `T = −273.2` cases above.

**Trace step 8** shows both Ctp calculations side by side with their numbers
substituted, the unit conversion applied to the entered pressure (raw input and
converted value both shown), and whether the temperature was entered or
inherited.

**Unit-mismatch guard.** If the entered pressure differs from the calculated one
by more than ~10%, the panel asks *"did you mean hPa?"* rather than reporting a
300% discrepancy — that magnitude is far more likely a unit mix-up than a real
instrument fault. This is a prompt, not a rejection.

**No tolerance or pass/fail flag.** Whether a given ΔCtp is acceptable is a
clinical judgement, and the tool does not make it. Panel 3 reports the difference
and stops.

**CLI parity.** `--compare-pressure <value> --compare-unit <unit>
[--compare-temp <C>]`, printing the same block.

---

## 6. Phased work

Each phase leaves the repo working. No phase requires the next.

**Phase 0 — hygiene** *(~30 min)*
Rewrite `requirements.txt` as UTF-8; fix `.gitignore` (`venv/`, `.venv/`,
`__pycache__/`, `.env`); delete `debug_get_pressure`; add `pyproject.toml` and a
`ruff` config; reindent to 4 spaces.

**Phase 1 — extract the pure core** *(~2 h)*
Move the math into `physics.py` per §5.3 and §5.4: `msl_to_station_pressure()`
(both methods), `convert_pressure_units()`, `ctp()` with the protocol argument,
`intercomparison()`. Write tests **first** pinning today's outputs so the
extraction is provably behaviour-preserving, then add the §2.4(c) table as the
barometric fixture and flip the default. Fixes bug #9. No network code yet.

Two intentional output changes land here and both need explicit before/after
tests, so the diff in results is a reviewed artefact rather than a surprise:
barometric replacing linear (§2.4(c)), and the TG-51 default replacing the
implicit 20 °C (§2.4(d), a uniform −0.6775%).

**Phase 2 — geocoding and elevation** *(~2 h)*
Build `geocode.py` (§5.1) and `elevation.py` (§5.2) with their fallback chains,
caching, and rate limiting. Add `geopy` to requirements. Test each provider in
the chain independently, plus the fallthrough behaviour when the first returns
nothing. This is the phase that delivers "the user types only their address".
Capture `country_code` here — normalised with `.upper()`, with a test covering
Nominatim's lowercase `us` — since §5.4's auto-selection depends on it.

**Phase 3 — providers: WU primary, two keyless fallbacks** *(~4 h)*
Build `providers/base.py` around the §3.1.1 contract — *every provider returns
`P_msl` plus metadata; none of them does the elevation correction*. Then:

- `wunderground.py` (primary) on the two verified endpoints, key from
  `WU_API_KEY` defaulting to the public one.
- `openmeteo.py` (fallback 1, worldwide, keyless) reading `pressure_msl`.
- `nws.py` (fallback 2, US only, keyless) reading `barometricPressure`
  **as an altimeter setting**, walking down `observationStations` past null
  readings, and honouring `qualityControl`.

All three ship together: the fallbacks are what keeps the tool alive when the
public key stops, so deferring them would leave the primary path unprotected.
Retire the BeautifulSoup selectors and `soup_check()`; drop `bs4` / `soupsieve`.
Fixes bug #2 and the fragility in §2.4(a).

Tests that matter here: the Leadville case from §3.1.1, asserting the NWS
provider yields ~716 hPa station pressure rather than a 1505 hPa MSL; and the
cross-provider agreement check (WU vs Open-Meteo vs NWS at one point, expected
within ~0.2%), which catches a provider silently changing its units or
reference.

**Phase 4 — the service seam** *(~1 h)*
Write `service.py` implementing the §4 contract, including the elevation
correctness fix from §2.4(b): use the **address's** elevation from `elevation.py`,
never the station's, and emit a `warning` if it ever has to fall back to the
station figure. Add the provider fallback chain with its warnings. Assemble the
§5.5 `TraceStep` list as the chain runs — each stage appends its own step, so the
trace cannot drift out of sync with the calculation that produced it. Wire up
`auto_protocol()` (§5.4) to populate `suggested_ctp_protocol`. Rewrite `cli.py`
as a thin caller — one address prompt, plus `--protocol` and `--trace`.
Fixes bugs #1, #3, #4, #5.

**Phase 5 — the web app** *(~5 h)*
Build the three panels of §5.6. Panel 1 is address in, pressure out, with steps
1-6 of the trace and no mention of any protocol. Panel 2 holds the temperature
input, the TG-51/TRS-398 radio pre-selected from country, and step 7 — all
recomputing from the cached `PressureResult` with no refetch. Panel 3 is the
§5.7 intercomparison: measured pressure with a unit dropdown, optional
temperature inheriting panel 2's, and ΔCtp as the headline.

Panel 3 tests: the unit conversions round-trip; a blank temperature inherits
rather than defaulting to zero; the protocol is taken from panel 2 and cannot
diverge; only a Ctp difference is reported; and the §5.7 input validation
rejects `P = 0` and `T = −273.2 °C` with a readable domain error rather than a
`ZeroDivisionError` (bug #10), while merely implausible values pass with a
warning.

The trace is the bulk of this phase's work and the reason the estimate moved from
3 h to 4 h. Build it as a shared renderer taking `list[TraceStep]`, so the CLI's
`--trace` and the web panel cannot disagree about what the program did.

**Phase 6 — deploy** *(~1 h)* — see §7.

**Later, optional:** cache observations for ~5 min per station — WU updates every
few minutes, so there is no reason to re-hit the API on every reload; let the user
override the auto-picked station from the nearest-10 list; log nothing that
identifies a patient or a site.

---

## 7. Free hosting options

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

Note that the geocoding and elevation chains chosen in §3.2 and §3.3 keep that
escape hatch genuinely open: USGS and the WU API both send
`Access-Control-Allow-Origin: *`, and Nominatim/Photon/Open-Meteo are all
browser-callable. The one exception is the US Census geocoder, which sends no
CORS headers — a static build would fall back to Nominatim first instead.

---

## 8. Decisions

**Resolved in this revision:**

- ~~Pressure formula~~ → barometric is now the default; linear retained as a
  labelled cross-check (§2.4(c), §5.3).
- ~~Geocoder~~ → `geopy` (Nominatim + Photon) plus a small custom Census
  adapter, chained (§3.2, §5.1).
- ~~Elevation source~~ → USGS → Open-Meteo → OpenTopoData, chained, using the
  **address's** elevation rather than the station's (§3.3, §5.2).
- ~~Ctp reference temperature~~ → user-selectable toggle, **defaulting to TG-51
  (22 °C)** as the US standard, with TRS-398 one click away for international
  use (§2.4(d), §5.4).
- ~~"Table method" reading~~ → confirmed as the standard-atmosphere barometric
  formula, not a published lookup chart (§2.4(c)).
- ~~WU API key~~ → the API is not publicly available, so the public key is the
  primary route (§3.1 options 2 + 3), with `WU_API_KEY` to override.
- ~~Keep the NWS provider?~~ → yes, as fallback 2 for US addresses, alongside
  Open-Meteo as the worldwide fallback 1 (§3.1.1).
- ~~Web app scope~~ → three panels, pressure standing alone in panel 1, Ctp and
  its protocol toggle in panel 2 (§5.6).
- ~~Panel 3 in the web app?~~ → yes, fully specified in §5.7: local pressure
  with a unit dropdown, optional second temperature, and a Ctp difference as the
  only reported comparison.
- ~~Ctp tolerance / action level~~ → not the tool's business; no threshold, no
  pass/fail flag (§5.7).

**Still open:**

None. Every question this plan raised has been answered.

Tolerances and action levels are deliberately **out of scope** — panel 3 reports
the Ctp difference and leaves the judgement to the clinical user (§5.7, §9).

## 9. Explicitly out of scope

Accounts / auth, storing results, mobile apps, patient data of any kind,
tolerances or action levels on the §5.7 comparison, and any claim of
medical-device or regulatory status. This stays a convenience calculator
whose sources are always shown so the user can verify them — which is the right
instinct the current program already has.
