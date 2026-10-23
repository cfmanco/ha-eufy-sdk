# ruff: noqa: ANN201, D100, D101, D102, INP001, PT009

import unittest
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.components.camera import Camera

from custom_components.eufy_sdk.camera import EufySdkCamera

BATTERY = "T8161P0000000001"
MAINS = "T8423P0000000001"
LEGACY_BATTERY = "T8170P0000000001"
LEGACY_MAINS = "T8425P0000000001"


def _camera(sn: str) -> EufySdkCamera:
    coordinator = Mock()
    coordinator.data = {
        BATTERY: {
            "capabilities": ["camera", "battery"],
            "state": {"battery": 80},
            "power": "battery",
            "stream": "/s",
        },
        # A mains-only model that still reports the battery capability and a level.
        MAINS: {
            "capabilities": ["camera", "battery"],
            "state": {"battery": 0},
            "power": "wired",
            "stream": "/s",
        },
        # A bridge without the `power` field.
        LEGACY_BATTERY: {
            "capabilities": ["camera", "battery"],
            "state": {"battery": 80},
            "stream": "/s",
        },
        LEGACY_MAINS: {"capabilities": ["camera", "battery"], "stream": "/s"},
    }
    return EufySdkCamera(coordinator, sn, "10.0.0.5", 3000, 8554)


class BatteryCameraStreamTests(unittest.IsolatedAsyncioTestCase):
    async def _starts_worker(self, sn: str) -> bool:
        with patch.object(Camera, "async_create_stream", AsyncMock()) as base:
            await _camera(sn).async_create_stream()
        return base.called

    async def test_a_battery_camera_never_starts_the_ha_stream_worker(self):
        # ha-eufy-sdk#83: the worker retries forever and each retry wakes the camera.
        with patch.object(Camera, "async_create_stream", AsyncMock()) as base:
            self.assertIsNone(await _camera(BATTERY).async_create_stream())
        base.assert_not_called()

    async def test_mains_camera_does_not_start_an_unsecured_stream_worker(self):
        cam = _camera(MAINS)
        with patch.object(Camera, "async_create_stream", AsyncMock()) as base:
            self.assertIsNone(await cam.async_create_stream())
        base.assert_not_called()

    async def test_unknown_power_sources_also_fail_closed(self):
        for sn in (LEGACY_BATTERY, LEGACY_MAINS):
            self.assertFalse(await self._starts_worker(sn))

    async def test_no_camera_exposes_direct_rtsp_transport(self):
        for sn in (BATTERY, MAINS, LEGACY_BATTERY, LEGACY_MAINS):
            self.assertIsNone(await _camera(sn).stream_source())


if __name__ == "__main__":
    unittest.main()
