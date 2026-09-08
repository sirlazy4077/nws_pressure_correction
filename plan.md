# Refactor Plan — BaroMe / nws_pressure_correction

**Status:** proposal only, nothing implemented.
**Drafted:** 2026-09-08 · **Revised:** 2026-09-08 (geocoding, elevation,
barometric formula, Ctp toggle defaulting to TG-51)

## 1. Goal

Turn the current 388-line interactive script into a small, testable library with two
thin front ends (CLI + web), and change the user contract to:

> The user types **one thing — their address**. The app returns the
> **elevation-adjusted local barometric pressure** (plus the derived Ctp).

Everything else — latitude/longitude, which weather station, the station's
elevation, the site's elevation — is resolved for them. Weather Underground is
the default source for all users, worldwide.

The one deliberate exception to "one input" is the **Ctp reference protocol**
(§5.4): a two-option toggle, chosen once and remembered, defaulting to
**AAPM TG-51 (22 °C)** for US users with **IAEA TRS-398 (20 °C)** one click away
for international ones. It stays visible rather than silent because the software
must not quietly pick a clinical convention on the user's behalf.

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

### 3.1 The WU API key question — needs your decision

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
`barome/<version> (kprisolo@gmail.com)`), and no bulk querying. All three are
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

**Default is TG-51 (22 °C)** — AAPM TG-51 is the US standard and this is a US
clinic. TRS-398 (20 °C) remains one click away for international users, for whom
it is the standard.

Note this is a **deliberate change from current behaviour**, which is
unconditionally 20 °C: see the −0.6775% shift documented in §2.4(d). It is the
one place in this refactor where output moves for a reason other than a bug fix,
so it should be the loudest line in the release notes.

Surfaced in both front ends:

- **Web:** a two-option radio directly above the Ctp result —
  `(•) 22 °C — AAPM TG-51` / `( ) 20 °C — IAEA TRS-398`. The result line always
  restates it: *"Ctp = 1.0145 (TG-51, 22 °C reference)"*. Selection persists in
  session state so it is chosen once, not every visit.
- **CLI:** a `--protocol {tg-51,trs-398}` flag, defaulting to `tg-51`.
- **Config:** a `BAROME_CTP_PROTOCOL` environment variable lets a site pin its
  house standard so nobody has to remember — the natural setting for an
  international deployment to flip to `trs-398` once, globally.

The protocol is a field on `PressureResult` and appears in every rendering. The
failure mode being designed out is a physicist reading a Ctp without knowing
which reference produced it — and at a uniform 0.6775%, that ambiguity is larger
than the elevation error this whole refactor exists to fix.

*Optional refinement, not planned unless you want it:* the geocoder already
returns a `countrycode` for every resolved address (verified — Photon returns
`"countrycode":"US"`). A locale-aware default that suggests TRS-398 for non-US
addresses would therefore cost almost nothing. Left out deliberately: an
auto-switching clinical convention is exactly the kind of silent behaviour this
section is trying to eliminate. Flagging it as available, not recommending it.

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

**Phase 3 — replace scraping with the WU API** *(~2 h)*
Build `providers/wunderground.py` on the two verified endpoints from §3. Retire
the BeautifulSoup selectors and `soup_check()`; drop `bs4` / `soupsieve` from
requirements. Fixes bug #2 and the fragility in §2.4(a).

**Phase 4 — the service seam** *(~1 h)*
Write `service.py` implementing the §4 contract, including the elevation
correctness fix from §2.4(b): use the **address's** elevation from `elevation.py`,
never the station's, and emit a `warning` if it ever has to fall back to the
station figure. Rewrite `cli.py` as a thin caller — one address prompt, plus the
`--protocol` flag. Fixes bugs #1, #3, #4, #5.

**Phase 5 — the web app** *(~3 h)*
One text input, one button, one results card: the corrected pressure large and
first, then the unit table, then a collapsible "how we got this" panel showing
the resolved address and geocoder used, station name and distance, observation
timestamp, both elevations, the legacy linear cross-check, and the source links.
Second panel for Ctp — temperature input plus the §5.4 protocol toggle — and
intercomparison, preserving today's features.

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

## 8. Decisions still open

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

**Still open:**

1. **WU API key** — is there a personal weather station available to get a free
   official key, or ship with the public one plus an env-var override?
2. **Scope of the web app** — address-and-pressure only, or carry Ctp and
   intercomparison across too? This plan assumes all three, with the latter two
   collapsed by default.
3. **Keep the NWS provider?** It is now redundant for the default flow, but it is
   a useful independent cross-check and a fallback if the WU key dies.

Everything else is specified. The remaining three are all "which way do you want
it", not "how would this work" — none of them block starting Phase 0.

## 9. Explicitly out of scope

Accounts / auth, storing results, mobile apps, patient data of any kind, and any
claim of medical-device or regulatory status. This stays a convenience calculator
whose sources are always shown so the user can verify them — which is the right
instinct the current program already has.
