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

# Command line
python cli.py "123 Main St, Doylestown PA 18901"
python cli.py "123 Main St, Doylestown PA 18901" --temp 21.5 --trace
python cli.py "123 Main St, Doylestown PA 18901" --temp 21.5 \
              --compare-pressure 757 --compare-unit mmHg

# Web app (three panels)
streamlit run web/app.py
```

Run `python cli.py --help` for the full set of options.

## What it does

**Panel 1 — pressure.** Your address is geocoded (US Census → Nominatim →
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
| `BAROME_CONTACT` | Contact address sent in the User-Agent (Nominatim's usage policy requires a genuine one). |
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
for a clinic checking pressure a few times a day.

Point it at `web/app.py`; it installs from `requirements.txt`.

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
