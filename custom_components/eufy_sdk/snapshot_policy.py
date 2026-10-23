"""Local per-camera snapshot acquisition policy."""

from __future__ import annotations

SNAPSHOT_POLICY_DEFAULT = "default"
SNAPSHOT_POLICY_AUTO = "auto"
SNAPSHOT_POLICY_STORED = "stored"
SNAPSHOT_POLICY_LIVE = "live"

SNAPSHOT_POLICY_OPTIONS = (
    SNAPSHOT_POLICY_DEFAULT,
    SNAPSHOT_POLICY_AUTO,
    SNAPSHOT_POLICY_STORED,
    SNAPSHOT_POLICY_LIVE,
)


def normalize_snapshot_policy(value: str | None) -> str:
    """Return a supported local policy, defaulting unknown/restored values safely."""
    return value if value in SNAPSHOT_POLICY_OPTIONS else SNAPSHOT_POLICY_DEFAULT


def bridge_mode_for_policy(policy: str | None) -> str | None:
    """Return the bridge query mode, or None for its configured behavior."""
    normalized = normalize_snapshot_policy(policy)
    return None if normalized == SNAPSHOT_POLICY_DEFAULT else normalized


def snapshot_path(sn: str, policy: str | None) -> str:
    """Build a relative image route for the authenticated media client."""
    path = f"/snapshot/{sn}"
    mode = bridge_mode_for_policy(policy)
    return f"{path}?mode={mode}" if mode else path


def snapshot_url(host: str, port: int, sn: str, policy: str | None) -> str:
    """Return a TLS URL for callers that only need a displayable media address."""
    return f"https://{host}:{port}{snapshot_path(sn, policy)}"
