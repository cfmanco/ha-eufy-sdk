"""Security tests for the shared authenticated bridge transport."""

import unittest
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest

from custom_components.eufy_sdk.api import (
    EufySdkApiClient,
    EufySdkApiClientBridgeAccessError,
    EufySdkApiClientCommunicationError,
)

TOKEN = "0123456789abcdef" * 4


def _session() -> Mock:
    """Create a mock aiohttp session with a controllable WebSocket upgrade."""
    session = Mock()
    session.ws_connect = AsyncMock()
    return session


class BridgeTransportTests(unittest.IsolatedAsyncioTestCase):
    """Verify authenticated bridge interactions without contacting a real host."""

    async def test_ws_uses_wss_bearer_and_requires_schema_two_greeting(self) -> None:
        """A valid TLS upgrade sends a secret header and validates the protocol."""
        session = _session()
        websocket = Mock()
        websocket.closed = False
        websocket.receive_json = AsyncMock(
            return_value={"event": "hello", "schemaVersion": 2, "bridgeId": "fixture"}
        )
        websocket.close = AsyncMock()
        session.ws_connect.return_value = websocket
        client = EufySdkApiClient("bridge", 3000, session, bridge_token=TOKEN)
        with patch(
            "custom_components.eufy_sdk.api.asyncio.ensure_future", return_value=Mock()
        ):
            await client.connect()
        assert client.connected
        assert client.bridge_id == "fixture"
        args = session.ws_connect.call_args
        assert args.args[0] == "wss://bridge:3000/ws"
        assert args.kwargs["headers"] == {"Authorization": f"Bearer {TOKEN}"}
        assert args.kwargs["heartbeat"] == 30

    async def test_ws_rejects_legacy_protocol_even_with_valid_token(self) -> None:
        """An old schema cannot create an authenticated control session."""
        session = _session()
        websocket = Mock()
        websocket.receive_json = AsyncMock(
            return_value={"event": "hello", "schemaVersion": 1}
        )
        websocket.close = AsyncMock()
        session.ws_connect.return_value = websocket
        client = EufySdkApiClient("bridge", 3000, session, bridge_token=TOKEN)
        with pytest.raises(EufySdkApiClientCommunicationError, match="protocol version"):
            await client.connect()
        websocket.close.assert_awaited_once()
        assert not client.connected

    async def test_ws_access_denied_has_distinct_error_without_secret(self) -> None:
        """Bridge access denial is not mistaken for Eufy account authentication."""
        session = _session()
        session.ws_connect.side_effect = aiohttp.WSServerHandshakeError(
            request_info=Mock(real_url="wss://bridge:3000/ws"),
            history=(),
            status=401,
            message="Unauthorized",
        )
        client = EufySdkApiClient("bridge", 3000, session, bridge_token=TOKEN)
        with pytest.raises(EufySdkApiClientBridgeAccessError) as caught:
            await client.connect()
        assert TOKEN not in str(caught.value)

    async def test_media_fetch_uses_https_bearer_and_disables_redirects(self) -> None:
        """The media client never forwards credentials to a redirected origin."""
        session = _session()
        response = Mock(status=200)
        response.read = AsyncMock(return_value=b"jpeg")
        context = Mock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=False)
        session.get.return_value = context
        client = EufySdkApiClient("bridge", 3000, session, bridge_token=TOKEN)
        assert await client.media_get("/snapshot/CAM_1?mode=stored") == b"jpeg"
        args = session.get.call_args
        assert args.args[0] == "https://bridge:3000/snapshot/CAM_1?mode=stored"
        assert args.kwargs["headers"] == {"Authorization": f"Bearer {TOKEN}"}
        assert args.kwargs["allow_redirects"] is False
        context.__aexit__.assert_awaited_once()

    async def test_media_get_rejects_401_and_302_without_returning_bytes(self) -> None:
        """Rejection or redirects must never return protected media content."""
        session = _session()
        response = Mock(status=401)
        response.read = AsyncMock(return_value=b"private")
        context = Mock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=False)
        session.get.return_value = context
        client = EufySdkApiClient("bridge", 3000, session, bridge_token=TOKEN)
        with pytest.raises(EufySdkApiClientBridgeAccessError):
            await client.media_get("/event-image/CAM_1")
        response.status = 302
        with pytest.raises(EufySdkApiClientCommunicationError):
            await client.media_get("/snapshot/CAM_1")
        response.read.assert_not_awaited()
