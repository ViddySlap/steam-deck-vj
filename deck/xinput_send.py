"""Listen for X11 XI2 raw key events and send mapped action events over UDP."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import selectors
import socket
import sys
import termios
import time
from dataclasses import dataclass

from protocol.messages import encode_action_event, encode_heartbeat_event


HEARTBEAT_INTERVAL_SECONDS = 0.5
GENERIC_EVENT = 35
XI_RAW_KEY_PRESS = 13
XI_RAW_KEY_RELEASE = 14
SENDER_AUDIT_ACTIONS = (
    "L2_SOFT",
    "L2_FULL",
    "R2_SOFT",
    "R2_FULL",
    "L2_SOFT_LAYER_2",
    "L2_FULL_LAYER_2",
    "R2_SOFT_LAYER_2",
    "R2_FULL_LAYER_2",
    "L4",
    "L5",
    "R4",
    "R5",
)


def _load_library(name: str) -> ctypes.CDLL:
    path = ctypes.util.find_library(name)
    if path is None:
        raise OSError(f"failed to locate shared library: {name}")
    return ctypes.CDLL(path)


_LIB_X11 = _load_library("X11")
_LIB_XI = _load_library("Xi")


class XGenericEventCookie(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("extension", ctypes.c_int),
        ("evtype", ctypes.c_int),
        ("cookie", ctypes.c_uint),
        ("data", ctypes.c_void_p),
    ]


class XEvent(ctypes.Union):
    _fields_ = [
        ("type", ctypes.c_int),
        ("xcookie", XGenericEventCookie),
        ("pad", ctypes.c_long * 24),
    ]


class XIEventMask(ctypes.Structure):
    _fields_ = [
        ("deviceid", ctypes.c_int),
        ("mask_len", ctypes.c_int),
        ("mask", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class XIRawEventHead(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("extension", ctypes.c_int),
        ("evtype", ctypes.c_int),
        ("time", ctypes.c_ulong),
        ("deviceid", ctypes.c_int),
        ("sourceid", ctypes.c_int),
        ("detail", ctypes.c_int),
    ]


_LIB_X11.XOpenDisplay.argtypes = [ctypes.c_char_p]
_LIB_X11.XOpenDisplay.restype = ctypes.c_void_p
_LIB_X11.XCloseDisplay.argtypes = [ctypes.c_void_p]
_LIB_X11.XCloseDisplay.restype = ctypes.c_int
_LIB_X11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
_LIB_X11.XDefaultRootWindow.restype = ctypes.c_ulong
_LIB_X11.XQueryExtension.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
]
_LIB_X11.XQueryExtension.restype = ctypes.c_int
_LIB_X11.XConnectionNumber.argtypes = [ctypes.c_void_p]
_LIB_X11.XConnectionNumber.restype = ctypes.c_int
_LIB_X11.XPending.argtypes = [ctypes.c_void_p]
_LIB_X11.XPending.restype = ctypes.c_int
_LIB_X11.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.POINTER(XEvent)]
_LIB_X11.XNextEvent.restype = ctypes.c_int
_LIB_X11.XGetEventData.argtypes = [ctypes.c_void_p, ctypes.POINTER(XGenericEventCookie)]
_LIB_X11.XGetEventData.restype = ctypes.c_int
_LIB_X11.XFreeEventData.argtypes = [ctypes.c_void_p, ctypes.POINTER(XGenericEventCookie)]
_LIB_X11.XFreeEventData.restype = None
_LIB_X11.XFlush.argtypes = [ctypes.c_void_p]
_LIB_X11.XFlush.restype = ctypes.c_int

_LIB_XI.XIQueryVersion.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
]
_LIB_XI.XIQueryVersion.restype = ctypes.c_int
_LIB_XI.XISelectEvents.argtypes = [
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.POINTER(XIEventMask),
    ctypes.c_int,
]
_LIB_XI.XISelectEvents.restype = ctypes.c_int


@dataclass(frozen=True)
class Xi2KeyEvent:
    keycode: str
    state: str


class Xi2RawListener:
    def __init__(self, device_id: int) -> None:
        self._device_id = device_id
        self._display = _LIB_X11.XOpenDisplay(None)
        if not self._display:
            raise OSError("failed to open X display")

        self._extension_opcode = ctypes.c_int()
        first_event = ctypes.c_int()
        first_error = ctypes.c_int()
        found = _LIB_X11.XQueryExtension(
            self._display,
            b"XInputExtension",
            ctypes.byref(self._extension_opcode),
            ctypes.byref(first_event),
            ctypes.byref(first_error),
        )
        if found == 0:
            self.close()
            raise OSError("X Input extension is not available")

        major = ctypes.c_int(2)
        minor = ctypes.c_int(0)
        if _LIB_XI.XIQueryVersion(self._display, ctypes.byref(major), ctypes.byref(minor)) != 0:
            self.close()
            raise OSError("XI2 is not available on this display")

        root = _LIB_X11.XDefaultRootWindow(self._display)
        mask_bytes = (ctypes.c_ubyte * 2)()
        set_mask(mask_bytes, XI_RAW_KEY_PRESS)
        set_mask(mask_bytes, XI_RAW_KEY_RELEASE)
        event_mask = XIEventMask(
            deviceid=self._device_id,
            mask_len=len(mask_bytes),
            mask=ctypes.cast(mask_bytes, ctypes.POINTER(ctypes.c_ubyte)),
        )
        if _LIB_XI.XISelectEvents(self._display, root, ctypes.byref(event_mask), 1) != 0:
            self.close()
            raise OSError("failed to select XI2 events")
        _LIB_X11.XFlush(self._display)

    def fileno(self) -> int:
        return _LIB_X11.XConnectionNumber(self._display)

    def read_event(self) -> Xi2KeyEvent | None:
        while _LIB_X11.XPending(self._display) > 0:
            event = XEvent()
            _LIB_X11.XNextEvent(self._display, ctypes.byref(event))
            if event.type != GENERIC_EVENT:
                continue
            if event.xcookie.extension != self._extension_opcode.value:
                continue
            if event.xcookie.evtype not in (XI_RAW_KEY_PRESS, XI_RAW_KEY_RELEASE):
                continue
            if _LIB_X11.XGetEventData(self._display, ctypes.byref(event.xcookie)) == 0:
                continue
            try:
                raw = ctypes.cast(event.xcookie.data, ctypes.POINTER(XIRawEventHead)).contents
                if raw.deviceid != self._device_id:
                    continue
                return Xi2KeyEvent(
                    keycode=str(raw.detail),
                    state="down" if event.xcookie.evtype == XI_RAW_KEY_PRESS else "up",
                )
            finally:
                _LIB_X11.XFreeEventData(self._display, ctypes.byref(event.xcookie))
        return None

    def close(self) -> None:
        if getattr(self, "_display", None):
            _LIB_X11.XCloseDisplay(self._display)
            self._display = None


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
        description="Watch XI2 raw key events and send mapped action events"
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


def build_action_token_index(bindings: dict[str, str]) -> dict[str, list[str]]:
    action_tokens: dict[str, list[str]] = {}
    for token, action in bindings.items():
        action_tokens.setdefault(action, []).append(token)
    for action in action_tokens:
        action_tokens[action].sort(
            key=lambda token: (0, int(token)) if token.isdigit() else (1, token)
        )
    return action_tokens


def print_sender_binding_audit(bindings: dict[str, str]) -> None:
    print("binding audit:")
    action_tokens = build_action_token_index(bindings)
    for action in SENDER_AUDIT_ACTIONS:
        tokens = action_tokens.get(action)
        token_text = ",".join(tokens) if tokens else "(unmapped)"
        print(f"- {action}: {token_text}")


def set_mask(mask: ctypes.Array[ctypes.c_ubyte], event_type: int) -> None:
    mask[event_type >> 3] |= 1 << (event_type & 7)


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
    event: Xi2KeyEvent | None,
    bindings: dict[str, str],
    held_keys: set[str],
) -> tuple[Xi2KeyEvent | None, str | None]:
    if event is None:
        return None, None

    action = bindings.get(event.keycode)
    if action is None:
        return None, None

    if not should_emit_event(event, held_keys):
        return None, None

    return event, action


def next_select_timeout(
    *,
    held_keys: set[str],
    block: list[str],
    next_heartbeat_at: float,
    now: float,
) -> float | None:
    if block:
        return 0.0
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
    try:
        listener = Xi2RawListener(int(device_id))
    except OSError as exc:
        print(f"Error: failed to start XI2 listener: {exc}")
        return 2
    except ValueError:
        print(f"Error: invalid device id: {device_id}")
        return 2

    print_sender_binding_audit(bindings)
    print(f"watching XI2 raw key events for device {device_id} and sending to {target}")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        with TerminalNoEcho():
            try:
                selector = selectors.DefaultSelector()
                selector.register(listener.fileno(), selectors.EVENT_READ)
                next_heartbeat_at = time.monotonic() + HEARTBEAT_INTERVAL_SECONDS
                while True:
                    now = time.monotonic()
                    timeout = next_select_timeout(
                        held_keys=held_keys,
                        block=[],
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

                    parsed = listener.read_event()
                    while parsed is not None:
                        event, action = flush_block(parsed, bindings, held_keys)
                        if event is not None and action is not None:
                            send_action(
                                sock,
                                resolved_target,
                                action=action,
                                state=event.state,
                                seq=seq,
                                profile_name=resolved_profile_name,
                                profile_hash=profile_hash,
                            )
                            seq += 1
                            next_heartbeat_at = time.monotonic() + HEARTBEAT_INTERVAL_SECONDS
                        parsed = listener.read_event()
                selector.close()
            except KeyboardInterrupt:
                print("stopping sender")
            finally:
                listener.close()
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
