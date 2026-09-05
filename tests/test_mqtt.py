"""Unit tests for the MQTT payload builder."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes

from custom_components.hoymiles_solarpv.hoymiles import (
    MicroinverterType,
    PlantData,
    parse_microinverter_record,
)
from custom_components.hoymiles_solarpv.mqtt import HoymilesMqttPublisher

from .conftest import build_record

_TS = datetime(2026, 6, 10, 12, 30, 45, tzinfo=UTC)

_CONNACK_OK = mqtt.ReasonCode(PacketTypes.CONNACK, "Success")
_CONNACK_REFUSED = mqtt.ReasonCode(PacketTypes.CONNACK, "Not authorized")


def _make_publisher() -> HoymilesMqttPublisher:
    publisher = HoymilesMqttPublisher(
        host="broker",
        port=1883,
        username=None,
        password=None,
        topic_base="homeassistant/hoymiles_solarpv",
    )
    # Stand in for paho, wired to the publisher's own connect callback.
    publisher._client = _FakeMqttClient(publisher._on_connect)
    return publisher


def test_discovery_payloads_cover_all_entities(sample_plant_data):
    """Discovery messages are produced for DTU and microinverter entities."""
    publisher = _make_publisher()
    messages = publisher._discovery_payloads(sample_plant_data)

    topics = [topic for topic, _ in messages]
    # DTU: 3 sensors + 1 last_update + 1 binary sensor;
    # microinverter (1 serial, 1 port): 7 inverter-level + 5 port-level.
    assert len(messages) == 3 + 1 + 1 + 7 + 5
    assert "homeassistant/sensor/aabbccddeeff/pv_power/config" in topics
    assert "homeassistant/sensor/aabbccddeeff/last_update/config" in topics
    assert "homeassistant/binary_sensor/aabbccddeeff/alarm_flag/config" in topics
    # Inverter-level sensor keyed by serial, port-level sensor keyed by serial+port.
    assert "homeassistant/sensor/112233445566/temperature/config" in topics
    assert "homeassistant/sensor/112233445566/port1_pv_voltage/config" in topics

    payload = json.loads(dict(messages)["homeassistant/sensor/aabbccddeeff/pv_power/config"])
    assert payload["unit_of_measurement"] == "W"
    assert payload["device_class"] == "power"
    assert payload["state_topic"] == "homeassistant/hoymiles_solarpv/aabbccddeeff/state"

    ts_payload = json.loads(dict(messages)["homeassistant/sensor/aabbccddeeff/last_update/config"])
    assert ts_payload["device_class"] == "timestamp"
    assert "unit_of_measurement" not in ts_payload

    # Port sensor points at the per-port state topic and reads the bare key.
    port_payload = json.loads(
        dict(messages)["homeassistant/sensor/112233445566/port1_pv_voltage/config"]
    )
    assert port_payload["state_topic"] == "homeassistant/hoymiles_solarpv/112233445566/1/state"
    assert "value_json.pv_voltage" in port_payload["value_template"]
    assert port_payload["name"] == "Port 1 pv_voltage"


def test_discovery_device_blocks(sample_plant_data):
    """DTU and inverter devices are named per serial and linked in one direction."""
    publisher = _make_publisher()
    messages = dict(publisher._discovery_payloads(sample_plant_data))

    # The DTU name carries its serial so several DTUs stay distinguishable, and it
    # is not its own via_device.
    dtu_device = json.loads(messages["homeassistant/sensor/aabbccddeeff/pv_power/config"])["device"]
    assert dtu_device["name"] == "DTU_aabbccddeeff"
    assert dtu_device["identifiers"] == ["hoymiles_solarpv_aabbccddeeff"]
    assert "via_device" not in dtu_device

    # Microinverters keep pointing at the DTU they sit behind.
    mi_device = json.loads(messages["homeassistant/sensor/112233445566/temperature/config"])[
        "device"
    ]
    assert mi_device["name"] == "Inverter 112233445566"
    assert mi_device["via_device"] == "hoymiles_solarpv_aabbccddeeff"


def test_state_payloads_serialize_decimals(sample_plant_data):
    """State payloads render Decimals as numbers and binary flags as ON/OFF."""
    publisher = _make_publisher()
    messages = publisher._state_payloads(sample_plant_data, _TS)

    state = dict(messages)
    dtu_state = json.loads(state["homeassistant/hoymiles_solarpv/aabbccddeeff/state"])
    assert dtu_state["pv_power"] == 150.0
    assert dtu_state["alarm_flag"] == "OFF"
    assert dtu_state["last_update"] == "2026-06-10T12:30:45+00:00"

    # Inverter-level state (per serial): grid/temperature/status, no PV port data.
    mi_state = json.loads(state["homeassistant/hoymiles_solarpv/112233445566/state"])
    assert mi_state["grid_frequency"] == 50.0
    assert "pv_voltage" not in mi_state

    # Port-level state (per serial + port): the PV input measurements.
    port_state = json.loads(state["homeassistant/hoymiles_solarpv/112233445566/1/state"])
    assert port_state["pv_voltage"] == 245.0
    assert port_state["pv_power"] == 150.0


def test_publish_plant_data_sends_configs_once(sample_plant_data):
    """Discovery is published once per connection, state every call."""
    publisher = _make_publisher()

    publisher.publish_plant_data(sample_plant_data)
    publisher.publish_plant_data(sample_plant_data)

    configs = [m for m in publisher._client.published if "/config" in m["topic"]]
    states = [m for m in publisher._client.published if m["topic"].endswith("/state")]
    # 17 retained discovery messages (5 DTU + 7 inverter + 5 port) published once
    assert len(configs) == 17
    assert all(m["retain"] for m in configs)
    # 3 state topics (DTU + inverter + 1 port) per publish call => 6 total
    assert len(states) == 6


def test_publish_plant_data_republishes_configs_after_reconnect(sample_plant_data):
    """A dropped connection re-sends discovery: the broker may have lost it."""
    publisher = _make_publisher()

    publisher.publish_plant_data(sample_plant_data)
    # The broker went away and paho reconnects on the next publish.
    publisher._client.drop_connection()
    publisher.publish_plant_data(sample_plant_data)

    configs = [m for m in publisher._client.published if "/config" in m["topic"]]
    assert len(configs) == 17 * 2


def test_silent_paho_reconnect_republishes_configs(sample_plant_data):
    """A reconnect paho handles on its own also re-sends discovery."""
    publisher = _make_publisher()

    publisher.publish_plant_data(sample_plant_data)
    # paho's network thread reconnected without this code ever seeing the drop.
    publisher._on_connect(publisher._client, None, {}, _CONNACK_OK, None)
    publisher.publish_plant_data(sample_plant_data)

    configs = [m for m in publisher._client.published if "/config" in m["topic"]]
    assert len(configs) == 17 * 2


def test_refused_connection_does_not_republish_configs(sample_plant_data):
    """A rejected CONNACK is not a new connection; discovery stays put."""
    publisher = _make_publisher()

    publisher.publish_plant_data(sample_plant_data)
    publisher._on_connect(publisher._client, None, {}, _CONNACK_REFUSED, None)
    publisher.publish_plant_data(sample_plant_data)

    configs = [m for m in publisher._client.published if "/config" in m["topic"]]
    assert len(configs) == 17


def test_dtu_state_is_retained(sample_plant_data):
    """DTU state is retained so consumers see it (and its age) on connect."""
    publisher = _make_publisher()

    publisher.publish_plant_data(sample_plant_data)

    states = {m["topic"]: m for m in publisher._client.published if m["topic"].endswith("/state")}
    assert states["homeassistant/hoymiles_solarpv/aabbccddeeff/state"]["retain"] is True
    # Inverter and port state stay non-retained.
    assert states["homeassistant/hoymiles_solarpv/112233445566/state"]["retain"] is False
    assert states["homeassistant/hoymiles_solarpv/112233445566/1/state"]["retain"] is False


def test_publish_plant_data_defaults_timestamp(sample_plant_data):
    """A last_update timestamp is published even when none is supplied."""
    publisher = _make_publisher()

    publisher.publish_plant_data(sample_plant_data)

    dtu_topic = "homeassistant/hoymiles_solarpv/aabbccddeeff/state"
    dtu_state = next(
        json.loads(m["payload"]) for m in publisher._client.published if m["topic"] == dtu_topic
    )
    # Value is present and parses back to an aware datetime.
    parsed = datetime.fromisoformat(dtu_state["last_update"])
    assert parsed.tzinfo is not None


def _multi_port_plant() -> PlantData:
    """A single microinverter serial driving two PV ports."""
    serial = b"\xaa\xbb\xcc\xdd\xee\x01"
    port1 = parse_microinverter_record(
        build_record(serial=serial, port_number=1, pv_voltage=2450, pv_power=1500),
        MicroinverterType.MI,
    )
    port2 = parse_microinverter_record(
        build_record(serial=serial, port_number=2, pv_voltage=2600, pv_power=1800),
        MicroinverterType.MI,
    )
    return PlantData(dtu="aabbccddeeff", microinverter_data=[port1, port2])


def test_multi_port_microinverter_publishes_every_port():
    """Both ports of one microinverter get their own state and discovery."""
    publisher = _make_publisher()
    plant = _multi_port_plant()
    serial = "aabbccddee01"

    state = dict(publisher._state_payloads(plant, _TS))
    # Inverter-level state published once; one port-state per port.
    assert f"homeassistant/hoymiles_solarpv/{serial}/state" in state
    assert f"homeassistant/hoymiles_solarpv/{serial}/1/state" in state
    assert f"homeassistant/hoymiles_solarpv/{serial}/2/state" in state
    assert (
        json.loads(state[f"homeassistant/hoymiles_solarpv/{serial}/1/state"])["pv_power"] == 150.0
    )
    assert (
        json.loads(state[f"homeassistant/hoymiles_solarpv/{serial}/2/state"])["pv_power"] == 180.0
    )

    topics = [t for t, _ in publisher._discovery_payloads(plant)]
    # Inverter sensors once (7), port sensors per port (5 * 2 = 10).
    assert sum(1 for t in topics if "/temperature/config" in t) == 1
    assert f"homeassistant/sensor/{serial}/port1_pv_power/config" in topics
    assert f"homeassistant/sensor/{serial}/port2_pv_power/config" in topics


class _FakeMqttClient:
    """Minimal stand-in for paho's Client."""

    def __init__(self, on_connect=None) -> None:
        self.published: list[dict] = []
        self._connected = False
        self.on_connect = on_connect

    def is_connected(self) -> bool:
        return self._connected

    def connect(self, host, port):
        self._connected = True
        if self.on_connect is not None:
            self.on_connect(self, None, {}, _CONNACK_OK, None)

    def loop_start(self):
        pass

    def drop_connection(self):
        """Simulate the broker going away between publishes."""
        self._connected = False

    def publish(self, topic, payload, retain=False):
        self.published.append({"topic": topic, "payload": payload, "retain": retain})
