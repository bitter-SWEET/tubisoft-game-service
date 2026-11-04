# Ghost Recon 2 worker integration

Tubisoft handles accounts and Ubisoft GS. The separate **gr2-dedicated-server**
project handles the original PS2 gameplay engine, PCSX2 and private owned-disc
assets. No ISO, BIOS, generated ELF, asset cache or memory card is needed by
this service, and none belongs in its repository or Docker image.

An unmodified retail USA client has signed in, found the dedicated Assault
room, joined and reached player setup/Ready. Multi-player movement, combat,
results and repeated rounds remain acceptance tests. The retained team modes
require further start-rule validation; online bots have not been established.

## Enable GR2 and a worker

Use the existing project and SQLite volume with both overlays:

```sh
export TUBISOFT_GR2_WORKER_DIR=/path/to/private/worker-health
docker compose --env-file .env -f compose.yaml -f deploy/compose.gr2.yaml \
  -f deploy/compose.gr2-worker.yaml config --quiet
docker compose --env-file .env -f compose.yaml -f deploy/compose.gr2.yaml \
  -f deploy/compose.gr2-worker.yaml up -d --build
```

Expose TCP/UDP 30010, TCP 30011 and UDP 30012 for GS. Gameplay has a separate
UDP endpoint owned by the worker or its operator-managed relay. DNS still maps
`gsconnect.ubisoft.com` to the GS service; the bootstrap uses its advertised
address. Keep existing platform DNS/DNAS routing.

Mount only the health directory, read-only. UID 10001 must be able to traverse
that directory and read `current.json`. Do not mount the worker's private assets
or the directory containing service credentials. Only a trusted operator may
write this file: it controls the endpoint given to players.

## Worker state contract

`TUBISOFT_GR2_WORKER_STATE` selects the file. Without it, GR2 rooms stay disabled.
The producer atomically replaces a UTF-8 JSON document, at most 4096 bytes:

```json
{
  "schema": "tubisoft-gr2-worker-v1",
  "run_id": "0123456789abcdef0123456789abcdef",
  "updated": 1234567890.0,
  "ready": true,
  "map": "st01_map",
  "mode": "assault",
  "address": "192.0.2.10",
  "port": 3659,
  "capacity": 16,
  "players": 0,
  "description": "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
}
```

The producer must set `ready` only after validating the native map, server-only
role, bound driver socket, advancing world tick and native player counts.
`updated` is Unix wall-clock seconds; replace the example with current time.
The service checks every second and removes a record older than five seconds,
with `ready: false`, or with malformed fields. A new 32-character hexadecimal
`run_id` replaces the previous room and notifies its members. Counts come from
the native GameInfo; the worker is not counted as a phantom player.

The 84-byte description is hexadecimal. The service clears password bytes and
fills known ST01/Assault fields and the advertised IPv4 endpoint. In this build,
field `0x48` must be zero for dedicated discovery; nonzero selects peer-owner
membership checks. This is separate from gameplay's `DEDICATED=1` role.

For a worker on another machine, the companion project's SSH bridge forwards
bounded gameplay datagrams and validated health. Its remote process stamps
health on receipt and advertises the relay's actual public endpoint. SSH host
verification and keys remain operator-managed. A broken bridge expires the
listing. The experimental TCP-backed tunnel can introduce head-of-line delay;
remote retail play and latency still require testing. Do not expose a LAN-only
endpoint or serve an unchanged snapshot as a live heartbeat.

## Join and lifetime

GR2 child-join success carries room ID plus an empty success-text field.
After player information, GS event 56 carries room ID, data, UDP port and public
and local addresses. The client then sends one-way operation 34 with its room
ID. Tubisoft validates this report and retains the GS connection without a
fabricated completion event. Worker expiry sends room removal while keeping
account sign-in alive. Shared socket tests cover listing, join, endpoint,
post-join heartbeat, worker restart and expiry.

At the observed round boundary, GR2 sends one-way operation 70 with its joined
room ID. The native call chain is `0x003de860` → `0x004c61e0` → `0x004d23a0`;
the SDK dispatcher at `0x004c8e70` has no operation-70 completion. Tubisoft
validates the report against this connection's dedicated GR2 room and retains
the GS session and room membership. Operation 8 remains the explicit leave.
Previously operation 70 fell through the unsupported-message path, closing
every reporting client's GS connection even though the gameplay worker stayed
alive. Socket regression tests cover simultaneous members, repeated reports,
heartbeat continuity and leave/rejoin. Retail continuation into a second round
still needs verification; this does not resolve native simulation performance.

Ranks currently return empty tables using the requested query IDs. Friends,
complete ranking writes, all GS operations and normal retail game teardown
remain incomplete. This integration is an experimental beta, with gameplay
acceptance recorded separately from service tests.
