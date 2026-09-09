"""The "show your work" renderer.

One implementation, taking `list[TraceStep]`, so the CLI's `--trace` and the
web panels cannot disagree about what the program did.

Every number the tool reports must be traceable to its inputs without reading
the source. The current script's one genuinely good instinct is printing the
source URL so the user can verify it; this generalises that instinct to the
whole chain.
"""

from __future__ import annotations

from datetime import datetime

from .models import CtpResult, IntercomparisonResult, PressureResult, TraceStep
from .physics import REFERENCE_TEMP_C, Method

STAGE_TITLES = {
    "geocode": "ADDRESS",
    "elevation": "YOUR ELEVATION  (at your address, not the station's)",
    "station": "PRESSURE SOURCE",
    "observation": "REPORTED PRESSURE  (sea-level adjusted - every provider normalises to this)",
    "correction": "ELEVATION CORRECTION",
    "units": "YOUR PRESSURE, IN OTHER UNITS",
    "ctp": "Ctp",
    "intercomparison": "INTERCOMPARISON  (your instruments vs the calculated value)",
}

_INDENT = " " * 3

# Trace steps carry machine-readable keys; the reader gets prose.
INPUT_LABELS = {
    "temperature_C": "Your temp",
    "pressure_mmHg": "Pressure",
    "entered_pressure": "You entered",
    "converted_pressure_mmHg": "Converted",
    "temperature_source": "Temp source",
}


def _line(label: str, value: object) -> str:
    return f"{_INDENT}{label:<12}: {value}"


def _block(text: str) -> str:
    return "\n".join(f"{_INDENT}{ln}" for ln in text.splitlines())


def _step_geocode(step: TraceStep) -> list[str]:
    out = step.output
    return [
        _line("You entered", step.inputs.get("address")),
        _line("Resolved to", out.get("resolved")),
        _line("Geocoder", f"{step.provider} ({out.get('confidence')} match)"),
        _line("Coordinates", f"{out.get('lat')}, {out.get('lon')}"),
        _line("Country", f"{out.get('country') or 'unresolved'}   (drives the Ctp protocol)"),
    ]


def _step_elevation(step: TraceStep) -> list[str]:
    out = step.output
    return [
        _line("Elevation", f"{out.get('elevation_ft')} ft  ({out.get('elevation_m')} m)"),
        _line("Source", step.provider),
    ]


def _step_station(step: TraceStep) -> list[str]:
    out = step.output
    lines = [_line("Provider", step.provider)]
    if out.get("station_id"):
        name = f' "{out["station_name"]}"' if out.get("station_name") else ""
        lines.append(_line("Station", f"{out['station_id']}{name}"))
    elif out.get("station_name"):
        lines.append(_line("Source", out["station_name"]))
    if out.get("distance_mi") is not None:
        lines.append(_line("Distance", f"{out['distance_mi']} mi from your address"))
    if out.get("station_elev_ft") is not None:
        lines.append(
            _line(
                "Station elev",
                f"{out['station_elev_ft']} ft   (not used in the calculation - "
                "shown for comparison)",
            )
        )
    lines.append(
        _line("Observed", f"{out.get('observed_utc')} UTC  ({out.get('age_minutes')} min ago)")
    )
    if out.get("quality"):
        lines.append(_line("Quality", out["quality"]))
    return lines


def _step_observation(step: TraceStep) -> list[str]:
    return [_line("P_msl", f"{step.output.get('pressure_msl_inhg')} inHg")]


def _step_units(step: TraceStep) -> list[str]:
    out = step.output
    order = ("mmHg", "inHg", "hPa", "kPa", "Pa")
    parts = [f"{out[u]:g} {u}" for u in order if u in out]
    return [f"{_INDENT}" + " | ".join(parts)]


def render_steps(steps: list[TraceStep], start_number: int = 1) -> str:
    """Render trace steps as the numbered block the user reads and pastes."""
    chunks: list[str] = []
    for offset, step in enumerate(steps):
        number = start_number + offset
        title = STAGE_TITLES.get(step.stage, step.stage.upper())
        if step.stage == "correction":
            method = (
                "standard-atmosphere barometric formula"
                if "standard" in step.provider
                else "legacy linear rule of thumb"
            )
            title = f"{title}  ({method})"
        body: list[str] = [f"{number}. {title}"]

        if step.stage == "geocode":
            body += _step_geocode(step)
        elif step.stage == "elevation":
            body += _step_elevation(step)
        elif step.stage == "station":
            body += _step_station(step)
        elif step.stage == "observation":
            body += _step_observation(step)
        elif step.stage == "units":
            body += _step_units(step)
        else:
            if step.stage in {"ctp", "intercomparison"}:
                body.append(_line("Protocol", step.provider))
                for key, value in step.inputs.items():
                    if key in {"protocol", "protocol_source"}:
                        continue
                    body.append(_line(INPUT_LABELS.get(key, key.replace("_", " ")), value))

        if step.expression:
            body.append(_block(step.expression))
        if step.note:
            body.append(_block(step.note))
        if step.url:
            body.append(f"{_INDENT}[verify]      {step.url}")
        # Warnings render at the step they belong to, not in a footer.
        for warning in step.warnings:
            body.append(_block(f"!! {warning}"))
        chunks.append("\n".join(body))
    return "\n\n".join(chunks)


def render_pressure_trace(result: PressureResult) -> str:
    """Steps 1-6: panel 1, the pressure at your address."""
    return render_steps(result.trace, start_number=1)


def render_full_trace(
    result: PressureResult,
    ctp_result: CtpResult | None = None,
    comparison: IntercomparisonResult | None = None,
) -> str:
    """The whole chain, numbered end to end.

    Emits only the panels the user actually filled in: a pressure-only lookup
    should not paste a Ctp section into the QA log.
    """
    header = [
        "BaroMe - elevation-adjusted pressure",
        f"Generated {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
        "=" * 68,
        "",
    ]
    parts = [render_steps(result.trace, start_number=1)]
    n = len(result.trace) + 1
    if ctp_result is not None:
        parts.append(render_steps(ctp_result.trace, start_number=n))
        n += len(ctp_result.trace)
    if comparison is not None:
        parts.append(render_steps(comparison.trace, start_number=n))
    return "\n".join(header) + "\n\n".join(parts) + "\n"


def render_summary(result: PressureResult) -> str:
    """The headline answer, for the top of the CLI output."""
    lines = [
        f"{result.pressure_station_mmhg:.2f} mmHg",
        f"   at {result.resolved_address}  ({result.site_elev_ft:.0f} ft)",
        f"   {_provider_line(result)}",
        "",
        f"   {result.pressure_station_inhg:.3f} inHg | {result.pressure_station_hpa:.2f} hPa"
        f" | {result.pressure_station_kpa:.3f} kPa | {result.pressure_station_pa:.0f} Pa",
    ]
    if result.method is Method.BAROMETRIC:
        lines.append(
            f"   legacy 1 inHg/1000 ft cross-check: "
            f"{result.pressure_station_mmhg_linear:.2f} mmHg"
        )
    return "\n".join(lines)


def _provider_line(result: PressureResult) -> str:
    from .providers import label

    bits = [label(result.provider) + (" (fallback)" if result.provider_fallback else "")]
    if result.station_id:
        bits.append(result.station_id)
    if result.station_distance_mi is not None:
        bits.append(f"{result.station_distance_mi:.1f} mi")
    bits.append(f"{result.obs_age_minutes:.0f} min ago")
    return " - ".join(bits)


def render_ctp(ctp_result: CtpResult) -> str:
    t_ref = REFERENCE_TEMP_C[ctp_result.protocol]
    alt_ref = REFERENCE_TEMP_C[ctp_result.other_protocol]
    return "\n".join(
        [
            f"Ctp = {ctp_result.ctp:.4f}        ({ctp_result.protocol}, {t_ref:g} °C reference)",
            f"   {ctp_result.protocol_reason}",
            f"   with {ctp_result.other_protocol} ({alt_ref:g} °C) instead: "
            f"{ctp_result.ctp_other_protocol:.4f}  ({ctp_result.other_delta_pct:+.2f}%)",
        ]
    )


def render_comparison(comparison: IntercomparisonResult) -> str:
    """Panel 3 reports one thing: the difference between two Ctp values."""
    temp_note = " (inherited)" if comparison.local_temp_inherited else ""
    t_ref = REFERENCE_TEMP_C[comparison.protocol]
    return "\n".join(
        [
            f"   Your readings : {comparison.local_pressure_mmhg:.2f} mmHg "
            f"(entered as {comparison.local_pressure_input:g} {comparison.local_pressure_unit}), "
            f"{comparison.local_temp_c:g} °C{temp_note}",
            "",
            "   Ctp",
            f"       calculated  {comparison.ctp_calculated:.4f}",
            f"       yours       {comparison.ctp_local:.4f}",
            f"       difference  {comparison.d_ctp:+.4f}      ({comparison.d_ctp_pct:+.3f}%)",
            "",
            f"   both at {comparison.protocol}, {t_ref:g} °C reference",
        ]
    )
