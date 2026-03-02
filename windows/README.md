# Windows

Windows-side components live here:

- `recv`: accept action events over the network
- `midi`: translate Action IDs into MIDI output for Resolume

Current modules:

- `config.py`: load and validate MIDI mapping config
- `list_midi_ports.py`: print available MIDI output ports
- `midi.py`: MIDI backend abstraction with dry-run support
- `receiver.py`: UDP receiver core, sequence handling, and failsafes
- `win_recv.py`: CLI entrypoint
