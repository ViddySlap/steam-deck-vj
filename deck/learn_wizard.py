"""Interactive CLI wizard for capturing Deck keycodes from `xinput test`."""

from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import subprocess
import sys
import tempfile
import termios
import tty
from dataclasses import dataclass


KEY_PRESS_RE = re.compile(r"^key press\s+(\d+)$")


@dataclass(frozen=True)
class LearnCandidate:
    token: str


class TerminalCbreak:
    def __enter__(self) -> "TerminalCbreak":
        self._fd = sys.stdin.fileno()
        self._old_attrs = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_attrs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture Steam Deck xinput keycodes and write deck bindings"
    )
    parser.add_argument("--device-id", required=True, help="xinput device id")
    parser.add_argument(
        "--actions",
        required=True,
        help="path to actions.yaml containing the action list",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="output path for deck_bindings.json",
    )
    parser.add_argument(
        "--profile-name",
        default="default",
        help="profile name to store in the bindings file",
    )
    return parser


def load_actions(path: str) -> list[str]:
    actions: list[str] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or line == "actions:":
                    continue
                if not line.startswith("- "):
                    raise ValueError(f"unsupported actions line: {raw_line.rstrip()}")
                action = line[2:].strip()
                if not action:
                    raise ValueError("action names must be non-empty")
                actions.append(action)
    except FileNotFoundError as exc:
        raise ValueError(f"actions file not found: {path}") from exc

    if not actions:
        raise ValueError("no actions found in actions file")
    return actions


def parse_key_press(line: str) -> LearnCandidate | None:
    match = KEY_PRESS_RE.match(line.strip())
    if match is None:
        return None
    return LearnCandidate(token=match.group(1))


def find_duplicate_action(bindings: dict[str, str], token: str) -> str | None:
    for action, bound_token in bindings.items():
        if bound_token == token:
            return action
    return None


def is_skip_input(chars: bytes) -> bool:
    return b"s" in chars.lower()


def write_bindings(path: str, profile_name: str, bindings: dict[str, str]) -> None:
    if os.path.isdir(path):
        raise ValueError(
            f"output path points to a directory, not a file: {path}"
        )

    payload = {
        "profile_name": profile_name,
        "bindings": {token: action for action, token in bindings.items()},
    }

    directory = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=directory
    ) as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        temp_path = handle.name
    os.replace(temp_path, path)


def print_header(device_id: str, output_path: str) -> None:
    print("Steam Deck Learn Wizard")
    print(f"Listening to xinput device: {device_id}")
    print(f"Output file: {output_path}")
    print("Instructions:")
    print("- Press the Steam Deck control you want to map")
    print("- Watch the latest captured keycode")
    print("- Press Enter to confirm the latest captured keycode")
    print("- Press S to skip the current action and leave it unmapped")
    print("- Press Ctrl+X at any time to exit without saving")
    print("- If you hit Enter too early, the wizard will warn and keep waiting")
    print("")


def prompt_action(action: str) -> None:
    print("")
    print(f"Map action: {action}")
    print("Waiting for key press, or press S to skip...")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        actions = load_actions(args.actions)
        if os.path.isdir(args.out):
            raise ValueError(f"--out must be a file path, not a directory: {args.out}")
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    try:
        process = subprocess.Popen(
            ["xinput", "test", str(args.device_id)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        parser.error(f"failed to start xinput: {exc}")
        return 2

    bindings: dict[str, str] = {}
    candidate: LearnCandidate | None = None
    action_index = 0

    selector = selectors.DefaultSelector()
    selector.register(sys.stdin, selectors.EVENT_READ, "stdin")
    assert process.stdout is not None
    selector.register(process.stdout, selectors.EVENT_READ, "xinput")

    print_header(args.device_id, args.out)
    prompt_action(actions[action_index])

    with TerminalCbreak():
        try:
            while action_index < len(actions):
                for key, _ in selector.select():
                    if key.data == "xinput":
                        line = key.fileobj.readline()
                        if line == "":
                            raise RuntimeError("xinput test exited unexpectedly")
                        parsed = parse_key_press(line)
                        if parsed is None:
                            continue
                        candidate = parsed
                        duplicate_action = find_duplicate_action(
                            bindings, candidate.token
                        )
                        print(
                            f"Latest candidate for {actions[action_index]}: keycode {candidate.token}"
                        )
                        if duplicate_action is not None:
                            print(
                                f"Warning: keycode {candidate.token} is already assigned to {duplicate_action}"
                            )
                    else:
                        chars = os.read(sys.stdin.fileno(), 8)
                        if b"\x18" in chars:
                            print("")
                            print("Wizard cancelled. No bindings were written.")
                            return 1
                        if is_skip_input(chars):
                            current_action = actions[action_index]
                            print(f"Skipped: {current_action}")
                            candidate = None
                            action_index += 1
                            if action_index < len(actions):
                                prompt_action(actions[action_index])
                            continue
                        if b"\n" not in chars and b"\r" not in chars:
                            continue
                        if candidate is None:
                            print("Warning: no candidate captured yet. Try again.")
                            continue

                        current_action = actions[action_index]
                        bindings[current_action] = candidate.token
                        print(
                            f"Confirmed: {current_action} <- keycode {candidate.token}"
                        )
                        candidate = None
                        action_index += 1
                        if action_index < len(actions):
                            prompt_action(actions[action_index])
            write_bindings(args.out, args.profile_name, bindings)
        except ValueError as exc:
            print("")
            print(f"Error: {exc}")
            return 2
        except KeyboardInterrupt:
            print("")
            print("Wizard cancelled. No bindings were written.")
            return 1
        finally:
            selector.close()
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()

    print("")
    print(f"Wrote bindings to {args.out}")
    print("Summary:")
    for action in actions:
        token = bindings.get(action, "(skipped)")
        print(f"- {action}: {token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
