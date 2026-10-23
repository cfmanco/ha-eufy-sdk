"""Camera platform — a live camera per streaming device, via the bridge's go2rtc."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import (
    EufySdkApiClientBridgeAccessError,
    EufySdkApiClientCommunicationError,
)
from .const import (
    ATTRIBUTION,
    CONF_GO2RTC_RTSP_PORT,
    CONF_HOST,
    CONF_PORT,
    DEFAULT_GO2RTC_RTSP_PORT,
    DOMAIN,
)
from .entity import device_offline
from .snapshot_policy import snapshot_path

if TYPE_CHECKING:
    from homeassistant.components.stream import Stream
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import EufySdkDataUpdateCoordinator
    from .data import EufySdkConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: EufySdkConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a camera for every device the bridge marked with a `stream` path."""
    coordinator = entry.runtime_data.coordinator
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    rtsp_port = int(entry.data.get(CONF_GO2RTC_RTSP_PORT, DEFAULT_GO2RTC_RTSP_PORT))
    async_add_entities(
        EufySdkCamera(coordinator, sn, host, port, rtsp_port)
        for sn, dev in coordinator.data.items()
        if dev.get("stream")
    )


class EufySdkCamera(CoordinatorEntity["EufySdkDataUpdateCoordinator"], Camera):
    """A camera via the bridge: live via go2rtc RTSP, stills via snapshot."""

    _attr_has_entity_name = True
    _attr_name = None  # the device name is the camera name
    _attr_attribution = ATTRIBUTION
    # Direct RTSP has no secure cross-host transport on this branch.
    _attr_supported_features = CameraEntityFeature(0)

    def __init__(
        self,
        coordinator: EufySdkDataUpdateCoordinator,
        sn: str,
        host: str,
        port: int,
        rtsp_port: int,
    ) -> None:
        """Bind to a device serial + the bridge address."""
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._sn = sn
        self._host = host
        self._port = port
        self._rtsp_port = rtsp_port
        self._attr_unique_id = f"{sn}_camera"
        dev = coordinator.data.get(sn, {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, sn)},
            name=dev.get("name") or sn,  # the user's device name (e.g. "Dining room")
            manufacturer="eufy",
            model=dev.get("model") or dev.get("codec"),  # the model code, not the codec
            serial_number=sn,
        )

    @property
    def available(self) -> bool:
        """Available while the bridge still reports this camera and it isn't offline."""
        return (
            super().available
            and self._sn in self.coordinator.data
            and not device_offline(self.coordinator.data.get(self._sn))
        )

    async def stream_source(self) -> str | None:
        """Refuse a direct RTSP URL until the authenticated media gateway exists."""
        return None

    async def async_create_stream(self) -> Stream | None:
        """Do not start Home Assistant video workers over unauthenticated RTSP."""
        return None

    async def async_camera_image(
        self,
        width: int | None = None,  # noqa: ARG002
        height: int | None = None,  # noqa: ARG002
    ) -> bytes | None:
        """Read a still via the shared HTTPS media client with its bearer header."""
        runtime = self.coordinator.config_entry.runtime_data
        path = snapshot_path(self._sn, runtime.snapshot_policy.get(self._sn))
        try:
            return await runtime.client.media_get(path, timeout=20)
        except EufySdkApiClientBridgeAccessError:
            # A rejected token requires a new credential, not an anonymous retry.
            raise
        except EufySdkApiClientCommunicationError:
            return None
