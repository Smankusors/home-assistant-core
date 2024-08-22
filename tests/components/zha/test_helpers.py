"""Tests for ZHA helpers."""

import logging
from typing import Any

import pytest
import voluptuous_serialize
from zigpy.types.basic import uint16_t
from zigpy.zcl.clusters import lighting

from homeassistant.components.zha.helpers import (
    cluster_command_schema_to_vol_schema,
    convert_to_zcl_values,
    exclude_none_values,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)


async def test_zcl_schema_conversions(hass: HomeAssistant) -> None:
    """Test ZHA ZCL schema conversion helpers."""
    command_schema = lighting.Color.ServerCommandDefs.color_loop_set.schema
    expected_schema = [
        {
            "type": "multi_select",
            "options": ["Action", "Direction", "Time", "Start Hue"],
            "name": "update_flags",
            "required": True,
        },
        {
            "type": "select",
            "options": [
                ("Deactivate", "Deactivate"),
                ("Activate from color loop hue", "Activate from color loop hue"),
                ("Activate from current hue", "Activate from current hue"),
            ],
            "name": "action",
            "required": True,
        },
        {
            "type": "select",
            "options": [("Decrement", "Decrement"), ("Increment", "Increment")],
            "name": "direction",
            "required": True,
        },
        {
            "type": "integer",
            "valueMin": 0,
            "valueMax": 65535,
            "name": "time",
            "required": True,
        },
        {
            "type": "integer",
            "valueMin": 0,
            "valueMax": 65535,
            "name": "start_hue",
            "required": True,
        },
        {
            "type": "integer",
            "valueMin": 0,
            "valueMax": 255,
            "name": "options_mask",
            "optional": True,
        },
        {
            "type": "integer",
            "valueMin": 0,
            "valueMax": 255,
            "name": "options_override",
            "optional": True,
        },
    ]
    vol_schema = voluptuous_serialize.convert(
        cluster_command_schema_to_vol_schema(command_schema),
        custom_serializer=cv.custom_serializer,
    )
    assert vol_schema == expected_schema

    raw_data = {
        "update_flags": ["Action", "Start Hue"],
        "action": "Activate from current hue",
        "direction": "Increment",
        "time": 20,
        "start_hue": 196,
    }

    converted_data = convert_to_zcl_values(raw_data, command_schema)

    assert isinstance(
        converted_data["update_flags"], lighting.Color.ColorLoopUpdateFlags
    )
    assert lighting.Color.ColorLoopUpdateFlags.Action in converted_data["update_flags"]
    assert (
        lighting.Color.ColorLoopUpdateFlags.Start_Hue in converted_data["update_flags"]
    )

    assert isinstance(converted_data["action"], lighting.Color.ColorLoopAction)
    assert (
        converted_data["action"]
        == lighting.Color.ColorLoopAction.Activate_from_current_hue
    )

    assert isinstance(converted_data["direction"], lighting.Color.ColorLoopDirection)
    assert converted_data["direction"] == lighting.Color.ColorLoopDirection.Increment

    assert isinstance(converted_data["time"], uint16_t)
    assert converted_data["time"] == 20

    assert isinstance(converted_data["start_hue"], uint16_t)
    assert converted_data["start_hue"] == 196

    raw_data = {
        "update_flags": [0b0000_0001, 0b0000_1000],
        "action": 0x02,
        "direction": 0x01,
        "time": 20,
        "start_hue": 196,
    }

    converted_data = convert_to_zcl_values(raw_data, command_schema)

    assert isinstance(
        converted_data["update_flags"], lighting.Color.ColorLoopUpdateFlags
    )
    assert lighting.Color.ColorLoopUpdateFlags.Action in converted_data["update_flags"]
    assert (
        lighting.Color.ColorLoopUpdateFlags.Start_Hue in converted_data["update_flags"]
    )

    assert isinstance(converted_data["action"], lighting.Color.ColorLoopAction)
    assert (
        converted_data["action"]
        == lighting.Color.ColorLoopAction.Activate_from_current_hue
    )

    assert isinstance(converted_data["direction"], lighting.Color.ColorLoopDirection)
    assert converted_data["direction"] == lighting.Color.ColorLoopDirection.Increment

    assert isinstance(converted_data["time"], uint16_t)
    assert converted_data["time"] == 20

    assert isinstance(converted_data["start_hue"], uint16_t)
    assert converted_data["start_hue"] == 196

    # This time, the update flags bitmap is empty
    raw_data = {
        "update_flags": [],
        "action": 0x02,
        "direction": 0x01,
        "time": 20,
        "start_hue": 196,
    }

    converted_data = convert_to_zcl_values(raw_data, command_schema)

    # No flags are passed through
    assert converted_data["update_flags"] == 0


@pytest.mark.parametrize(
    ("obj", "expected_output"),
    [
        ({"a": 1, "b": 2, "c": None}, {"a": 1, "b": 2}),
        ({"a": 1, "b": 2, "c": 0}, {"a": 1, "b": 2, "c": 0}),
        ({"a": 1, "b": 2, "c": ""}, {"a": 1, "b": 2, "c": ""}),
        ({"a": 1, "b": 2, "c": False}, {"a": 1, "b": 2, "c": False}),
    ],
)
def test_exclude_none_values(
    obj: dict[str, Any], expected_output: dict[str, Any]
) -> None:
    """Test exclude_none_values helper."""
    result = exclude_none_values(obj)
    assert result == expected_output

    for key in expected_output:
        assert expected_output[key] == obj[key]
