# Deck Learn Wizard

The Learn Wizard captures Steam Deck keycodes from `xinput test <device_id>` and
writes `deck_bindings.json`.

## Interaction Model

- The wizard listens for `key press <code>` events only.
- Each key press becomes the current candidate for the action being mapped.
- Press `Enter` to confirm the most recent candidate.
- Press `Esc` to skip the current action and leave it unmapped.
- If `Enter` is pressed before any candidate is captured, the wizard prints a warning and keeps waiting.
- If a keycode is already assigned to a previous action, the wizard prints a warning before confirmation.

## Running

```bash
python3 -m deck.learn_wizard \
  --device-id 5 \
  --actions config/actions.yaml \
  --out config/deck_bindings.json
```

Desktop launcher flow:

```bash
python3 -m deck.launch_learn
```

## Output Format

Example `deck_bindings.json`:

```json
{
  "profile_name": "default",
  "bindings": {
    "67": "BTN_A",
    "68": "BTN_B"
  }
}
```
