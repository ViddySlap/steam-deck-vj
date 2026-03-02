"""Print available MIDI output ports."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        import mido
    except ImportError:
        print("mido is not installed. Run: pip install -r requirements.txt")
        return 1

    ports = mido.get_output_names()
    if not ports:
        print("No MIDI output ports found.")
        return 1

    print("Available MIDI output ports:")
    for index, port in enumerate(ports):
        print(f"- [{index}] {port}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
