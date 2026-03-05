# Deck Sender

Deck sender listens to X11/XI2 raw key events for the configured device id.

Then it:

- maps the numeric keycode token to an Action ID using `config/deck_bindings.json`
- converts raw key press to `down` and raw key release to `up`
- sends the JSON event to the Windows receiver over UDP
- sends heartbeat events while any key is held

## Binding Format

Example `config/deck_bindings.json`:

```json
{
  "profile_name": "default",
  "bindings": {
    "14": "BTN_A",
    "15": "BTN_B"
  }
}
```

## Running

Example:

```bash
python3 -m deck.xinput_send \
  --device-id 5 \
  --bindings config/deck_bindings.json \
  --target 10.10.10.15:45123
```

Desktop launcher flow:

```bash
python3 -m deck.launch_send
```

## Notes

- Unmapped keycodes are ignored and printed to stdout.
- Sequence numbers start at `1` each time the sender starts.
- This is intended for SteamOS Desktop Mode / X11.
- The launcher stores target presets in `config/deck_runtime_settings.local.json`.
- Learn Wizard capture remains on the older xinput-based path by design.
