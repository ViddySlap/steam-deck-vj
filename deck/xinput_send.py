"""Watch `xinput test` output and send mapped action events over UDP."""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import termios
from dataclasses import dataclass

from protocol.messages import encode_action_event


EVENT_HEADER_RE = re.compile(r"^EVENT type \d+ \((KeyPress|KeyRelease)\)$")
DETAIL_RE = re.compile(r"^\s*detail:\s+(\d+)$")
FLAGS_RE = re.compile(r"^\s*flags:\s*(.*)$")


@dataclass(frozen=True)
class Xi2KeyEvent:
    keycode: str
    state: str
    is_repeat: bool = False


class TerminalNoEcho:
    def __enter__(self) -> "TerminalNoEcho":
        self._fd: int | None = None
        self._old_attrs = None
        if not sys.stdin.isatty():
            return self
        self._fd = sys.stdin.fileno()
        self._old_attrs = termios.tcgetattr(self._fd)
        new_attrs = termios.tcgetattr(self._fd)
        new_attrs[3] &= ~(termios.ECHO | termios.ICANON)
        termios.tcsetattr(self._fd, termios.TCSADRAIN, new_attrs)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is None or self._old_attrs is None:
            return
        termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_attrs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Watch xinput key events and send mapped action events"
    )
    parser.add_argument("--device-id", required=True, help="xinput device id")
    parser.add_argument(
        "--bindings",
        required=True,
        help="path to deck_bindings.json containing keycode-to-action bindings",
    )
    parser.add_argument(
        "--target",
        required=True,
        help="receiver address in host:port form, for example 10.10.10.15:45123",
    )
    parser.add_argument(
        "--profile-name",
        default=None,
        help="override the profile_name sent over the network",
    )
    parser.add_argument(
        "--profile-hash",
        default=None,
        help="optional profile hash sent over the network",
    )
    return parser


def parse_target(value: str) -> tuple[str, int]:
    host, port_text = value.rsplit(":", 1)
    return host, int(port_text)


def load_bindings(path: str) -> tuple[str | None, dict[str, str]]:
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    profile_name = raw.get("profile_name")
    bindings = raw.get("bindings")
    if profile_name is not None and not isinstance(profile_name, str):
        raise ValueError("profile_name must be a string when provided")
    if not isinstance(bindings, dict):
        raise ValueError("bindings file must contain an object at 'bindings'")

    validated: dict[str, str] = {}
    for token, action in bindings.items():
        if not isinstance(token, str) or not token:
            raise ValueError("binding tokens must be non-empty strings")
        if not isinstance(action, str) or not action:
            raise ValueError("binding actions must be non-empty strings")
        validated[token] = action
    return profile_name, validated


def parse_xi2_event_block(block: list[str]) -> Xi2KeyEvent | None:
    if not block:
        return None

    match = EVENT_HEADER_RE.match(block[0].strip())
    if match is None:
        return None

    state_name = match.group(1)
    keycode: str | None = None
    flags = ""
    for line in block[1:]:
        detail_match = DETAIL_RE.match(line)
        if detail_match is not None:
            keycode = detail_match.group(1)
            continue
        flags_match = FLAGS_RE.match(line)
        if flags_match is not None:
            flags = flags_match.group(1).strip()

    if keycode is None:
        return None

    return Xi2KeyEvent(
        keycode=keycode,
        state="down" if state_name == "KeyPress" else "up",
        is_repeat="repeat" in flags.split(),
    )


def should_emit_event(event: Xi2KeyEvent, held_keys: set[str]) -> bool:
    if event.state == "down":
        if event.is_repeat or event.keycode in held_keys:
            return False
        held_keys.add(event.keycode)
        return True

    if event.keycode not in held_keys:
        return False
    held_keys.remove(event.keycode)
    return True


def flush_block(
    block: list[str],
    bindings: dict[str, str],
    held_keys: set[str],
) -> tuple[Xi2KeyEvent | None, str | None]:
    parsed = parse_xi2_event_block(block)
    if parsed is None:
        return None, None

    action = bindings.get(parsed.keycode)
    if action is None:
        return None, None

    if not should_emit_event(parsed, held_keys):
        return None, None

    return parsed, action


def send_action(
    sock: socket.socket,
    target: tuple[str, int],
    *,
    action: str,
    state: str,
    seq: int,
    profile_name: str | None,
    profile_hash: str | None,
) -> None:
    payload = encode_action_event(
        action=action,
        state=state,
        seq=seq,
        profile_name=profile_name,
        profile_hash=profile_hash,
    )
    sock.sendto(payload, target)
    print(f"sent action={action} state={state} seq={seq}")


def run_sender(
    *,
    device_id: str,
    bindings_path: str,
    target: str,
    profile_name: str | None,
    profile_hash: str | None,
) -> int:
    try:
        loaded_profile_name, bindings = load_bindings(bindings_path)
        resolved_target = parse_target(target)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}")
        return 2

    resolved_profile_name = profile_name or loaded_profile_name
    seq = 1
    held_keys: set[str] = set()

    try:
        process = subprocess.Popen(
            ["xinput", "test-xi2", "--root"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        print(f"Error: failed to start xinput: {exc}")
        return 2

    print(f"watching X11 XI2 root events and sending to {target}")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        with TerminalNoEcho():
            try:
                assert process.stdout is not None
                block: list[str] = []
                for raw_line in process.stdout:
                    line = raw_line.rstrip("\n")
                    if line.startswith("EVENT type ") and block:
                        parsed, action = flush_block(block, bindings, held_keys)
                        block = []
                        if parsed is not None and action is not None:
                            send_action(
                                sock,
                                resolved_target,
                                action=action,
                                state=parsed.state,
                                seq=seq,
                                profile_name=resolved_profile_name,
                                profile_hash=profile_hash,
                            )
                            seq += 1

                    if line.strip():
                        block.append(line)
                        continue

                    parsed, action = flush_block(block, bindings, held_keys)
                    block = []
                    if parsed is not None and action is not None:
                        send_action(
                            sock,
                            resolved_target,
                            action=action,
                            state=parsed.state,
                            seq=seq,
                            profile_name=resolved_profile_name,
                            profile_hash=profile_hash,
                        )
                        seq += 1

                parsed, action = flush_block(block, bindings, held_keys)
                if parsed is not None and action is not None:
                    send_action(
                        sock,
                        resolved_target,
                        action=action,
                        state=parsed.state,
                        seq=seq,
                        profile_name=resolved_profile_name,
                        profile_hash=profile_hash,
                    )
            except KeyboardInterrupt:
                print("stopping sender")
            finally:
                process.terminate()
                process.wait(timeout=2)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    return run_sender(
        device_id=args.device_id,
        bindings_path=args.bindings,
        target=args.target,
        profile_name=args.profile_name,
        profile_hash=args.profile_hash,
    )


if __name__ == "__main__":
    sys.exit(main())
