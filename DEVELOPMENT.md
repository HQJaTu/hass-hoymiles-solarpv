# Development

## Prep

```bash
python -m venv venv && . venv/bin/activate
pip install -r requirements_test.txt
pytest
```

## Coding standards

Code quality is enforced with the Home Assistant tool set
— **black** (formatting)
- **isort** (imports)
- **flake8** (linting)
- **mypy** (typing)

... wired up through
[pre-commit](https://pre-commit.com/):

```bash
pre-commit install      # run the checks automatically on every commit
pre-commit run --all-files
```

### `isort` reports "files were modified by this hook" on commit

This is normal pre-commit behaviour, **not** a black/isort conflict (the two are
reconciled via `profile = "black"` in `pyproject.toml`). It means the *staged*
content was not import-sorted, so the hook rewrote the files in your working tree
and aborted the commit. Just stage the fixes and commit again:

```bash
git add -u && git commit ...
```

If it keeps happening on every commit, your editor is most likely re-sorting
imports on save with a different ordering than isort's black profile. Either let
pre-commit own import sorting (disable the editor's "organize imports on save"), or
point the editor's isort at this repo's config (`profile = black`, line length 100).

## QA

Validate the manifest/translations with hassfest (the same check CI runs):

```bash
python -m script.hassfest --integration-path custom_components/hoymiles_solarpv
```

## Running / debugging outside Home Assistant

`scripts/debug_dtu.py` drives the integration's own Modbus client, production cache
and (optionally) MQTT publisher without a running Home Assistant instance — handy
for verifying connectivity to a DTU or stepping through the parsing code in a
debugger. The core path needs only `pymodbus`; `--mqtt-*` additionally needs
`homeassistant` importable.

### Usage
```text
usage: debug_dtu.py [-h] [--host HOST] [--port PORT] [--type {MI,HM}]
                    [--unit-id UNIT_ID] [--timeout TIMEOUT] [--retries RETRIES]
                    [--interval INTERVAL] [--cache] [--mqtt-host MQTT_HOST]
                    [--mqtt-port MQTT_PORT] [--mqtt-username MQTT_USERNAME]
                    [--mqtt-password MQTT_PASSWORD] [--mqtt-topic MQTT_TOPIC] [--debug]
                    [--selftest]

Debug the Hoymiles SolarPV integration locally.

options:
  -h, --help            show this help message and exit
  --host HOST           DTU host / IP address
  --port PORT           DTU Modbus TCP port
  --type {MI,HM}        Microinverter family
  --unit-id UNIT_ID     Modbus unit/device ID
  --timeout TIMEOUT     Per-request timeout (s)
  --retries RETRIES     Max retries per request
  --interval INTERVAL   Poll every N seconds (0 = once)
  --cache               Apply production smoothing/reset
  --mqtt-host MQTT_HOST
                        Re-publish to this MQTT broker (needs homeassistant)
  --mqtt-port MQTT_PORT
  --mqtt-username MQTT_USERNAME
  --mqtt-password MQTT_PASSWORD
  --mqtt-topic MQTT_TOPIC
  --debug               Enable pymodbus DEBUG logging
  --selftest            Run offline logic check (no DTU)
```


### Examples

```bash
# Offline logic check — parses a synthetic record and simulates a day
# (incl. the 22:00 reset) through the production cache. No hardware needed.
python scripts/debug_dtu.py --selftest

# Read a real DTU once and print the decoded plant data
python scripts/debug_dtu.py --host 192.168.1.50

# Poll every 30s with production smoothing and full pymodbus DEBUG logging
python scripts/debug_dtu.py --host 192.168.1.50 --interval 30 --cache --debug
```
