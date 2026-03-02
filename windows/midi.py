"""MIDI output abstractions for the Windows receiver."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


class MidiError(RuntimeError):
    """Raised when MIDI output cannot be initialized or used."""


class MidiOut:
    """Abstract MIDI output interface."""

    @property
    def port_name(self) -> str:
        raise NotImplementedError

    @property
    def port_index(self) -> int | None:
        return None

    def note_on(self, channel: int, note: int, velocity: int) -> None:
        raise NotImplementedError

    def note_off(self, channel: int, note: int, velocity: int = 0) -> None:
        raise NotImplementedError

    def control_change(self, channel: int, control: int, value: int) -> None:
        raise NotImplementedError

    def panic(self) -> None:
        """Send a conservative reset where supported."""

    def close(self) -> None:
        """Release backend resources if needed."""


@dataclass
class DryRunMidiOut(MidiOut):
    """A no-op backend that records what would be sent."""

    selected_port_name: str = "dry-run"
    selected_port_index: int | None = None

    @property
    def port_name(self) -> str:
        return self.selected_port_name

    @property
    def port_index(self) -> int | None:
        return self.selected_port_index

    def note_on(self, channel: int, note: int, velocity: int) -> None:
        print(f"MIDI note_on channel={channel} note={note} velocity={velocity}")

    def note_off(self, channel: int, note: int, velocity: int = 0) -> None:
        print(f"MIDI note_off channel={channel} note={note} velocity={velocity}")

    def control_change(self, channel: int, control: int, value: int) -> None:
        print(f"MIDI cc channel={channel} control={control} value={value}")

    def panic(self) -> None:
        print("MIDI panic")


class MidoMidiOut(MidiOut):
    """Optional `mido`-based MIDI output implementation."""

    def __init__(self, port_name: str):
        try:
            import mido
        except ImportError as exc:
            raise MidiError(
                "mido is not installed; use --dry-run or install a MIDI backend"
            ) from exc

        available = list_output_ports(mido.get_output_names())
        resolved_port_name = resolve_output_port_name(port_name, available)

        self._mido = mido
        self._port_index = available.index(resolved_port_name)
        self._port = mido.open_output(resolved_port_name)
        self._port_name = resolved_port_name
        self._failed = False

    @property
    def port_name(self) -> str:
        return self._port_name

    @property
    def port_index(self) -> int | None:
        return self._port_index

    def _send(self, message) -> None:
        if self._failed:
            raise MidiError(
                f"MIDI output '{self._port_name}' is unavailable after a previous send failure"
            )
        try:
            self._port.send(message)
        except Exception as exc:
            self._failed = True
            raise MidiError(
                f"failed to send MIDI message on '{self._port_name}': {exc}"
            ) from exc

    def note_on(self, channel: int, note: int, velocity: int) -> None:
        self._send(
            self._mido.Message("note_on", channel=channel, note=note, velocity=velocity)
        )

    def note_off(self, channel: int, note: int, velocity: int = 0) -> None:
        self._send(
            self._mido.Message("note_off", channel=channel, note=note, velocity=velocity)
        )

    def control_change(self, channel: int, control: int, value: int) -> None:
        self._send(
            self._mido.Message(
                "control_change", channel=channel, control=control, value=value
            )
        )

    def panic(self) -> None:
        for channel in range(16):
            self.control_change(channel, 123, 0)

    def close(self) -> None:
        self._port.close()


def open_midi_output(port_name: str | None, dry_run: bool) -> MidiOut:
    if dry_run:
        return DryRunMidiOut(selected_port_name=port_name or "dry-run")
    if not port_name:
        raise MidiError("a MIDI port name is required unless --dry-run is enabled")
    return MidoMidiOut(port_name)


def list_output_ports(names: Sequence[str]) -> list[str]:
    return list(names)


def resolve_output_port_name(port_name: str, names: Sequence[str]) -> str:
    available = list_output_ports(names)
    if port_name in available:
        return port_name

    folded_name = port_name.casefold()

    case_insensitive_exact = [
        candidate for candidate in available if candidate.casefold() == folded_name
    ]
    if len(case_insensitive_exact) == 1:
        return case_insensitive_exact[0]

    prefix_matches = [
        candidate for candidate in available if candidate.casefold().startswith(folded_name)
    ]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if len(prefix_matches) > 1:
        joined_matches = ", ".join(prefix_matches)
        raise MidiError(
            f"MIDI port '{port_name}' matched multiple ports: {joined_matches}"
        )

    joined = format_output_port_list(available)
    raise MidiError(f"MIDI port '{port_name}' not found; available ports: {joined}")


def format_output_port_list(names: Sequence[str]) -> str:
    if not names:
        return "(none)"
    return ", ".join(f"[{index}] {name}" for index, name in enumerate(names))
