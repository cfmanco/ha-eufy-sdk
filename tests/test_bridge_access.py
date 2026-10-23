"""Behaviour contract for the secure transport endpoint (no network calls)."""

import unittest

from custom_components.eufy_sdk.bridge_access import BridgeEndpoint

TOKEN = "0123456789abcdef" * 4


class BridgeEndpointTests(unittest.TestCase):
    def test_constructs_verified_tls_origins_and_bearer_header(self) -> None:
        endpoint = BridgeEndpoint(host="bridge.example.invalid", port=443, token=TOKEN)
        self.assertEqual(endpoint.ws_url, "wss://bridge.example.invalid:443/ws")
        self.assertEqual(endpoint.https_origin, "https://bridge.example.invalid:443")
        self.assertEqual(endpoint.auth_headers(), {"Authorization": f"Bearer {TOKEN}"})
        self.assertNotIn(TOKEN, repr(endpoint))

    def test_refuses_weak_tokens_and_malformed_endpoints(self) -> None:
        for token in (None, "", "abc", "F" * 64, "a" * 63, TOKEN + "\n"):
            with self.subTest(token=type(token).__name__):
                with self.assertRaises(ValueError):
                    BridgeEndpoint(host="bridge", port=3000, token=token)
        for host in ("", "https://bridge", "bridge/path", "user@bridge", "bridge?x=1", "bridge\nexample"):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    BridgeEndpoint(host=host, port=3000, token=TOKEN)
        for port in (0, 65536, -1, True):
            with self.subTest(port=port):
                with self.assertRaises(ValueError):
                    BridgeEndpoint(host="bridge", port=port, token=TOKEN)

    def test_ipv6_is_bracketed_for_tls_urls(self) -> None:
        endpoint = BridgeEndpoint(host="::1", port=444, token=TOKEN)
        self.assertEqual(endpoint.ws_url, "wss://[::1]:444/ws")

    def test_media_requests_cannot_escape_the_configured_origin(self) -> None:
        endpoint = BridgeEndpoint(host="bridge", port=3000, token=TOKEN)
        self.assertEqual(
            endpoint.media_url("/snapshot/CAM_1?mode=stored"),
            "https://bridge:3000/snapshot/CAM_1?mode=stored",
        )
        self.assertEqual(
            endpoint.media_url("/event-image/CAM_1"),
            "https://bridge:3000/event-image/CAM_1",
        )
        for path in (
            "https://untrusted.invalid/snapshot/CAM_1",
            "//untrusted.invalid/clip/CAM_1",
            "/snapshot/../healthz",
            "/snapshot/CAM_1?other=1",
            "/snapshot/CAM_1#fragment",
            "/snapshot/CAM_1/extra",
            "/healthz",
            "/snapshot/%2Fetc",
        ):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    endpoint.media_url(path)
