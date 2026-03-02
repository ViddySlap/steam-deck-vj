"""CLI entrypoint for the Windows UDP receiver."""

from __future__ import annotations

import argparse
import logging
import sys

from windows.config import ConfigError, load_midi_map
from windows.midi import MidiError, open_midi_output
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
        required=True,
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
        listen_host, listen_port = parse_listen(args.listen)
        mappings = load_midi_map(args.map_path)
        midi_out = open_midi_output(args.midi_port, args.dry_run)
    except (argparse.ArgumentTypeError, ConfigError, MidiError) as exc:
        parser.error(str(exc))
        return 2

    logging.info(
        "selected MIDI output port: name=%s index=%s",
        midi_out.port_name,
        midi_out.port_index if midi_out.port_index is not None else "n/a",
    )

    receiver = ActionReceiver(midi_out, mappings, timeout_seconds=args.timeout)
    try:
        serve_forever(listen_host, listen_port, receiver)
    finally:
        midi_out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
