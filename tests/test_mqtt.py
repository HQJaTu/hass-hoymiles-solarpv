"""Unit tests for the MQTT payload builder."""

from __future__ import annotations

import json

from custom_components.hoymiles_solarpv.mqtt import HoymilesMqttPublisher


def _make_publisher() -> HoymilesMqttPublisher:
    return HoymilesMqttPublisher(
        host="broker", port=1883, username=None, password=None,
        topic_base="homeassistant/hoymiles_solarpv",
    )


def test_discovery_payloads_cover_all_entities(sample_plant_data):
    """Discovery messages are produced for DTU and microinverter entities."""
    publisher = _make_publisher()
    messages = publisher._discovery_payloads(sample_plant_data)

    topics = [topic for topic, _ in messages]
    # DTU: 3 sensors + 1 binary sensor, microinverter: 12 sensors
    assert len(messages) == 3 + 1 + 12
    assert "homeassistant/sensor/aabbccddeeff/pv_power/config" in topics
    assert "homeassistant/binary_sensor/aabbccddeeff/alarm_flag/config" in topics
    assert any("/112233445566/pv_voltage/config" in t for t in topics)

    payload = json.loads(dict(messages)["homeassistant/sensor/aabbccddeeff/pv_power/config"])
    assert payload["unit_of_measurement"] == "W"
    assert payload["device_class"] == "power"
    assert payload["state_topic"] == "homeassistant/hoymiles_solarpv/aabbccddeeff/state"


def test_state_payloads_serialize_decimals(sample_plant_data):
    """State payloads render Decimals as numbers and binary flags as ON/OFF."""
    publisher = _make_publisher()
    messages = publisher._state_payloads(sample_plant_data)

    state = dict(messages)
    dtu_state = json.loads(state["homeassistant/hoymiles_solarpv/aabbccddeeff/state"])
    assert dtu_state["pv_power"] == 150.0
    assert dtu_state["alarm_flag"] == "OFF"

    mi_state = json.loads(state["homeassistant/hoymiles_solarpv/112233445566/state"])
    assert mi_state["pv_voltage"] == 245.0
    assert mi_state["grid_frequency"] == 50.0


def test_publish_plant_data_sends_configs_once(sample_plant_data):
    """Discovery is published once (retained), state every call."""
    publisher = _make_publisher()
    publisher._client = _FakeMqttClient()

    publisher.publish_plant_data(sample_plant_data)
    publisher.publish_plant_data(sample_plant_data)

    retained = [m for m in publisher._client.published if m["retain"]]
    non_retained = [m for m in publisher._client.published if not m["retain"]]
    # 16 retained discovery messages published exactly once
    assert len(retained) == 16
    # 2 state topics (DTU + 1 microinverter) per publish call => 4 total
    assert len(non_retained) == 4


class _FakeMqttClient:
    """Minimal stand-in for paho's Client."""

    def __init__(self) -> None:
        self.published: list[dict] = []
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def connect(self, host, port):  # noqa: ARG002
        self._connected = True

    def loop_start(self):
        pass

    def publish(self, topic, payload, retain=False):
        self.published.append({"topic": topic, "payload": payload, "retain": retain})
