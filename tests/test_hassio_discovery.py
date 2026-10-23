# ruff: noqa: ANN001, ANN201, ANN202, D100, D101, D102, INP001, PT009, SLF001

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from homeassistant.const import CONF_HOST, CONF_PORT

import custom_components.eufy_sdk as integration
from custom_components.eufy_sdk import config_flow

ADDON_UUID = "0123456789abcdef0123456789abcdef"
BRIDGE_ID = "3f2a0000-0000-4000-8000-000000000001"


def _discovery(host: str = "172.30.32.1", port: int = 3000, rtsp: int = 8554):
    return SimpleNamespace(
        name="eufy-sdk bridge",
        uuid=ADDON_UUID,
        config={CONF_HOST: host, CONF_PORT: port, "rtsp_port": rtsp},
    )


class HassioDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_unauthenticated_addon_discovery_cannot_provision_a_bridge(self):
        """Discovery lacks a verified TLS identity and bearer credential."""
        flow = config_flow.EufySdkFlowHandler()
        flow.async_abort = Mock(side_effect=lambda reason: f"abort:{reason}")

        result = await flow.async_step_hassio(_discovery())

        self.assertEqual(result, "abort:manual_secure_setup_required")
        flow.async_abort.assert_called_once_with(reason="manual_secure_setup_required")


class AdoptBridgeIdTests(unittest.TestCase):
    def _hass(self, *entries: SimpleNamespace) -> Mock:
        hass = Mock()
        hass.config_entries.async_entries = Mock(return_value=list(entries))
        return hass

    def _cfg(self, entry_id, unique_id, title="eufy bridge"):
        return SimpleNamespace(
            entry_id=entry_id, unique_id=unique_id, title=title, domain="eufy_sdk"
        )

    def test_an_entry_adopts_its_bridges_id(self):
        entry = self._cfg("a", "192.168.1.20:3000")
        hass = self._hass(entry)
        integration._adopt_bridge_id(hass, entry, BRIDGE_ID)
        hass.config_entries.async_update_entry.assert_called_once_with(
            entry, unique_id=BRIDGE_ID
        )

    def test_a_duplicate_entry_is_reported_not_rekeyed(self):
        first = self._cfg("a", BRIDGE_ID, "first")
        second = self._cfg("b", ADDON_UUID, "second")
        hass = self._hass(first, second)
        with self.assertLogs(integration.LOGGER, level="WARNING"):
            integration._adopt_bridge_id(hass, second, BRIDGE_ID)
        hass.config_entries.async_update_entry.assert_not_called()

    def test_an_older_bridge_changes_nothing(self):
        entry = self._cfg("a", "192.168.1.20:3000")
        hass = self._hass(entry)
        integration._adopt_bridge_id(hass, entry, None)
        hass.config_entries.async_update_entry.assert_not_called()


if __name__ == "__main__":
    unittest.main()
