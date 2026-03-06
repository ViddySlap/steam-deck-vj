"""Interactive launcher for the Deck sender preset workflow."""

from __future__ import annotations

import argparse
import os
import sys

from deck.local_config import (
    describe_preset,
    ensure_local_settings,
    save_runtime_settings,
    with_added_preset,
)
from deck.xinput_send import run_sender


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch STEAMDECK-MIDI-SENDER")
    parser.add_argument(
        "--settings",
        default="config/deck_runtime_settings.local.json",
        help="path to deck runtime settings JSON",
    )
    parser.add_argument(
        "--settings-example",
        default="config/deck_runtime_settings.example.json",
        help="path to example deck runtime settings JSON",
    )
    parser.add_argument(
        "--preset-index",
        type=int,
        default=None,
        help="1-based preset index for non-interactive startup",
    )
    return parser

def prompt_new_preset(settings_path: str, settings):
    print("")
    print("Create New Preset")
    while True:
        host = input("What is your target IP address? ").strip()
        name = input("What is the name of the target? ").strip()
        try:
            updated = with_added_preset(settings, name=name, host=host)
        except ValueError as exc:
            print(f"Error: {exc}")
            print("Try again.")
            print("")
            continue
        save_runtime_settings(settings_path, updated)
        print(f"Saved preset: {updated.presets[-1].name} ({updated.presets[-1].host})")
        return updated


def prompt_for_preset(settings_path: str, settings, device_id: str):
    while True:
        print("")
        print("STEAMDECK-MIDI-SENDER")
        print(f"Bindings: {settings.bindings_path}")
        print(f"Device ID: {device_id}")
        print("")
        print("Select a target preset:")
        if settings.presets:
            for index, preset in enumerate(settings.presets, start=1):
                print(describe_preset(index, preset))
        else:
            print("No presets saved yet.")
        create_index = len(settings.presets) + 1
        print(f"{create_index}. Create new preset")
        print("q. Quit")
        print("")

        choice = input("Selection: ").strip().lower()
        if choice == "q":
            return None, settings
        if choice == str(create_index):
            settings = prompt_new_preset(settings_path, settings)
            continue
        try:
            selected_index = int(choice)
        except ValueError:
            print("Invalid selection.")
            continue
        if 1 <= selected_index <= len(settings.presets):
            return settings.presets[selected_index - 1], settings
        print("Invalid selection.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = ensure_local_settings(args.settings, args.settings_example)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2

    if not os.path.exists(settings.bindings_path):
        parser.error(
            f"bindings file not found: {settings.bindings_path}. Run Learn Steam Input Map first."
        )
        return 2

    device_id = settings.device_id or "5"
    if args.preset_index is not None:
        index = args.preset_index
        if index < 1 or index > len(settings.presets):
            parser.error(
                f"--preset-index {index} is out of range; presets available: {len(settings.presets)}"
            )
            return 2
        preset = settings.presets[index - 1]
        print("")
        print("STEAMDECK-MIDI-SENDER")
        print(f"Bindings: {settings.bindings_path}")
        print(f"Device ID: {device_id}")
        print(f"Using preset index: {index}")
    else:
        preset, settings = prompt_for_preset(args.settings, settings, device_id)
        if preset is None:
            print("Sender cancelled.")
            return 0

    target = f"{preset.host}:{preset.port}"
    print("")
    print(f"Starting sender for preset: {preset.name}")
    print(f"Target: {target}")
    print("")
    return run_sender(
        device_id=device_id,
        bindings_path=settings.bindings_path,
        target=target,
        profile_name=settings.profile_name,
        profile_hash=settings.profile_hash,
    )


if __name__ == "__main__":
    sys.exit(main())
