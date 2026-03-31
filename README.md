# I.D.R.A. Desktop Tools Repository

Desktop debug/load simulator for I.D.R.A. (Python + Tkinter + socket.io client).

## What this repository does
This repository provides a standalone desktop simulator used by developers/operators to:
- create many simulated clients,
- test channel/auth/report flows against a target server,
- run controlled load scenarios without browser socket limits,
- inspect protocol responses and errors in a single event log UI.

## What this repo contains
- `idra_desktop_simulator.py` desktop simulator app
- `requirements.txt` Python dependencies

## Run without Docker (recommended)
1. `python3 -m venv .venv`
2. `source .venv/bin/activate` (Windows: `.venv\\Scripts\\activate`)
3. `pip install -r requirements.txt`
4. `python idra_desktop_simulator.py`

## Auth and test behavior
- Supports Frontier OAuth flow for selected simulated client.
- Supports fake-user batches and report blast for load checks.

## License
GNU GPL v2 or later. See `LICENSE`.
