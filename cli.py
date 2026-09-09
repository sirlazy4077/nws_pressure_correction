#!/usr/bin/env python3
"""BaroMe command line front end.

Thin by design: it prompts, it prints, and it calls `barome.service`. Every
calculation lives in the library, so this file and the web app can never
disagree about a number.

    python cli.py "123 Main St, Doylestown PA 18901"
    python cli.py --temp 21.5 --trace
    python cli.py --temp 21.5 --compare-pressure 757 --compare-unit mmHg
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from barome import service  # noqa: E402
from barome.errors import BaromeError  # noqa: E402
from barome.physics import PRESSURE_UNITS, Method  # noqa: E402
from barome.render import (  # noqa: E402
    render_comparison,
    render_ctp,
    render_full_trace,
    render_summary,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="barome",
        description=(
            "Elevation-adjusted local barometric pressure and Ctp, from your address alone."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("address", nargs="?", help="Your address. Prompted for if omitted.")
    parser.add_argument(
        "--temp",
        type=float,
        metavar="C",
        help="Vault temperature in Celsius. Adds the Ctp panel.",
    )
    parser.add_argument(
        "--protocol",
        choices=["tg-51", "trs-398"],
        help=(
            "Ctp reference protocol. Omitted, it is auto-selected from the address's "
            "country (US -> TG-51, elsewhere -> TRS-398) and the reason is printed."
        ),
    )
    parser.add_argument(
        "--provider",
        choices=["wunderground", "openmeteo", "nws"],
        default=service.DEFAULT_PROVIDER,
        help="Preferred pressure source. Falls back automatically if it is unavailable.",
    )
    parser.add_argument(
        "--method",
        choices=[Method.BAROMETRIC.value, Method.LINEAR.value],
        default=Method.BAROMETRIC.value,
        help="Elevation correction. Barometric is the standard atmosphere; linear is "
        "the legacy 1 inHg/1000 ft rule of thumb, kept only for reproducing old records.",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Print the full calculation chain, paste-ready for a QA log.",
    )
    parser.add_argument("--compare-pressure", type=float, metavar="P",
                        help="Your own barometer's reading, for the intercomparison.")
    parser.add_argument("--compare-unit", default="mmHg", choices=list(PRESSURE_UNITS),
                        help="Unit of --compare-pressure. Default mmHg.")
    parser.add_argument("--compare-temp", type=float, metavar="C",
                        help="Your own thermometer's reading. Omitted, --temp is reused.")
    return parser


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        # A bare `except:` in the old code swallowed these, so Ctrl-C would not
        # reliably quit the prompt. Exit cleanly instead.
        print("\nCancelled.")
        raise SystemExit(130) from None


def _ask_float(prompt: str) -> float | None:
    raw = _ask(prompt)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        print(f"  '{raw}' is not a number. Skipping.")
        return None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    address = args.address or _ask("Your address: ")
    if not address:
        print("An address is required.")
        return 2

    try:
        result = service.pressure_for_address(
            address,
            provider=args.provider,
            method=Method(args.method),
        )
    except BaromeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print()
    print(render_summary(result))
    print()

    for warning in result.warnings:
        print(f"  ! {warning}")
    if result.warnings:
        print()

    # --- Ctp ------------------------------------------------------------
    temperature = args.temp
    if temperature is None and args.address is None:
        temperature = _ask_float("Vault temperature in °C (blank to skip Ctp): ")

    ctp_result = None
    if temperature is not None:
        try:
            ctp_result = service.ctp_for(result, temperature, protocol=args.protocol)
        except BaromeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(render_ctp(ctp_result))
        print()
        for warning in ctp_result.warnings:
            print(f"  ! {warning}")

    # --- Intercomparison -------------------------------------------------
    comparison = None
    if ctp_result is not None and args.compare_pressure is not None:
        try:
            comparison = service.compare_local(
                ctp_result,
                args.compare_pressure,
                args.compare_unit,
                args.compare_temp,
            )
        except BaromeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print("Intercomparison")
        print(render_comparison(comparison))
        print()
        for warning in comparison.warnings:
            print(f"  ! {warning}")
    elif args.compare_pressure is not None:
        print(
            "  ! --compare-pressure needs a temperature too: add --temp.",
            file=sys.stderr,
        )

    if args.trace:
        print()
        print(render_full_trace(result, ctp_result, comparison))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
