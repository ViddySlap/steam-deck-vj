"""Configuration loading and validation for the Windows receiver."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    """Raised when the Windows MIDI map is invalid."""


@dataclass(frozen=True)
class MacroSettings:
    fade_duration_seconds: float = 2.0
    update_hz: float = 30.0
    min_value: int = 0
    max_value: int = 127
    feedback_match_tolerance: int = 2
    macro_delay_ms: int = 80
    modifier_hold_ms: int = 2000

    @property
    def step_interval_seconds(self) -> float:
        return 1.0 / self.update_hz


@dataclass(frozen=True)
class NoteMapping:
    action: str
    kind: str
    channel: int
    note: int
    velocity: int = 127


@dataclass(frozen=True)
class ControlChangeMapping:
    action: str
    kind: str
    channel: int
    cc: int
    on_value: int = 127
    off_value: int = 0


@dataclass(frozen=True)
class MacroCCMapping:
    action: str
    kind: str
    channel: int
    cc: int
    gesture: str


@dataclass(frozen=True)
class RelativeCCMapping:
    action: str
    kind: str
    channel: int
    cc: int
    step_value: int
    repeat_interval_ms: int = 40


@dataclass(frozen=True)
class StagedNoteMacroMapping:
    action: str
    kind: str
    note: int
    modifier_channel: int = 0
    trigger_channel: int = 1
    velocity: int = 127
    refresh_actions: tuple[str, ...] = ()


MidiMapping = (
    NoteMapping
    | ControlChangeMapping
    | MacroCCMapping
    | RelativeCCMapping
    | StagedNoteMacroMapping
)


@dataclass(frozen=True)
class ReceiverConfig:
    mappings: dict[str, MidiMapping]
    macro_settings: MacroSettings


def load_midi_map(path: str | Path) -> ReceiverConfig:
    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"mapping file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"mapping file is not valid JSON: {config_path}") from exc

    mappings = raw.get("mappings")
    if not isinstance(mappings, dict):
        raise ConfigError("mapping file must contain an object at 'mappings'")

    macro_settings = _parse_macro_settings(raw.get("macro_settings"))

    validated: dict[str, MidiMapping] = {}
    for action, spec in mappings.items():
        if not isinstance(action, str) or not action:
            raise ConfigError("mapping action keys must be non-empty strings")
        if not isinstance(spec, dict):
            raise ConfigError(f"mapping for {action} must be an object")
        validated[action] = _parse_mapping(action, spec)

    return ReceiverConfig(mappings=validated, macro_settings=macro_settings)


def _parse_macro_settings(spec: object) -> MacroSettings:
    if spec is None:
        return MacroSettings()
    if not isinstance(spec, dict):
        raise ConfigError("macro_settings must be an object")

    fade_duration_seconds = _read_positive_number(
        spec, "fade_duration_seconds", default=2.0
    )
    update_hz = _read_positive_number(spec, "update_hz", default=30.0)
    min_value = _read_byte(spec, "min_value", default=0)
    max_value = _read_byte(spec, "max_value", default=127)
    feedback_match_tolerance = _read_byte(
        spec,
        "feedback_match_tolerance",
        default=2,
    )
    macro_delay_ms = _read_positive_int(spec, "macro_delay_ms", default=80)
    modifier_hold_ms = _read_positive_int(spec, "modifier_hold_ms", default=2000)
    if min_value >= max_value:
        raise ConfigError("macro_settings min_value must be less than max_value")

    return MacroSettings(
        fade_duration_seconds=fade_duration_seconds,
        update_hz=update_hz,
        min_value=min_value,
        max_value=max_value,
        feedback_match_tolerance=feedback_match_tolerance,
        macro_delay_ms=macro_delay_ms,
        modifier_hold_ms=modifier_hold_ms,
    )


def _parse_mapping(action: str, spec: dict[str, object]) -> MidiMapping:
    kind = spec.get("type")
    if kind == "note":
        channel = _read_byte(spec, "channel", maximum=15, default=0)
        note = _read_byte(spec, "note")
        velocity = _read_byte(spec, "velocity", default=127)
        return NoteMapping(
            action=action,
            kind="note",
            channel=channel,
            note=note,
            velocity=velocity,
        )
    if kind == "cc":
        channel = _read_byte(spec, "channel", maximum=15, default=0)
        cc = _read_byte(spec, "cc")
        on_value = _read_byte(spec, "on_value", default=127)
        off_value = _read_byte(spec, "off_value", default=0)
        return ControlChangeMapping(
            action=action,
            kind="cc",
            channel=channel,
            cc=cc,
            on_value=on_value,
            off_value=off_value,
        )
    if kind == "macro_cc":
        channel = _read_byte(spec, "channel", maximum=15, default=0)
        cc = _read_byte(spec, "cc")
        gesture = spec.get("gesture")
        if gesture not in {"click", "long_press"}:
            raise ConfigError(
                f"mapping for {action} must set gesture to 'click' or 'long_press'"
            )
        return MacroCCMapping(
            action=action,
            kind="macro_cc",
            channel=channel,
            cc=cc,
            gesture=gesture,
        )
    if kind == "relative_cc":
        channel = _read_byte(spec, "channel", maximum=15, default=0)
        cc = _read_byte(spec, "cc")
        step_value = _read_byte(spec, "step_value")
        repeat_interval_ms = _read_positive_int(spec, "repeat_interval_ms", default=40)
        return RelativeCCMapping(
            action=action,
            kind="relative_cc",
            channel=channel,
            cc=cc,
            step_value=step_value,
            repeat_interval_ms=repeat_interval_ms,
        )
    if kind == "staged_note_macro":
        note = _read_byte(spec, "note")
        velocity = _read_byte(spec, "velocity", default=127)
        modifier_channel = _read_byte(spec, "modifier_channel", maximum=15, default=0)
        trigger_channel = _read_byte(spec, "trigger_channel", maximum=15, default=1)
        refresh_actions = _read_string_list(spec, "refresh_actions", default=[])
        if modifier_channel == trigger_channel:
            raise ConfigError(
                f"mapping for {action} must use different modifier_channel and trigger_channel"
            )
        return StagedNoteMacroMapping(
            action=action,
            kind="staged_note_macro",
            note=note,
            modifier_channel=modifier_channel,
            trigger_channel=trigger_channel,
            velocity=velocity,
            refresh_actions=tuple(refresh_actions),
        )
    raise ConfigError(
        "mapping for"
        " "
        f"{action} must have type 'note', 'cc', 'macro_cc', 'relative_cc', or"
        " 'staged_note_macro'"
    )


def _read_byte(
    spec: dict[str, object],
    key: str,
    *,
    maximum: int = 127,
    default: int | None = None,
) -> int:
    value = spec.get(key, default)
    if not isinstance(value, int):
        raise ConfigError(f"{key} must be an integer")
    if value < 0 or value > maximum:
        raise ConfigError(f"{key} must be between 0 and {maximum}")
    return value


def _read_positive_number(
    spec: dict[str, object],
    key: str,
    *,
    default: float,
) -> float:
    value = spec.get(key, default)
    if not isinstance(value, (int, float)):
        raise ConfigError(f"{key} must be a number")
    number = float(value)
    if number <= 0:
        raise ConfigError(f"{key} must be greater than 0")
    return number


def _read_positive_int(
    spec: dict[str, object],
    key: str,
    *,
    default: int,
) -> int:
    value = spec.get(key, default)
    if not isinstance(value, int):
        raise ConfigError(f"{key} must be an integer")
    if value <= 0:
        raise ConfigError(f"{key} must be greater than 0")
    return value


def _read_string_list(
    spec: dict[str, object],
    key: str,
    *,
    default: list[str],
) -> list[str]:
    value = spec.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ConfigError(f"{key} must be a list of non-empty strings")
    return list(value)
