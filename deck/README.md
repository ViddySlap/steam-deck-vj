# Deck

Steam Deck-side components live here:

- `learn`: capture X11-generated tokens and bind them to Action IDs
- `send`: watch input events and transmit action messages over UDP

Current modules:

- `learn_wizard.py`: interactive xinput-based binding capture wizard
- `xinput_send.py`: listen for X11/XI2 raw key events for a device id, map keycodes to Action IDs, and send UDP events
