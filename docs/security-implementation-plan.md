# Secure companion integration implementation plan

Status: staged engineering specification, not a deployment authorisation.
Target: `dev/security-hardening` only. Source baseline: `main` at `42c30c7ac463e6a54d4f0880816e948548ba8c64`.
Contract: [hardened bridge schema 2](https://github.com/cfmanco/ha-eufy-sdk-bridge/blob/dev/security-hardening/docs/ws-protocol.md).
See [security architecture](security-architecture.md) for component, logical ERD and interaction diagrams.

## Decision record

The existing HACS integration calls `ws_connect("ws://...")` without headers, obtains JPEG snapshots over `http://...`, fetches event images independently, and returns unauthenticated RTSP sources. The hardened bridge rejects unauthorised WS and HTTP traffic and currently does not export go2rtc across the network. The two projects therefore require coordinated changes.

Options considered:
- **Native secure integration (chosen):** a single bridge bearer secret in the Home Assistant config entry, WSS for the control channel, HTTPS for JPEG media and a shared authenticated media helper. This aligns with the bridge's existing protocol and avoids extra software on the Home Assistant appliance.
- **Transparent local proxy without changing the integration (rejected):** would have to inject a secret into multiple protocols while Home Assistant continued constructing unauthenticated URLs and could conceal failures.
- **Client-token in URL (rejected):** exposes a reusable credential in logs, telemetry, history, entity state or RTSP URLs.

Live video needs a separate, demonstrated secure media path. Until then, explicitly disable the STREAM feature in the development integration. This is temporary and must be documented as a functional limitation, not considered completed live video.

## Step 0 — pin contract and test baseline

Files to inspect: `api.py`, `config_flow.py`, `__init__.py`, `camera.py`, `image.py`, `snapshot_policy.py`, `coordinator.py`, `const.py`, `translations/en.json`, `tests/test_*.py` and `.github/workflows/*.yml`.

- Confirm the bridge schema is 2, WS upgrade and all media routes require bearer headers, and `/healthz` is deliberately minimal anonymously.
- Capture baseline unit tests and Ruff checks with Python 3.14. The workflow currently only runs on `main` and `dev`, so include `dev/security-hardening` in push and PR triggers before interpreting an absent CI run.
- Confirm private TLS gateway hostname and certificate validation in deployment. Never put actual hostname/IP into repository docs.
- Check existing HA reauth behavior, cloud 2FA/captcha and all direct media GET call sites.

## Step 1 — secure control-plane client

Files: `custom_components/eufy_sdk/const.py`, `api.py`; add `tests/test_bridge_access.py`.

Interfaces:
- `CONF_BRIDGE_TOKEN = "bridge_token"` (private config-entry field).
- `SUPPORTED_SCHEMA = 2`.
- `EufySdkApiClient(host, port, session, bridge_token, ...)` requires a valid 64-character lowercase hexadecimal bearer.
- `bridge_media_get(path, *, timeout)` is the single authenticated HTTPS media method.
- `EufySdkApiClientBridgeAccessError` distinctly represents bridge HTTP 401/403 at upgrade or media access.

Pseudocode:

```text
client_initialise(host, port, token):
    reject token unless exactly 64 lowercase hexadecimal characters
    reject malformed host or absolute URLs that override configured origin
    ws_url  = validated_url(scheme="wss", host=host, port=port, path="/ws")
    base_url = validated_url(scheme="https", host=host, port=port)
    store bearer token only in private client memory

connect_or_reconnect():
    open ws_connect(ws_url, headers={"Authorization": bearer(token)})
    rely on normal TLS certificate and hostname verification
    on HTTP 401 or 403: raise BridgeAccessError, do not schedule blind retry
    on other temporary network failure: preserve bounded reconnect/backoff
    on hello: require schemaVersion == 2 or reject unsupported bridge

bridge_media_get(relative_path, timeout):
    reject absolute paths and different origins
    GET base_url + relative_path with Authorization header and validated TLS
    401 or 403: raise BridgeAccessError
    404: return None
    200: return bytes inside an async response context manager
    unexpected failure: raise typed media communication error
```

Tests: missing/invalid token; WebSocket header is present on first connect and reconnect; WSS/HTTPS schemes; 401 and 403 distinct from cloud login; no raw tokens in exception messages; no HTTP fallback, no insecure TLS bypass; relative media paths cannot redirect to another origin.

## Step 2 — secure configuration, migration and reauthentication

Files: `custom_components/eufy_sdk/config_flow.py`, `const.py`, `__init__.py`, `coordinator.py`, `translations/en.json`; add `tests/test_bridge_config_security.py`.

Pseudocode:

```text
manual_setup_form:
    collect hostname, TLS port, token through password-style selector
    do not use token as entity unique id, display title, URL or logger argument
    validate token form before any network request
    create_authenticated_client(host, port, token)
    distinguish access-denied from cannot-connect
    if connected: continue existing Eufy cloud 2FA/captcha sequence
    on success: persist token inside protected Home Assistant config entry

entry_start:
    if token absent (legacy entry): raise ConfigEntryAuthFailed with no secret
    create secure client with entry token
    do not call insecure WS client even temporarily

bridge_token_rotation:
    request a replacement token in reauth form
    authenticate against bridge with replacement
    update config entry token and reload only on success

eufy_cloud_reauthentication:
    retain stored bridge token
    continue existing 2FA/captcha flow
    never prompt for an access token unnecessarily

reconfiguration:
    preserve previously stored token unless user explicitly replaces it
    validate against new host/port before entry update
    do not emit old token in errors or form defaults

supervisor_discovery:
    never auto-import a bridge without authenticated TLS credentials
    abort discovery as unsupported in secure-only mode unless a safe credential
    provisioning flow is explicitly implemented
```

Migration: legacy entries contain host/port but no bridge token. They must fail closed and present a repair flow, not silently attempt plaintext or reset unrelated cloud authentication. Keep existing entry unique IDs and camera entities intact. Update English translation field labels and missing/invalid bridge token errors; no hard-coded appliance or host details.

## Step 3 — authenticated still-image and event-image access

Files: `custom_components/eufy_sdk/camera.py`, `image.py`, `snapshot_policy.py`, `api.py`; extend `tests/test_snapshot_policy.py`; add `tests/test_media_authorisation.py`.

Pseudocode:

```text
camera_image():
    policy = config_entry.runtime_data.snapshot_policy[entity_id]
    relative_path = make_snapshot_path(device_id, policy)
    return await config_entry.runtime_data.client.bridge_media_get(relative_path)

event_image_refresh():
    acquire existing per-camera serialisation lock
    data = await client.bridge_media_get(event_image_path, timeout=15)
    if data changed: update image and timestamp
    always release response and lock

on_media_unauthorised:
    raise bridge credential failure through existing HA recovery path
    never perform another unauthenticated retry
```

Keep the existing `SNAPSHOT_POLICY_DEFAULT/AUTO/STORED/LIVE` semantics. Prefer path builders or a single canonical URL builder over assembling HTTP URLs at each call site.

## Step 4 — gate unauthenticated live video

Files: `custom_components/eufy_sdk/camera.py`, tests `test_camera_battery_stream.py` and `test_snapshot_policy.py`.

Pseudocode:

```text
camera_feature_capabilities:
    do not advertise STREAM until secure media gateway is verified

stream_source():
    refuse direct RTSP URL generation from this development integration
    return no stream source for unsupported secure media transport

async_create_stream():
    return None while gateway remains unsupported
    preserve other camera functions and battery wake-up safeguards
```

Alternative RTSP-over-authenticated-overlay or TLS media gateway work is not bundled into this stage. It needs a separate tested design covering TLS/peer validation, downstream listener isolation, reconnections and battery impact. Never embed a persistent bearer credential in an RTSP or stream URL.

## Step 5 — CI, security verification and deployment boundary

Files: adjust existing `.github/workflows/lint.yml`, `test.yml`, `validate.yml` and release guard only where their trigger scopes require; create/extend unit tests identified above.

Acceptance commands in CI:
```sh
python3 -m pip install -r requirements_common.txt -r requirements_dev.txt
python3 -m pytest tests/ -q
python3 -m ruff check .
python3 -m ruff format . --check
python3 -m compileall -q custom_components/eufy_sdk
```

Required manual checks on an isolated test installation: tested certificate chain and hostname, unauthorized WS upgrade and JPEG requests fail without a token, no credentials in HA logs or diagnostics, Eufy 2FA reauth works, doorbell push arrives, event image and snapshot refresh without repeated battery wakes, token rotation prompts correctly, legacy entry migration, disconnect/reconnect recovery. Live video is explicitly unavailable until its gateway is verified.

Report commit SHA, changes by file, CI run links, tests, unresolved issues and rollback path. Neither companion repo is ready for production until cross-host encrypted media transport and end-to-end appliance tests pass.

## Quality and disclosure requirements

Use typed boundary helpers, standard `aiohttp` error classes, bounded connection retries, and consistent credential redaction. Never use `ssl=False`, query-string bearer secrets, unprotected RTSP, global requests session headers containing the bridge token, or blanket exception swallowing of access-denied conditions. Keep unrelated device functionality unchanged. Public documentation includes protocol roles and CPU architectures only, never hardware models, device identifiers or deployment addresses.
