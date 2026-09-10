# BaroMe — elevation-adjusted pressure from your address

You type one thing: **your address**. The tool returns the **station pressure at
that address** — and, if you want it, the Ctp for your vault.

The coordinates, the nearest reporting weather station, and the elevation *at
your address* are all resolved for you. Every number is shown with the formula
that produced it and a link back to its source, so you can check it rather than
trust it.

```
760.11 mmHg
   at 123 Main St, Doylestown PA 18901  (325 ft)
   Weather Underground - KPADOYLE21 - 0.7 mi - 14 min ago

   29.926 inHg | 1013.40 hPa | 101.340 kPa | 101340 Pa
```

## Quick start

```bash
pip install -r requirements.txt

# A contact email is required when you run it yourself (see below)
export BAROME_CONTACT=you@example.org        # PowerShell: $env:BAROME_CONTACT = "you@example.org"

# Command line
python cli.py "123 Main St, Doylestown PA 18901"
python cli.py --contact you@example.org "123 Main St, Doylestown PA 18901"
python cli.py --pick "123 Main St, Doyle"      # confirm the address from a list
python cli.py "123 Main St, Doylestown PA 18901" --temp 21.5 --trace
python cli.py "123 Main St, Doylestown PA 18901" --temp 21.5 \
              --compare-pressure 757 --compare-unit mmHg

# Web app (three panels)
streamlit run web/app.py
```

Run `python cli.py --help` for the full set of options.

## Using it from your own script

`barome` is an ordinary package; the CLI and web app are thin front ends over
it. Install it with `pip install -e .` (or from git), then:

```python
from barome import BaromeError, pressure_for_address, set_contact, suggest

set_contact("you@example.org")        # or set BAROME_CONTACT

loc = suggest("123 Main St, Doylestown PA")[0]      # resolve the address once
try:
    r = pressure_for_address(loc.display_name, location=loc)
except BaromeError as exc:
    print("lookup failed:", exc)
else:
    print(r.pressure_station_mmhg, r.warnings)
```

**A contact email is required.** Nominatim's usage policy requires every
request to identify who is making it, and that has to be you, not the author.
With none set, the first call raises `ContactRequiredError` before anything is
sent. The CLI asks for it at a terminal, and refuses to run unattended without
one.

**Elevation is cached between runs.** The first lookup for an address saves its
elevation to `%LOCALAPPDATA%\barome\elevation.json` (Windows) or
`~/.cache/barome/elevation.json`, so a script run every hour does not wait on
USGS every hour. The ground does not move; the pressure is fetched fresh every
time. Only an answer from the preferred source is saved: if USGS was down and
Open-Meteo answered, that run uses Open-Meteo's value but the next run asks
USGS again. The saved entry keeps its original source and URL, so the trace
still shows where the number came from.

## What it does

**Panel 1 — pressure.** You type what you know, press **Find address**, and pick
the exact one from a list of real, resolved candidates — so the address the tool
works from is one a geocoder actually knows, not one you hope it parsed
correctly. Suggestions come from Photon/OpenStreetMap, which is built for
search-as-you-type. (Nominatim cannot be used for this: its usage policy
prohibits autocomplete outright.)

OpenStreetMap does not know every address, so the list always ends with *"None
of these — use exactly what I typed"*, which runs the full geocoder chain on
your text. In the US that reaches the Census geocoder, which often has addresses
OpenStreetMap does not.

Picking a candidate costs no extra lookup: Photon returns the coordinates and
the country with the suggestion, so a confirmed address is already resolved.

Your address is then geocoded (US Census → Nominatim →
Photon), the elevation at that point is looked up (USGS → Open-Meteo →
OpenTopoData), and the nearest station's sea-level pressure is corrected to your
elevation with the standard-atmosphere barometric formula:

```
P_station = P_msl · (1 − 0.0065·h / 288.15) ^ 5.25588        (h in metres)
```

The legacy "1 inHg per 1000 ft" rule of thumb is still computed and shown beside
it, labelled as a cross-check, so numbers in older records stay reproducible.

**Panel 2 — Ctp.** Enter your vault temperature. The reference protocol is
selected from the address's country — US → **AAPM TG-51 (22 °C)**, everywhere
else → **IAEA TRS-398 (20 °C)** — and can be flipped at any time. Which protocol
was used, and whether it was chosen automatically or by hand, is stated on every
result.

**Panel 3 — intercomparison.** Enter your own barometer and (optionally)
thermometer readings. It reports **one** thing: the difference between the two
Ctp values. Not a pressure difference, not a temperature difference — Ctp is what
propagates into a dose measurement.

There is deliberately **no tolerance or pass/fail flag**. Whether a given ΔCtp is
acceptable is a clinical judgement, and this tool does not make it.

## ⚠️ Changed behaviour vs. the previous script

The old script always computed Ctp at 20 °C. The default is now **TG-51 (22 °C)**.
Because the protocols differ only by a constant ratio of reference temperatures,
this shifts **every** Ctp by exactly

    (273.2 + 20) / (273.2 + 22) − 1 = −0.6775%

uniformly, whatever the measured temperature and pressure. That is a real step
change against historical records, not rounding. Select TRS-398 in panel 2 (or
`--protocol trs-398`) to reproduce the old numbers.

The elevation correction also changed: the barometric formula replaces the linear
rule of thumb, and the elevation used is now **your address's**, not the weather
station's. At the reference test point that station-vs-address gap was 55 ft —
about 0.18% in Ctp.

## Data sources

| Purpose | Chain | Key needed |
|---|---|---|
| Geocoding | US Census → Nominatim → Photon | no |
| Elevation | USGS EPQS → Open-Meteo → OpenTopoData | no |
| Pressure | Weather Underground → Open-Meteo → NWS (US only) | see below |

**On the Weather Underground key.** WU's API is not publicly available: the free
tier requires contributing a personal weather station. What ships is the key WU's
own website embeds in its JavaScript — i.e. this is the same request a browser
makes when you visit wunderground.com. It works today and carries no uptime
guarantee, which is exactly why the two keyless fallbacks ship alongside it
rather than after it. When the primary is unavailable the tool falls back and
**says so**, on the result and in the trace.

Set `WU_API_KEY` to use your own key instead.

Every provider's only job is to return sea-level pressure. The elevation
correction happens once, in `physics.py`, so the calculation reads the same no
matter which source answered.

## Configuration

| Variable | Effect |
|---|---|
| `WU_API_KEY` | Your own Weather Underground key. |
| `BAROME_CTP_PROTOCOL` | Pin a house standard (`TG-51` / `TRS-398`). Suppresses the country auto-selection and says so on screen. |
| `BAROME_CONTACT` | **Required for local runs.** Your contact email, sent in the User-Agent (Nominatim's usage policy requires a genuine one). `--contact` or `barome.set_contact()` do the same. The web app reads it from its secrets and refuses to run without it. |
| `BAROME_ELEVATION_CACHE` | Where the elevation cache file lives, or `0`/`off` to disable it. Default: your user cache directory. Off in the web app. |
| `BAROME_HTTP_TIMEOUT` | Seconds. Default 12. |
| `BAROME_USGS_TIMEOUT` | Seconds. Default 25 — USGS EPQS is reliably correct and reliably slow. |
| `BAROME_SYSTEM_TRUST` | Set to `0` to verify TLS against Python's bundled CA list instead of the OS trust store. On by default. |
| `SSL_CERT_FILE` | An alternative to the above: point it at your proxy's CA bundle. |

## Networks that intercept HTTPS

Many clinic networks terminate HTTPS at a proxy and re-sign it with a private
CA. Managed workstations trust that CA — it is pushed in by group policy — which
is why a browser reaches these APIs happily while Python does not: Python
verifies against its own bundled CA list, which has never heard of the proxy.

`truststore` is a required dependency for exactly this reason. It makes Python
verify against the operating system's trust store, the same one the browser
uses, so the tool works on an intercepting network with no configuration. It is
a harmless no-op elsewhere, where the OS store and the bundled list agree.

Verified on an intercepting network: without it, Open-Meteo, OpenTopoData,
Nominatim and Photon all failed certificate verification while Census, Weather
Underground, NWS and USGS worked — so US addresses resolved but international
ones could not. With it, all eight reach.

If a request still fails, the error says so in those terms rather than blaming
your spelling, and points at the proxy rather than at the client.

## Deploying

**Streamlit Community Cloud** is the recommended host: it deploys straight from
this repo on push, keeps one Python codebase for both front ends, and has a
secrets UI for `WU_API_KEY`. A ~40 second cold start after idle is a non-issue
for a clinic checking pressure a few times a day. It also sidesteps the
intercepting-proxy problem entirely, because the API calls then originate from
Streamlit's network rather than the clinic's.

1. Sign in at [share.streamlit.io](https://share.streamlit.io) with the GitHub
   account that owns this repo, and authorise it.
2. **Create app** → this repository → the branch you want to serve →
   main file path **`web/app.py`**.
3. Under **Advanced settings**, choose **Python 3.11 or newer**. The package
   uses `StrEnum` and `datetime.UTC`, both 3.11+.
4. Still under Advanced settings, add the secrets in TOML form.
   `BAROME_CONTACT` is required — the app shows a setup error without it; the
   others are optional:

   ```toml
   BAROME_CONTACT = "you@example.org"
   WU_API_KEY = "your-own-key"
   BAROME_CTP_PROTOCOL = "TG-51"
   ```

   The contact is sent only in the User-Agent to the services the app queries
   (Nominatim's policy requires it); it is never shown on the page and never
   written in the repository. To run the web app locally, put the same line in
   `.streamlit/secrets.toml`, which is git-ignored.

5. Deploy. It installs from `requirements.txt` at the repo root.

Every later `git push` to that branch redeploys automatically.

Apps are **public by default**. Nothing here handles patient data, but if you
would rather it were not world-readable, set the app to private in its settings
and add viewers by email — the free tier allows this.

## Layout

```
src/barome/
  physics.py      PURE - no network, no I/O. All the maths, fully unit-tested.
  geocode.py      address -> lat/lon, over a fallback chain
  elevation.py    lat/lon -> the elevation at that point
  providers/      wunderground (primary), openmeteo, nws - each returns P_msl
  service.py      the one contract both front ends call
  render.py       the shared "show your work" renderer
cli.py            thin
web/app.py        thin
tests/            125 tests, no network
```

## Development

```bash
pip install -e ".[dev,web]"
python -m pytest      # no network required
python -m ruff check .
```

## Scope

A convenience calculator whose sources are always shown so you can verify them.
No accounts, no stored results, no patient data of any kind, no tolerances or
action levels, and no claim of medical-device or regulatory status.
