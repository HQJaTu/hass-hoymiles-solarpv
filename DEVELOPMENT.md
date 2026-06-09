## Development

```bash
python -m venv venv && . venv/bin/activate
pip install -r requirements_test.txt
pytest
```

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

Validate the manifest/translations with hassfest (the same check CI runs):

```bash
python -m script.hassfest --integration-path custom_components/hoymiles_solarpv
```

### Running / debugging outside Home Assistant

`scripts/debug_dtu.py` drives the integration's own Modbus client, production cache
and (optionally) MQTT publisher without a running Home Assistant instance — handy
for verifying connectivity to a DTU or stepping through the parsing code in a
debugger. The core path needs only `pymodbus`; `--mqtt-*` additionally needs
`homeassistant` importable.

```bash
# Offline logic check — parses a synthetic record and simulates a day
# (incl. the 22:00 reset) through the production cache. No hardware needed.
python scripts/debug_dtu.py --selftest

# Read a real DTU once and print the decoded plant data
python scripts/debug_dtu.py --host 192.168.1.50

# Poll every 30s with production smoothing and full pymodbus DEBUG logging
python scripts/debug_dtu.py --host 192.168.1.50 --interval 30 --cache --debug
```
