# ruff: noqa: INP001, S101 - standalone pytest module; assertions are test-only
"""Behavioural tests for the secure bridge transport endpoint."""

import pytest

from custom_components.eufy_sdk.bridge_access import BridgeEndpoint

TOKEN = "0123456789abcdef" * 4


def test_constructs_verified_tls_origins_without_disclosing_the_token() -> None:
    """The bridge token is sent in an HTTP header, never rendered in the endpoint."""
    endpoint = BridgeEndpoint(host="bridge.example.invalid", port=443, token=TOKEN)
    assert endpoint.ws_url == "wss://bridge.example.invalid:443/ws"
    assert endpoint.https_origin == "https://bridge.example.invalid:443"
    assert endpoint.auth_headers() == {"Authorization": f"Bearer {TOKEN}"}
    assert TOKEN not in repr(endpoint)


@pytest.mark.parametrize("token", [None, "", "abc", "F" * 64, "a" * 63, TOKEN + "\n"])
def test_invalid_tokens_fail_closed(token: object) -> None:
    """Missing, truncated and noncanonical tokens must not authenticate."""
    with pytest.raises(ValueError, match="bridge access token"):
        BridgeEndpoint(host="bridge", port=3000, token=token)


@pytest.mark.parametrize(
    "host",
    ["", "https://bridge", "bridge/path", "user@bridge", "bridge?x=1", "bridge\nexample"],
)
def test_invalid_hosts_are_rejected(host: str) -> None:
    """Untrusted user info and URL fragments cannot override the TLS origin."""
    with pytest.raises(ValueError, match="bridge host"):
        BridgeEndpoint(host=host, port=3000, token=TOKEN)


@pytest.mark.parametrize("port", [0, 65536, -1, True])
def test_invalid_ports_are_rejected(port: int) -> None:
    """The service port must be a valid integer TCP port."""
    with pytest.raises(ValueError, match="bridge port"):
        BridgeEndpoint(host="bridge", port=port, token=TOKEN)


def test_ipv6_authority_uses_brackets_for_tls_urls() -> None:
    """IPv6 literals require brackets when used as an HTTPS origin."""
    endpoint = BridgeEndpoint(host="::1", port=444, token=TOKEN)
    assert endpoint.ws_url == "wss://[::1]:444/ws"


def test_media_urls_remain_on_the_authenticated_origin() -> None:
    """Relative snapshot and event image routes preserve a single fixed origin."""
    endpoint = BridgeEndpoint(host="bridge", port=3000, token=TOKEN)
    assert (
        endpoint.media_url("/snapshot/CAM_1?mode=stored")
        == "https://bridge:3000/snapshot/CAM_1?mode=stored"
    )
    assert (
        endpoint.media_url("/event-image/CAM_1")
        == "https://bridge:3000/event-image/CAM_1"
    )


@pytest.mark.parametrize(
    "path",
    [
        "https://untrusted.invalid/snapshot/CAM_1",
        "//untrusted.invalid/clip/CAM_1",
        "/snapshot/../healthz",
        "/snapshot/CAM_1?other=1",
        "/snapshot/CAM_1#fragment",
        "/snapshot/CAM_1/extra",
        "/healthz",
        "/snapshot/%2Fetc",
    ],
)
def test_media_requests_cannot_escape_the_configured_origin(path: str) -> None:
    """Absolute routes, traversal and unsupported parameters are forbidden."""
    endpoint = BridgeEndpoint(host="bridge", port=3000, token=TOKEN)
    with pytest.raises(ValueError, match="invalid bridge media path"):
        endpoint.media_url(path)
