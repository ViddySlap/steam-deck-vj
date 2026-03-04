"""CLI entrypoint for the Windows UDP receiver."""

from __future__ import annotations

import argparse
import logging
import sys

from windows.config import ConfigError, load_midi_map
from windows.midi import (
    MidiError,
    format_output_port_list,
    get_output_port_names,
    open_midi_output,
    resolve_available_output_port_name,
)
from windows.receiver import ActionReceiver, serve_forever


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Receive action events and emit MIDI")
    parser.add_argument(
        "--listen",
        default="0.0.0.0:45123",
        help="listen address in host:port form (default: 0.0.0.0:45123)",
    )
    parser.add_argument(
        "--midi-port",
        default="DECK_IN",
        help='Windows MIDI output port name (default: "DECK_IN")',
    )
    parser.add_argument(
        "--map",
        dest="map_path",
        help="path to windows_midi_map.json",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=2.0,
        help="seconds before active notes/controls are released",
    )
    parser.add_argument("--dry-run", action="store_true", help="log MIDI output only")
    parser.add_argument("--verbose", action="store_true", help="enable verbose logging")
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="list available MIDI output ports and exit",
    )
    parser.add_argument(
        "--check-midi-port",
        action="store_true",
        help="validate the configured MIDI port and exit",
    )
    return parser


def parse_listen(value: str) -> tuple[str, int]:
    try:
        host, port_text = value.rsplit(":", 1)
        return host, int(port_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("listen must be in host:port form") from exc


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    try:
        if args.list_ports:
            port_names = get_output_port_names()
            if not port_names:
                print("No MIDI output ports found.")
                return 1
            print("Available MIDI output ports:")
            for index, port_name in enumerate(port_names):
                print(f"- [{index}] {port_name}")
            return 0

        if args.check_midi_port:
            resolved_port_name = resolve_available_output_port_name(args.midi_port)
            print(
                "MIDI output port is available:"
                f" requested={args.midi_port} resolved={resolved_port_name}"
            )
            return 0

        if not args.map_path:
            raise ConfigError("--map is required unless --list-ports or --check-midi-port is used")

        listen_host, listen_port = parse_listen(args.listen)
        receiver_config = load_midi_map(args.map_path)
        midi_out = open_midi_output(args.midi_port, args.dry_run)
    except (argparse.ArgumentTypeError, ConfigError, MidiError) as exc:
        parser.error(str(exc))
        return 2

    logging.info(
        "selected MIDI output port: name=%s index=%s",
        midi_out.port_name,
        midi_out.port_index if midi_out.port_index is not None else "n/a",
    )

    receiver = ActionReceiver(
        midi_out,
        receiver_config.mappings,
        timeout_seconds=args.timeout,
        macro_settings=receiver_config.macro_settings,
    )
    try:
        serve_forever(listen_host, listen_port, receiver)
    finally:
        midi_out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
