"""Fail-closed bridge endpoint validation and credential handling.

The bridge client and image entities share this contract. It never places the
bridge token in a URL or object representation.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field

_TOKEN_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_LABEL_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_MEDIA_PATTERN = re.compile(
    r"/(?:snapshot|event-image|clip|stream)/[A-Za-z0-9_-]{1,128}"
    r"(?:\?mode=(?:auto|stored|live))?\Z"
)


def valid_bridge_token(token: object) -> bool:
    """Return whether the provided value is a canonical 256-bit bridge secret."""
    return isinstance(token, str) and _TOKEN_PATTERN.fullmatch(token) is not None


def _host_authority(host: str) -> str:
    """Validate a DNS name or IP literal without accepting a URL or userinfo."""
    if not isinstance(host, str) or not host or host != host.strip():
        raise ValueError("bridge host must be a DNS name or IP address")

    if host.startswith("[") and host.endswith("]"):
        try:
            return f"[{ipaddress.IPv6Address(host[1:-1])}]"
        except ipaddress.AddressValueError as err:
            raise ValueError("invalid bridge IPv6 address") from err

    if ":" in host:
        try:
            return f"[{ipaddress.IPv6Address(host)}]"
        except ipaddress.AddressValueError as err:
            raise ValueError("invalid bridge IPv6 address") from err

    if len(host) > 253 or any(
        _LABEL_PATTERN.fullmatch(label) is None for label in host.split(".")
    ):
        raise ValueError("bridge host must be a DNS name or IP address")
    return host


@dataclass(frozen=True, slots=True)
class BridgeEndpoint:
    """One credential-bound, TLS-only bridge origin."""

    host: str
    port: int
    token: str = field(repr=False)

    def __post_init__(self) -> None:
        _host_authority(self.host)
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("bridge port must be between 1 and 65535")
        if not valid_bridge_token(self.token):
            raise ValueError("bridge access token must be 64 lowercase hexadecimal characters")

    @property
    def https_origin(self) -> str:
        """HTTPS endpoint; certificate verification is performed by aiohttp."""
        return f"https://{_host_authority(self.host)}:{self.port}"

    @property
    def ws_url(self) -> str:
        """Secure WebSocket endpoint."""
        return f"wss://{_host_authority(self.host)}:{self.port}/ws"

    def auth_headers(self) -> dict[str, str]:
        """Construct a per-request header, never a session-global credential."""
        return {"Authorization": f"Bearer {self.token}"}

    def media_url(self, path: str) -> str:
        """Allow only a single camera-media route at our own HTTPS origin."""
        if not isinstance(path, str) or _MEDIA_PATTERN.fullmatch(path) is None:
            raise ValueError("invalid bridge media path")
        return self.https_origin + path
