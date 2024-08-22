"""Tests for the Sonos Media Player platform."""

from typing import Any
from unittest.mock import patch

import pytest
from soco.data_structures import SearchResult
from syrupy import SnapshotAssertion

from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    ATTR_MEDIA_ENQUEUE,
    ATTR_MEDIA_REPEAT,
    ATTR_MEDIA_SHUFFLE,
    ATTR_MEDIA_VOLUME_LEVEL,
    DOMAIN as MP_DOMAIN,
    SERVICE_CLEAR_PLAYLIST,
    SERVICE_PLAY_MEDIA,
    SERVICE_SELECT_SOURCE,
    MediaPlayerEnqueue,
    RepeatMode,
)
from homeassistant.components.sonos.const import (
    DOMAIN as SONOS_DOMAIN,
    SOURCE_LINEIN,
    SOURCE_TV,
)
from homeassistant.components.sonos.media_player import (
    LONG_SERVICE_TIMEOUT,
    SERVICE_RESTORE,
    SERVICE_SNAPSHOT,
    VOLUME_INCREMENT,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_MEDIA_NEXT_TRACK,
    SERVICE_MEDIA_PAUSE,
    SERVICE_MEDIA_PLAY,
    SERVICE_MEDIA_PREVIOUS_TRACK,
    SERVICE_MEDIA_STOP,
    SERVICE_REPEAT_SET,
    SERVICE_SHUFFLE_SET,
    SERVICE_VOLUME_DOWN,
    SERVICE_VOLUME_SET,
    SERVICE_VOLUME_UP,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    CONNECTION_UPNP,
    DeviceRegistry,
)
from homeassistant.setup import async_setup_component

from .conftest import MockMusicServiceItem, MockSoCo, SoCoMockFactory, SonosMockEvent


async def test_device_registry(
    hass: HomeAssistant, device_registry: DeviceRegistry, async_autosetup_sonos, soco
) -> None:
    """Test sonos device registered in the device registry."""
    reg_device = device_registry.async_get_device(
        identifiers={("sonos", "RINCON_test")}
    )
    assert reg_device is not None
    assert reg_device.model == "Model Name"
    assert reg_device.sw_version == "13.1"
    assert reg_device.connections == {
        (CONNECTION_NETWORK_MAC, "00:11:22:33:44:55"),
        (CONNECTION_UPNP, "uuid:RINCON_test"),
    }
    assert reg_device.manufacturer == "Sonos"
    assert reg_device.name == "Zone A"
    # Default device provides battery info, area should not be suggested
    assert reg_device.suggested_area is None


async def test_device_registry_not_portable(
    hass: HomeAssistant, device_registry: DeviceRegistry, async_setup_sonos, soco
) -> None:
    """Test non-portable sonos device registered in the device registry to ensure area suggested."""
    soco.get_battery_info.return_value = {}
    await async_setup_sonos()

    reg_device = device_registry.async_get_device(
        identifiers={("sonos", "RINCON_test")}
    )
    assert reg_device is not None
    assert reg_device.suggested_area == "Zone A"


async def test_entity_basic(
    hass: HomeAssistant,
    async_autosetup_sonos,
    discover,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test basic state and attributes."""
    entity_id = "media_player.zone_a"
    entity_entry = entity_registry.async_get(entity_id)
    assert entity_entry == snapshot(name=f"{entity_entry.entity_id}-entry")
    state = hass.states.get(entity_entry.entity_id)
    assert state == snapshot(name=f"{entity_entry.entity_id}-state")


@pytest.mark.parametrize(
    ("media_content_type", "media_content_id", "enqueue", "test_result"),
    [
        (
            "artist",
            "A:ALBUMARTIST/Beatles",
            MediaPlayerEnqueue.REPLACE,
            {
                "title": "All",
                "item_id": "A:ALBUMARTIST/Beatles/",
                "clear_queue": 1,
                "position": None,
                "play": 1,
                "play_pos": 0,
            },
        ),
        (
            "genre",
            "A:GENRE/Classic%20Rock",
            MediaPlayerEnqueue.ADD,
            {
                "title": "All",
                "item_id": "A:GENRE/Classic%20Rock/",
                "clear_queue": 0,
                "position": None,
                "play": 0,
                "play_pos": 0,
            },
        ),
        (
            "album",
            "A:ALBUM/Abbey%20Road",
            MediaPlayerEnqueue.NEXT,
            {
                "title": "Abbey Road",
                "item_id": "A:ALBUM/Abbey%20Road",
                "clear_queue": 0,
                "position": 1,
                "play": 0,
                "play_pos": 0,
            },
        ),
        (
            "composer",
            "A:COMPOSER/Carlos%20Santana",
            MediaPlayerEnqueue.PLAY,
            {
                "title": "All",
                "item_id": "A:COMPOSER/Carlos%20Santana/",
                "clear_queue": 0,
                "position": 1,
                "play": 1,
                "play_pos": 9,
            },
        ),
        (
            "artist",
            "A:ALBUMARTIST/Beatles/Abbey%20Road",
            MediaPlayerEnqueue.REPLACE,
            {
                "title": "Abbey Road",
                "item_id": "A:ALBUMARTIST/Beatles/Abbey%20Road",
                "clear_queue": 1,
                "position": None,
                "play": 1,
                "play_pos": 0,
            },
        ),
    ],
)
async def test_play_media_library(
    hass: HomeAssistant,
    soco_factory: SoCoMockFactory,
    async_autosetup_sonos,
    media_content_type,
    media_content_id,
    enqueue,
    test_result,
) -> None:
    """Test playing local library with a variety of options."""
    sock_mock = soco_factory.mock_list.get("192.168.42.2")
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_MEDIA_CONTENT_TYPE: media_content_type,
            ATTR_MEDIA_CONTENT_ID: media_content_id,
            ATTR_MEDIA_ENQUEUE: enqueue,
        },
        blocking=True,
    )
    assert sock_mock.clear_queue.call_count == test_result["clear_queue"]
    assert sock_mock.add_to_queue.call_count == 1
    assert (
        sock_mock.add_to_queue.call_args_list[0].args[0].title == test_result["title"]
    )
    assert (
        sock_mock.add_to_queue.call_args_list[0].args[0].item_id
        == test_result["item_id"]
    )
    if test_result["position"] is not None:
        assert (
            sock_mock.add_to_queue.call_args_list[0].kwargs["position"]
            == test_result["position"]
        )
    else:
        assert "position" not in sock_mock.add_to_queue.call_args_list[0].kwargs
    assert (
        sock_mock.add_to_queue.call_args_list[0].kwargs["timeout"]
        == LONG_SERVICE_TIMEOUT
    )
    assert sock_mock.play_from_queue.call_count == test_result["play"]
    if test_result["play"] != 0:
        assert (
            sock_mock.play_from_queue.call_args_list[0].args[0]
            == test_result["play_pos"]
        )


_track_url = "S://192.168.42.100/music/iTunes/The%20Beatles/A%20Hard%20Day%2fs%I%20Should%20Have%20Known%20Better.mp3"


async def test_play_media_lib_track_play(
    hass: HomeAssistant,
    soco_factory: SoCoMockFactory,
    async_autosetup_sonos,
) -> None:
    """Tests playing media track with enqueue mode play."""
    soco_mock = soco_factory.mock_list.get("192.168.42.2")
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_MEDIA_CONTENT_TYPE: "track",
            ATTR_MEDIA_CONTENT_ID: _track_url,
            ATTR_MEDIA_ENQUEUE: MediaPlayerEnqueue.PLAY,
        },
        blocking=True,
    )
    assert soco_mock.add_uri_to_queue.call_count == 1
    assert soco_mock.add_uri_to_queue.call_args_list[0].args[0] == _track_url
    assert soco_mock.add_uri_to_queue.call_args_list[0].kwargs["position"] == 1
    assert (
        soco_mock.add_uri_to_queue.call_args_list[0].kwargs["timeout"]
        == LONG_SERVICE_TIMEOUT
    )
    assert soco_mock.play_from_queue.call_count == 1
    assert soco_mock.play_from_queue.call_args_list[0].args[0] == 9


async def test_play_media_lib_track_next(
    hass: HomeAssistant,
    soco_factory: SoCoMockFactory,
    async_autosetup_sonos,
) -> None:
    """Tests playing media track with enqueue mode next."""
    soco_mock = soco_factory.mock_list.get("192.168.42.2")
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_MEDIA_CONTENT_TYPE: "track",
            ATTR_MEDIA_CONTENT_ID: _track_url,
            ATTR_MEDIA_ENQUEUE: MediaPlayerEnqueue.NEXT,
        },
        blocking=True,
    )
    assert soco_mock.add_uri_to_queue.call_count == 1
    assert soco_mock.add_uri_to_queue.call_args_list[0].args[0] == _track_url
    assert soco_mock.add_uri_to_queue.call_args_list[0].kwargs["position"] == 1
    assert (
        soco_mock.add_uri_to_queue.call_args_list[0].kwargs["timeout"]
        == LONG_SERVICE_TIMEOUT
    )
    assert soco_mock.play_from_queue.call_count == 0


async def test_play_media_lib_track_replace(
    hass: HomeAssistant,
    soco_factory: SoCoMockFactory,
    async_autosetup_sonos,
) -> None:
    """Tests playing media track with enqueue mode replace."""
    soco_mock = soco_factory.mock_list.get("192.168.42.2")
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_MEDIA_CONTENT_TYPE: "track",
            ATTR_MEDIA_CONTENT_ID: _track_url,
            ATTR_MEDIA_ENQUEUE: MediaPlayerEnqueue.REPLACE,
        },
        blocking=True,
    )
    assert soco_mock.play_uri.call_count == 1
    assert soco_mock.play_uri.call_args_list[0].args[0] == _track_url
    assert soco_mock.play_uri.call_args_list[0].kwargs["force_radio"] is False


async def test_play_media_lib_track_add(
    hass: HomeAssistant,
    soco_factory: SoCoMockFactory,
    async_autosetup_sonos,
) -> None:
    """Tests playing media track with enqueue mode add."""
    soco_mock = soco_factory.mock_list.get("192.168.42.2")
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_MEDIA_CONTENT_TYPE: "track",
            ATTR_MEDIA_CONTENT_ID: _track_url,
            ATTR_MEDIA_ENQUEUE: MediaPlayerEnqueue.ADD,
        },
        blocking=True,
    )
    assert soco_mock.add_uri_to_queue.call_count == 1
    assert soco_mock.add_uri_to_queue.call_args_list[0].args[0] == _track_url
    assert (
        soco_mock.add_uri_to_queue.call_args_list[0].kwargs["timeout"]
        == LONG_SERVICE_TIMEOUT
    )
    assert soco_mock.play_from_queue.call_count == 0


_share_link: str = "spotify:playlist:abcdefghij0123456789XY"


async def test_play_media_share_link_add(
    hass: HomeAssistant,
    soco_factory: SoCoMockFactory,
    async_autosetup_sonos,
    soco_sharelink,
) -> None:
    """Tests playing a share link with enqueue option add."""
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_MEDIA_CONTENT_TYPE: "playlist",
            ATTR_MEDIA_CONTENT_ID: _share_link,
            ATTR_MEDIA_ENQUEUE: MediaPlayerEnqueue.ADD,
        },
        blocking=True,
    )
    assert soco_sharelink.add_share_link_to_queue.call_count == 1
    assert (
        soco_sharelink.add_share_link_to_queue.call_args_list[0].args[0] == _share_link
    )
    assert (
        soco_sharelink.add_share_link_to_queue.call_args_list[0].kwargs["timeout"]
        == LONG_SERVICE_TIMEOUT
    )


async def test_play_media_share_link_next(
    hass: HomeAssistant,
    soco_factory: SoCoMockFactory,
    async_autosetup_sonos,
    soco_sharelink,
) -> None:
    """Tests playing a share link with enqueue option next."""
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_MEDIA_CONTENT_TYPE: "playlist",
            ATTR_MEDIA_CONTENT_ID: _share_link,
            ATTR_MEDIA_ENQUEUE: MediaPlayerEnqueue.NEXT,
        },
        blocking=True,
    )
    assert soco_sharelink.add_share_link_to_queue.call_count == 1
    assert (
        soco_sharelink.add_share_link_to_queue.call_args_list[0].args[0] == _share_link
    )
    assert (
        soco_sharelink.add_share_link_to_queue.call_args_list[0].kwargs["timeout"]
        == LONG_SERVICE_TIMEOUT
    )
    assert (
        soco_sharelink.add_share_link_to_queue.call_args_list[0].kwargs["position"] == 1
    )


async def test_play_media_share_link_play(
    hass: HomeAssistant,
    soco_factory: SoCoMockFactory,
    async_autosetup_sonos,
    soco_sharelink,
) -> None:
    """Tests playing a share link with enqueue option play."""
    soco_mock = soco_factory.mock_list.get("192.168.42.2")
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_MEDIA_CONTENT_TYPE: "playlist",
            ATTR_MEDIA_CONTENT_ID: _share_link,
            ATTR_MEDIA_ENQUEUE: MediaPlayerEnqueue.PLAY,
        },
        blocking=True,
    )
    assert soco_sharelink.add_share_link_to_queue.call_count == 1
    assert (
        soco_sharelink.add_share_link_to_queue.call_args_list[0].args[0] == _share_link
    )
    assert (
        soco_sharelink.add_share_link_to_queue.call_args_list[0].kwargs["timeout"]
        == LONG_SERVICE_TIMEOUT
    )
    assert (
        soco_sharelink.add_share_link_to_queue.call_args_list[0].kwargs["position"] == 1
    )
    assert soco_mock.play_from_queue.call_count == 1
    soco_mock.play_from_queue.assert_called_with(9)


async def test_play_media_share_link_replace(
    hass: HomeAssistant,
    soco_factory: SoCoMockFactory,
    async_autosetup_sonos,
    soco_sharelink,
) -> None:
    """Tests playing a share link with enqueue option replace."""
    soco_mock = soco_factory.mock_list.get("192.168.42.2")
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_MEDIA_CONTENT_TYPE: "playlist",
            ATTR_MEDIA_CONTENT_ID: _share_link,
            ATTR_MEDIA_ENQUEUE: MediaPlayerEnqueue.REPLACE,
        },
        blocking=True,
    )
    assert soco_mock.clear_queue.call_count == 1
    assert soco_sharelink.add_share_link_to_queue.call_count == 1
    assert (
        soco_sharelink.add_share_link_to_queue.call_args_list[0].args[0] == _share_link
    )
    assert (
        soco_sharelink.add_share_link_to_queue.call_args_list[0].kwargs["timeout"]
        == LONG_SERVICE_TIMEOUT
    )
    assert soco_mock.play_from_queue.call_count == 1
    soco_mock.play_from_queue.assert_called_with(0)


_mock_playlists = [
    MockMusicServiceItem(
        "playlist1",
        "S://192.168.1.68/music/iTunes/iTunes%20Music%20Library.xml#GUID_1",
        "A:PLAYLISTS",
        "object.container.playlistContainer",
    ),
    MockMusicServiceItem(
        "playlist2",
        "S://192.168.1.68/music/iTunes/iTunes%20Music%20Library.xml#GUID_2",
        "A:PLAYLISTS",
        "object.container.playlistContainer",
    ),
]


@pytest.mark.parametrize(
    ("media_content_id", "expected_item_id"),
    [
        (
            _mock_playlists[0].item_id,
            _mock_playlists[0].item_id,
        ),
        (
            f"S:{_mock_playlists[1].title}",
            _mock_playlists[1].item_id,
        ),
    ],
)
async def test_play_media_music_library_playlist(
    hass: HomeAssistant,
    soco_factory: SoCoMockFactory,
    async_autosetup_sonos,
    discover,
    media_content_id,
    expected_item_id,
) -> None:
    """Test that playlists can be found by id or title."""
    soco_mock = soco_factory.mock_list.get("192.168.42.2")
    soco_mock.music_library.get_playlists.return_value = _mock_playlists

    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_MEDIA_CONTENT_TYPE: "playlist",
            ATTR_MEDIA_CONTENT_ID: media_content_id,
        },
        blocking=True,
    )

    assert soco_mock.clear_queue.call_count == 1
    assert soco_mock.add_to_queue.call_count == 1
    assert soco_mock.add_to_queue.call_args_list[0].args[0].item_id == expected_item_id
    assert soco_mock.play_from_queue.call_count == 1


async def test_play_media_music_library_playlist_dne(
    hass: HomeAssistant,
    soco_factory: SoCoMockFactory,
    async_autosetup_sonos,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test error handling when attempting to play a non-existent playlist ."""
    media_content_id = "S:nonexistent"
    soco_mock = soco_factory.mock_list.get("192.168.42.2")
    soco_mock.music_library.get_playlists.return_value = _mock_playlists

    with pytest.raises(
        ServiceValidationError,
        match=f"Could not find Sonos playlist: {media_content_id}",
    ):
        await hass.services.async_call(
            MP_DOMAIN,
            SERVICE_PLAY_MEDIA,
            {
                ATTR_ENTITY_ID: "media_player.zone_a",
                ATTR_MEDIA_CONTENT_TYPE: "playlist",
                ATTR_MEDIA_CONTENT_ID: media_content_id,
            },
            blocking=True,
        )
    assert soco_mock.play_uri.call_count == 0


async def test_play_sonos_playlist(
    hass: HomeAssistant,
    async_autosetup_sonos,
    soco: MockSoCo,
    sonos_playlists: SearchResult,
) -> None:
    """Test that sonos playlists can be played."""

    # Test a successful call
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_MEDIA_CONTENT_TYPE: "playlist",
            ATTR_MEDIA_CONTENT_ID: "sample playlist",
        },
        blocking=True,
    )
    assert soco.clear_queue.call_count == 1
    assert soco.add_to_queue.call_count == 1
    soco.add_to_queue.asset_called_with(
        sonos_playlists[0], timeout=LONG_SERVICE_TIMEOUT
    )

    # Test playing a non-existent playlist
    soco.clear_queue.reset_mock()
    soco.add_to_queue.reset_mock()
    media_content_id: str = "bad playlist"
    with pytest.raises(
        ServiceValidationError,
        match=f"Could not find Sonos playlist: {media_content_id}",
    ):
        await hass.services.async_call(
            MP_DOMAIN,
            SERVICE_PLAY_MEDIA,
            {
                ATTR_ENTITY_ID: "media_player.zone_a",
                ATTR_MEDIA_CONTENT_TYPE: "playlist",
                ATTR_MEDIA_CONTENT_ID: media_content_id,
            },
            blocking=True,
        )
    assert soco.clear_queue.call_count == 0
    assert soco.add_to_queue.call_count == 0


@pytest.mark.parametrize(
    ("source", "result"),
    [
        (
            SOURCE_LINEIN,
            {
                "switch_to_line_in": 1,
            },
        ),
        (
            SOURCE_TV,
            {
                "switch_to_tv": 1,
            },
        ),
    ],
)
async def test_select_source_line_in_tv(
    hass: HomeAssistant,
    soco_factory: SoCoMockFactory,
    async_autosetup_sonos,
    source: str,
    result: dict[str, Any],
) -> None:
    """Test the select_source method with a variety of inputs."""
    soco_mock = soco_factory.mock_list.get("192.168.42.2")
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_SELECT_SOURCE,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_INPUT_SOURCE: source,
        },
        blocking=True,
    )
    assert soco_mock.switch_to_line_in.call_count == result.get("switch_to_line_in", 0)
    assert soco_mock.switch_to_tv.call_count == result.get("switch_to_tv", 0)


@pytest.mark.parametrize(
    ("source", "result"),
    [
        (
            "James Taylor Radio",
            {
                "play_uri": 1,
                "play_uri_uri": "x-sonosapi-radio:ST%3aetc",
                "play_uri_title": "James Taylor Radio",
            },
        ),
        (
            "66 - Watercolors",
            {
                "play_uri": 1,
                "play_uri_uri": "x-sonosapi-hls:Api%3atune%3aliveAudio%3ajazzcafe%3aetc",
                "play_uri_title": "66 - Watercolors",
            },
        ),
    ],
)
async def test_select_source_play_uri(
    hass: HomeAssistant,
    soco_factory: SoCoMockFactory,
    async_autosetup_sonos,
    source: str,
    result: dict[str, Any],
) -> None:
    """Test the select_source method with a variety of inputs."""
    soco_mock = soco_factory.mock_list.get("192.168.42.2")
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_SELECT_SOURCE,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_INPUT_SOURCE: source,
        },
        blocking=True,
    )
    assert soco_mock.play_uri.call_count == result.get("play_uri")
    soco_mock.play_uri.assert_called_with(
        result.get("play_uri_uri"),
        title=result.get("play_uri_title"),
        timeout=LONG_SERVICE_TIMEOUT,
    )


@pytest.mark.parametrize(
    ("source", "result"),
    [
        (
            "1984",
            {
                "add_to_queue": 1,
                "add_to_queue_item_id": "A:ALBUMARTIST/Aerosmith/1984",
                "clear_queue": 1,
                "play_from_queue": 1,
            },
        ),
    ],
)
async def test_select_source_play_queue(
    hass: HomeAssistant,
    soco_factory: SoCoMockFactory,
    async_autosetup_sonos,
    source: str,
    result: dict[str, Any],
) -> None:
    """Test the select_source method with a variety of inputs."""
    soco_mock = soco_factory.mock_list.get("192.168.42.2")
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_SELECT_SOURCE,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_INPUT_SOURCE: source,
        },
        blocking=True,
    )
    assert soco_mock.clear_queue.call_count == result.get("clear_queue")
    assert soco_mock.add_to_queue.call_count == result.get("add_to_queue")
    assert soco_mock.add_to_queue.call_args_list[0].args[0].item_id == result.get(
        "add_to_queue_item_id"
    )
    assert (
        soco_mock.add_to_queue.call_args_list[0].kwargs["timeout"]
        == LONG_SERVICE_TIMEOUT
    )
    assert soco_mock.play_from_queue.call_count == result.get("play_from_queue")
    soco_mock.play_from_queue.assert_called_with(0)


async def test_select_source_error(
    hass: HomeAssistant,
    soco_factory: SoCoMockFactory,
    async_autosetup_sonos,
) -> None:
    """Test the select_source method with a variety of inputs."""
    with pytest.raises(ServiceValidationError) as sve:
        await hass.services.async_call(
            MP_DOMAIN,
            SERVICE_SELECT_SOURCE,
            {
                ATTR_ENTITY_ID: "media_player.zone_a",
                ATTR_INPUT_SOURCE: "invalid_source",
            },
            blocking=True,
        )
    assert "invalid_source" in str(sve.value)
    assert "Could not find a Sonos favorite" in str(sve.value)


async def test_shuffle_set(
    hass: HomeAssistant,
    soco: MockSoCo,
    async_autosetup_sonos,
) -> None:
    """Test the set shuffle method."""
    assert soco.play_mode == "NORMAL"

    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_SHUFFLE_SET,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_MEDIA_SHUFFLE: True,
        },
        blocking=True,
    )
    assert soco.play_mode == "SHUFFLE_NOREPEAT"

    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_SHUFFLE_SET,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_MEDIA_SHUFFLE: False,
        },
        blocking=True,
    )
    assert soco.play_mode == "NORMAL"


async def test_shuffle_get(
    hass: HomeAssistant,
    soco: MockSoCo,
    async_autosetup_sonos,
    no_media_event: SonosMockEvent,
) -> None:
    """Test the get shuffle attribute by simulating a Sonos Event."""
    subscription = soco.avTransport.subscribe.return_value
    sub_callback = subscription.callback

    state = hass.states.get("media_player.zone_a")
    assert state.attributes[ATTR_MEDIA_SHUFFLE] is False

    no_media_event.variables["current_play_mode"] = "SHUFFLE_NOREPEAT"
    sub_callback(no_media_event)
    await hass.async_block_till_done(wait_background_tasks=True)
    state = hass.states.get("media_player.zone_a")
    assert state.attributes[ATTR_MEDIA_SHUFFLE] is True

    # The integration keeps a copy of the last event to check for
    # changes, so we create a new event.
    no_media_event = SonosMockEvent(
        soco, soco.avTransport, no_media_event.variables.copy()
    )
    no_media_event.variables["current_play_mode"] = "NORMAL"
    sub_callback(no_media_event)
    await hass.async_block_till_done(wait_background_tasks=True)
    state = hass.states.get("media_player.zone_a")
    assert state.attributes[ATTR_MEDIA_SHUFFLE] is False


async def test_repeat_set(
    hass: HomeAssistant,
    soco: MockSoCo,
    async_autosetup_sonos,
) -> None:
    """Test the set repeat method."""
    assert soco.play_mode == "NORMAL"
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_REPEAT_SET,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_MEDIA_REPEAT: RepeatMode.ALL,
        },
        blocking=True,
    )
    assert soco.play_mode == "REPEAT_ALL"

    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_REPEAT_SET,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_MEDIA_REPEAT: RepeatMode.ONE,
        },
        blocking=True,
    )
    assert soco.play_mode == "REPEAT_ONE"

    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_REPEAT_SET,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_MEDIA_REPEAT: RepeatMode.OFF,
        },
        blocking=True,
    )
    assert soco.play_mode == "NORMAL"


async def test_repeat_get(
    hass: HomeAssistant,
    soco: MockSoCo,
    async_autosetup_sonos,
    no_media_event: SonosMockEvent,
) -> None:
    """Test the get repeat attribute by simulating a Sonos Event."""
    subscription = soco.avTransport.subscribe.return_value
    sub_callback = subscription.callback

    state = hass.states.get("media_player.zone_a")
    assert state.attributes[ATTR_MEDIA_REPEAT] == RepeatMode.OFF

    no_media_event.variables["current_play_mode"] = "REPEAT_ALL"
    sub_callback(no_media_event)
    await hass.async_block_till_done(wait_background_tasks=True)
    state = hass.states.get("media_player.zone_a")
    assert state.attributes[ATTR_MEDIA_REPEAT] == RepeatMode.ALL

    no_media_event = SonosMockEvent(
        soco, soco.avTransport, no_media_event.variables.copy()
    )
    no_media_event.variables["current_play_mode"] = "REPEAT_ONE"
    sub_callback(no_media_event)
    await hass.async_block_till_done(wait_background_tasks=True)
    state = hass.states.get("media_player.zone_a")
    assert state.attributes[ATTR_MEDIA_REPEAT] == RepeatMode.ONE

    no_media_event = SonosMockEvent(
        soco, soco.avTransport, no_media_event.variables.copy()
    )
    no_media_event.variables["current_play_mode"] = "NORMAL"
    sub_callback(no_media_event)
    await hass.async_block_till_done(wait_background_tasks=True)
    state = hass.states.get("media_player.zone_a")
    assert state.attributes[ATTR_MEDIA_REPEAT] == RepeatMode.OFF


async def test_play_media_favorite_item_id(
    hass: HomeAssistant,
    soco_factory: SoCoMockFactory,
    async_autosetup_sonos,
) -> None:
    """Test playing media with a favorite item id."""
    soco_mock = soco_factory.mock_list.get("192.168.42.2")
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
            ATTR_MEDIA_CONTENT_TYPE: "favorite_item_id",
            ATTR_MEDIA_CONTENT_ID: "FV:2/4",
        },
        blocking=True,
    )
    assert soco_mock.play_uri.call_count == 1
    assert (
        soco_mock.play_uri.call_args_list[0].args[0]
        == "x-sonosapi-hls:Api%3atune%3aliveAudio%3ajazzcafe%3aetc"
    )
    assert (
        soco_mock.play_uri.call_args_list[0].kwargs["timeout"] == LONG_SERVICE_TIMEOUT
    )
    assert soco_mock.play_uri.call_args_list[0].kwargs["title"] == "66 - Watercolors"

    # Test exception handling with an invalid id.
    with pytest.raises(ValueError) as sve:
        await hass.services.async_call(
            MP_DOMAIN,
            SERVICE_PLAY_MEDIA,
            {
                ATTR_ENTITY_ID: "media_player.zone_a",
                ATTR_MEDIA_CONTENT_TYPE: "favorite_item_id",
                ATTR_MEDIA_CONTENT_ID: "UNKNOWN_ID",
            },
            blocking=True,
        )
    assert "UNKNOWN_ID" in str(sve.value)


async def _setup_hass(hass: HomeAssistant):
    await async_setup_component(
        hass,
        SONOS_DOMAIN,
        {
            "sonos": {
                "media_player": {
                    "interface_addr": "127.0.0.1",
                    "hosts": ["10.10.10.1", "10.10.10.2"],
                }
            }
        },
    )
    await hass.async_block_till_done()


async def test_service_snapshot_restore(
    hass: HomeAssistant,
    soco_factory: SoCoMockFactory,
) -> None:
    """Test the snapshot and restore services."""
    soco_factory.cache_mock(MockSoCo(), "10.10.10.1", "Living Room")
    soco_factory.cache_mock(MockSoCo(), "10.10.10.2", "Bedroom")
    await _setup_hass(hass)
    with patch(
        "homeassistant.components.sonos.speaker.Snapshot.snapshot"
    ) as mock_snapshot:
        await hass.services.async_call(
            SONOS_DOMAIN,
            SERVICE_SNAPSHOT,
            {
                ATTR_ENTITY_ID: ["media_player.living_room", "media_player.bedroom"],
            },
            blocking=True,
        )
    assert mock_snapshot.call_count == 2

    with patch(
        "homeassistant.components.sonos.speaker.Snapshot.restore"
    ) as mock_restore:
        await hass.services.async_call(
            SONOS_DOMAIN,
            SERVICE_RESTORE,
            {
                ATTR_ENTITY_ID: ["media_player.living_room", "media_player.bedroom"],
            },
            blocking=True,
        )
    assert mock_restore.call_count == 2


async def test_volume(
    hass: HomeAssistant,
    soco: MockSoCo,
    async_autosetup_sonos,
) -> None:
    """Test the media player volume services."""
    initial_volume = soco.volume

    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_VOLUME_UP,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
        },
        blocking=True,
    )
    assert soco.volume == initial_volume + VOLUME_INCREMENT

    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_VOLUME_DOWN,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
        },
        blocking=True,
    )
    assert soco.volume == initial_volume

    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_VOLUME_SET,
        {ATTR_ENTITY_ID: "media_player.zone_a", ATTR_MEDIA_VOLUME_LEVEL: 0.30},
        blocking=True,
    )
    # SoCo uses 0..100 for its range.
    assert soco.volume == 30


@pytest.mark.parametrize(
    ("service", "client_call"),
    [
        (SERVICE_MEDIA_PLAY, "play"),
        (SERVICE_MEDIA_PAUSE, "pause"),
        (SERVICE_MEDIA_STOP, "stop"),
        (SERVICE_MEDIA_NEXT_TRACK, "next"),
        (SERVICE_MEDIA_PREVIOUS_TRACK, "previous"),
        (SERVICE_CLEAR_PLAYLIST, "clear_queue"),
    ],
)
async def test_media_transport(
    hass: HomeAssistant,
    soco: MockSoCo,
    async_autosetup_sonos,
    service: str,
    client_call: str,
) -> None:
    """Test the media player transport services."""
    await hass.services.async_call(
        MP_DOMAIN,
        service,
        {
            ATTR_ENTITY_ID: "media_player.zone_a",
        },
        blocking=True,
    )
    assert getattr(soco, client_call).call_count == 1
