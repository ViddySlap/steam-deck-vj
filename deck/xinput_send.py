"""Watch `xinput test` output and send mapped action events over UDP."""

from __future__ import annotations

import argparse
import json
import re
import selectors
import shutil
import socket
import subprocess
import sys
import termios
import time
from dataclasses import dataclass

from protocol.messages import encode_action_event, encode_heartbeat_event


EVENT_HEADER_RE = re.compile(r"^EVENT type \d+ \((RawKeyPress|RawKeyRelease)\)$")
DETAIL_RE = re.compile(r"^\s*detail:\s+(\d+)$")
HEARTBEAT_INTERVAL_SECONDS = 0.5


@dataclass(frozen=True)
class Xi2KeyEvent:
    keycode: str
    state: str


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
    for line in block[1:]:
        detail_match = DETAIL_RE.match(line)
        if detail_match is not None:
            keycode = detail_match.group(1)

    if keycode is None:
        return None

    return Xi2KeyEvent(
        keycode=keycode,
        state="down" if state_name == "RawKeyPress" else "up",
    )


def is_complete_xi2_event_block(block: list[str]) -> bool:
    if not block:
        return False
    if EVENT_HEADER_RE.match(block[0].strip()) is None:
        return False
    return any(DETAIL_RE.match(line) for line in block[1:])


def should_emit_event(event: Xi2KeyEvent, held_keys: set[str]) -> bool:
    if event.state == "down":
        if event.keycode in held_keys:
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


def next_select_timeout(
    *,
    held_keys: set[str],
    block: list[str],
    next_heartbeat_at: float,
    now: float,
) -> float | None:
    if block:
        # Finish the current XI2 event block before considering heartbeat traffic.
        return None
    if not held_keys:
        return None
    return max(0.0, next_heartbeat_at - now)


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


def send_heartbeat(
    sock: socket.socket,
    target: tuple[str, int],
    *,
    seq: int,
    profile_name: str | None,
    profile_hash: str | None,
) -> None:
    payload = encode_heartbeat_event(
        seq=seq,
        profile_name=profile_name,
        profile_hash=profile_hash,
    )
    sock.sendto(payload, target)


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
    xinput_command = ["xinput", "test-xi2", str(device_id)]
    if shutil.which("script") is not None:
        xinput_command = [
            "script",
            "-qfec",
            f"xinput test-xi2 {device_id}",
            "/dev/null",
        ]

    try:
        process = subprocess.Popen(
            xinput_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        print(f"Error: failed to start xinput: {exc}")
        return 2

    print(f"watching XI2 raw key events for device {device_id} and sending to {target}")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        with TerminalNoEcho():
            try:
                selector = selectors.DefaultSelector()
                assert process.stdout is not None
                selector.register(process.stdout, selectors.EVENT_READ)
                block: list[str] = []
                next_heartbeat_at = time.monotonic() + HEARTBEAT_INTERVAL_SECONDS
                while True:
                    now = time.monotonic()
                    timeout = next_select_timeout(
                        held_keys=held_keys,
                        block=block,
                        next_heartbeat_at=next_heartbeat_at,
                        now=now,
                    )
                    events = selector.select(timeout)
                    if not events:
                        send_heartbeat(
                            sock,
                            resolved_target,
                            seq=seq,
                            profile_name=resolved_profile_name,
                            profile_hash=profile_hash,
                        )
                        seq += 1
                        next_heartbeat_at = time.monotonic() + HEARTBEAT_INTERVAL_SECONDS
                        continue

                    raw_line = process.stdout.readline()
                    if raw_line == "":
                        break
                    line = raw_line.rstrip("\r\n")
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
                            next_heartbeat_at = time.monotonic() + HEARTBEAT_INTERVAL_SECONDS

                    if line.strip():
                        block.append(line)
                        if is_complete_xi2_event_block(block):
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
                                next_heartbeat_at = time.monotonic() + HEARTBEAT_INTERVAL_SECONDS
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
                        next_heartbeat_at = time.monotonic() + HEARTBEAT_INTERVAL_SECONDS

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
                selector.close()
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
