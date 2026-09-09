"""BaroMe web front end - three panels.

Thin by design, like the CLI: every number on this page comes from
`barome.service`, and every explanation from `barome.render`.

The split is by *what the user is asking for*, and the rule is that panel 1
must be complete and correct on its own for someone who only wants the
pressure.

Run it with:  streamlit run web/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from barome import service  # noqa: E402
from barome.errors import BaromeError  # noqa: E402
from barome.physics import PRESSURE_UNITS, REFERENCE_TEMP_C, CtpProtocol  # noqa: E402
from barome.render import render_full_trace, render_steps  # noqa: E402

st.set_page_config(
    page_title="BaroMe - pressure from your address",
    page_icon="🌡️",
    layout="centered",
)

PROTOCOL_CHOICES = [CtpProtocol.TG_51, CtpProtocol.TRS_398]
PROTOCOL_CAPTION = {
    CtpProtocol.TG_51: "22 °C — AAPM TG-51",
    CtpProtocol.TRS_398: "20 °C — IAEA TRS-398",
}


# =========================================================================
# PANEL 1 - PRESSURE
# =========================================================================

st.title("Pressure at your address")
st.caption(
    "Type one thing: your address. The coordinates, the nearest reporting station "
    "and the elevation **at your address** are resolved for you."
)

address = st.text_input(
    "Address",
    key="address",
    placeholder="123 Main St, Doylestown PA 18901",
    label_visibility="collapsed",
)
go = st.button("Go", type="primary")

# Changing the address invalidates everything downstream. Panels 2 and 3 derive
# from the stored result and are recomputed on every rerun, so dropping a
# result whose address no longer matches the box is what guarantees no panel
# can display a number belonging to a previous address.
stored = st.session_state.get("result")
if stored is not None and stored.address_query != address:
    del st.session_state["result"]

if go and address.strip():
    with st.spinner("Locating, then reading the nearest station..."):
        try:
            st.session_state["result"] = service.pressure_for_address(address)
        except BaromeError as exc:
            st.session_state.pop("result", None)
            st.error(str(exc))

result = st.session_state.get("result")

ctp_result = None
comparison = None

if result is None:
    st.info("Enter an address and press **Go**.")
else:
    st.metric(
        label="Station pressure at your address",
        value=f"{result.pressure_station_mmhg:.2f} mmHg",
    )
    st.write(f"at **{result.resolved_address}** — {result.site_elev_ft:.0f} ft")

    provider_bits = [service.provider_label(result.provider)]
    if result.provider_fallback:
        provider_bits.append("fallback")
    if result.station_id:
        provider_bits.append(result.station_id)
    if result.station_distance_mi is not None:
        provider_bits.append(f"{result.station_distance_mi:.1f} mi")
    provider_bits.append(f"{result.obs_age_minutes:.0f} min ago")
    st.caption(" · ".join(provider_bits))

    cols = st.columns(4)
    cols[0].markdown(f"**{result.pressure_station_inhg:.3f}**  \ninHg")
    cols[1].markdown(f"**{result.pressure_station_hpa:.2f}**  \nhPa")
    cols[2].markdown(f"**{result.pressure_station_kpa:.3f}**  \nkPa")
    cols[3].markdown(f"**{result.pressure_station_pa:.0f}**  \nPa")

    for warning in result.warnings:
        st.warning(warning, icon="⚠️")

    with st.expander("Show your work"):
        st.code(render_steps(result.trace, start_number=1), language="text")
        st.caption("Steps 1-6. No reference protocol is involved in this number.")

    st.divider()

    # =====================================================================
    # PANEL 2 - Ctp
    # =====================================================================

    st.subheader("Ctp")
    st.caption("Optional. Enter your vault temperature.")

    temperature = st.number_input(
        "Temperature (°C)",
        value=None,
        step=0.1,
        format="%.2f",
        placeholder="21.5",
        key="temperature",
    )

    if temperature is not None:
        suggested = result.suggested_ctp_protocol
        # Pre-selected from the address's country and overridable at any time.
        # The toggle lives here rather than in panel 1 because it has no
        # bearing whatsoever on the corrected pressure; putting it up there
        # would imply the pressure depends on the protocol, which it does not.
        protocol = st.radio(
            "Reference protocol",
            options=PROTOCOL_CHOICES,
            index=PROTOCOL_CHOICES.index(suggested),
            format_func=lambda p: PROTOCOL_CAPTION[p],
            horizontal=True,
            key="protocol",
        )
        overridden = protocol is not suggested
        try:
            # Pure arithmetic over the cached result: no refetch, so the
            # toggle and the temperature both recompute instantly.
            ctp_result = service.ctp_for(
                result, float(temperature), protocol=protocol if overridden else None
            )
        except BaromeError as exc:
            st.error(str(exc))

    if ctp_result is not None:
        st.metric(
            label=(
                f"Ctp — {ctp_result.protocol}, "
                f"{REFERENCE_TEMP_C[ctp_result.protocol]:g} °C reference"
            ),
            value=f"{ctp_result.ctp:.4f}",
        )
        st.caption(
            f"{ctp_result.protocol_reason}. With {ctp_result.other_protocol} "
            f"({REFERENCE_TEMP_C[ctp_result.other_protocol]:g} °C) instead: "
            f"{ctp_result.ctp_other_protocol:.4f} ({ctp_result.other_delta_pct:+.2f}%)."
        )
        for warning in ctp_result.warnings:
            st.warning(warning, icon="⚠️")
        with st.expander("Show your work"):
            st.code(
                render_steps(ctp_result.trace, start_number=len(result.trace) + 1),
                language="text",
            )

    st.divider()

    # =====================================================================
    # PANEL 3 - INTERCOMPARISON
    # =====================================================================

    st.subheader("Intercomparison")
    st.caption(
        "Optional. How far is the Ctp from your own barometer and thermometer "
        "from the one calculated above?"
    )

    if ctp_result is None:
        st.info("Enter a temperature above first — the comparison is between two Ctp values.")
    else:
        left, right = st.columns([2, 1])
        local_pressure = left.number_input(
            "Your measured pressure",
            value=None,
            step=0.1,
            format="%.2f",
            placeholder="757.0",
            key="local_pressure",
        )
        # The unit dropdown is not a convenience: a clinic barometer reading
        # 1013 hPa typed into a field expecting mmHg is a silent 33% error
        # that produces a plausible-looking number.
        local_unit = right.selectbox("Unit", options=list(PRESSURE_UNITS), key="local_unit")

        local_temp = st.number_input(
            "Your measured temperature (°C) — optional",
            value=None,
            step=0.1,
            format="%.2f",
            placeholder=f"blank = reuse {ctp_result.temperature_c:g} °C from above",
            key="local_temp",
        )

        if local_pressure is None:
            st.caption("Enter your barometer's reading to compare.")
        else:
            try:
                comparison = service.compare_local(
                    ctp_result,
                    float(local_pressure),
                    local_unit,
                    None if local_temp is None else float(local_temp),
                )
            except BaromeError as exc:
                st.error(str(exc))

        if comparison is not None:
            inherited = (
                " (inherited from the Ctp panel)" if comparison.local_temp_inherited else ""
            )
            st.caption(
                f"Your readings: {comparison.local_pressure_mmhg:.2f} mmHg "
                f"(entered as {comparison.local_pressure_input:g} "
                f"{comparison.local_pressure_unit}), "
                f"{comparison.local_temp_c:g} °C{inherited}"
            )
            # One reported quantity: the Ctp difference. Not pressure, not
            # temperature — those are inputs, echoed above for verification.
            a, b, c = st.columns(3)
            a.metric("Ctp calculated", f"{comparison.ctp_calculated:.4f}")
            b.metric("Ctp yours", f"{comparison.ctp_local:.4f}")
            c.metric(
                "Difference",
                f"{comparison.d_ctp:+.4f}",
                delta=f"{comparison.d_ctp_pct:+.3f}%",
                delta_color="off",
            )
            st.caption(
                f"Both at {comparison.protocol}, "
                f"{REFERENCE_TEMP_C[comparison.protocol]:g} °C reference — inherited from "
                "the Ctp panel, so this is an instrument difference only."
            )
            for warning in comparison.warnings:
                st.warning(warning, icon="⚠️")
            with st.expander("Show your work"):
                st.code(
                    render_steps(
                        comparison.trace,
                        start_number=len(result.trace) + len(ctp_result.trace) + 1,
                    ),
                    language="text",
                )

    # =====================================================================
    # The whole record - only the panels actually filled in
    # =====================================================================

    st.divider()
    with st.expander("Copy the whole record as text"):
        st.caption(
            "Paste-ready for a QA log. Only the panels you filled in are included."
        )
        st.code(render_full_trace(result, ctp_result, comparison), language="text")

st.divider()
st.caption(
    "A convenience calculator whose sources are always shown so you can verify them. "
    "Not a medical device, and it makes no clinical judgement — including on whether "
    "any Ctp difference is acceptable."
)
