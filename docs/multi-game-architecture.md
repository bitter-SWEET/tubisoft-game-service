# Shared services and game profiles

Tubisoft runs multiple titles in one process, with one account database and one
legacy GS key. A game profile supplies the title's wire dialect. XIII remains
the default enabled game; Ghost Recon 2 is an opt-in development profile, with
bootstrap and shared authentication plumbing but no implemented room flow.

| Layer | Shared implementation | Per-game responsibility |
| --- | --- | --- |
| Identity | `accounts.py`: SQLite, global case-folded username, scrypt, migration, backup; `admin.py`: account administration | None; games use the same username and password |
| Transport | `frame.py`, `data.py`, `gsxor.py`, `crypto.py`: GS framing, typed fields, legacy crypto | Confirm compatibility from the executable and live exchange |
| Bootstrap | `bootstrap.py`: bounded HTTP parsing, product dispatch, health | INI section/key spelling and advertised listener ports |
| Login/lobby | `router.py`: account operations, authentication handoffs, heartbeats, common GS envelopes | Parent records, registration parsing, supported operations, join endpoint and player-info codecs |
| Room lifecycle | `rooms.py`: pending/active state, membership, owner connection tracking, removal listeners | Registration metadata, advertisement flags; opaque game and score blobs |
| Reliable UDP | `srp_probe.py`: checksum/padding, sequence ring, ACKs, retries, host sessions | Host operation validation, member notifications and update interpretation |
| NAT | `nat.py`: correlated token/probe state, observed endpoints, bounded retries | Verify the title's request/callback dialect; no gameplay relay is implied |
| Runtime | `service.py`, `access.py`: startup, shared state path, global resource limits, private logs | `games/registry.py`: enabled profiles and per-title listener bindings |

`games/base.py` defines `GameProfile` and normalized `RoomSpec`. The implemented
XIII adapter is in `games/xiii.py`; `games/gr2.py` records GR2's verified identity
and bootstrap dialect. The catalog is immutable. Unknown and duplicate game
slugs, overlapping ports and invalid port numbers fail configuration validation.

## Accounts stay global; sessions stay with their game

All enabled router/launcher listeners receive the same
`/state/accounts.sqlite3` path. No account copy, per-title database, or schema
migration is needed. Existing accounts keep their password hashes. Creating a
name in one game reserves that name across all games; there is one credential
and one `last_login_at` value. The bootstrap's optional `user` query is neither
authentication nor a routing identity, and is not logged or forwarded by the PHP
bridge.

Each enabled profile has separate router/host, launcher, and NAT ports. Bootstrap
selects them by `dp` product, independent of IP address. This is necessary
because an initial account/login message does not reliably identify a title;
several titles use version `1.0`, and multiple clients may share an IP address.
The server therefore knows the profile from the listener that accepted the
connection, without requiring modified clients or host mappings.

Each game's router service owns its transient authentication/handoff maps, room
registry, UDP transport and NAT tokens. A GR2 handoff cannot be redeemed on the
XIII listener even with the same username and source address. The reusable room
registry also scopes registration, activation, browsing and lookup by product.
Registration must match the listener's profile. Game room names are not global
identities and can be repeated; room IDs are local to a game's runtime. The
same account can be used concurrently across titles. Within a title, the existing
handoff model still correlates by `(IP, account)` and is not a complete original
GS session-token implementation.

Rooms and handoffs intentionally remain in memory: a restart must not advertise
an old match whose host is gone. Future rankings or per-title preferences should
use separate tables keyed by `(account identity, product)`, without duplicating
credentials or putting game columns into password verification.

## Enabling games

Production defaults are unchanged:

| Profile | Product | Router TCP/host UDP | Launcher TCP | NAT UDP | Readiness |
| --- | --- | --- | --- | --- | --- |
| `xiii` | `XIIIPS2US` | 30000 | 30001 | 30002 | Existing open beta; client gameplay exercised |
| `gr2` | `GHOSTRECON2PS2` | 30010 | 30011 | 30012 | Development only; native bootstrap mapped, room operations unavailable |

For a local Python development instance, set `TUBISOFT_GAMES=xiii,gr2` plus the
usual advertised address and state directory. XIII retains the existing
`TUBISOFT_ROUTER_PORT`, `TUBISOFT_LAUNCHER_PORT`, and `TUBISOFT_NAT_PORT` variables.
GR2 accepts corresponding `TUBISOFT_GR2_*_PORT` overrides. The HTTP bootstrap
serves only enabled products. `TUBISOFT_HTTP_PORT` controls the Python listener
(default 8080); Docker's existing publish variables control its external mapping.

Compose development opt-in also publishes the additional ports:

```sh
docker compose -f compose.yaml -f deploy/compose.gr2.yaml --env-file .env config --quiet
docker compose -f compose.yaml -f deploy/compose.gr2.yaml --env-file .env up -d --build
curl --noproxy '*' 'http://127.0.0.1:18080/gsinit.php?dp=GHOSTRECON2PS2'
```

Use the same Compose project and state volume. This is an overlay on the existing
service, not a second container/database. The common DNS/HTTP routing remains
`gsconnect.ubisoft.com` on port 80. Keep using the existing platform DNS/DNAS.
The optional PHP bridge forwards product requests to the canonical Python
dispatcher rather than duplicating profile bodies.

GR2's `[Servers]` section and CamelCase keys differ from XIII's sectionless,
lower-case response. GR2's primary GS login constructor matches the common
shape; full retail crypto/login interoperability remains to be tested. Unsupported
GR2 lobby operations are closed with a metadata-only `UnsupportedOperation` log;
the server does not send XIII room records or fabricated success. A client may
show an error/timeout at that boundary. Enabling the profile does not establish
working GR2 multiplayer. See [the research evidence and missing messages](ghost-recon-2-network.md).

## Adding another title

1. Map its product/version, bootstrap parser, crypto, GS message constructors and
   callbacks from the owned disc. Keep extracted code, configuration, credentials
   and captures outside the publication boundary.
2. Add a profile module and catalog entry with distinct default listener ports.
   Reuse transport/account code when the protocol evidence supports it. Leave
   `supports_rooms=False` while the room contract is incomplete.
3. Implement registration to return `RoomSpec`, parent/launcher records, discovery
   flags, join endpoint, player-info port, host updates and membership events.
   Do not copy XIII's payload layout solely because the message number matches.
4. Add synthetic wire fixtures and cross-title isolation tests, then verify
   account/login, host, browser, join, NAT, multiple rounds and host departure
   with actual clients. Promote the profile's room capability only when the
   complete adapter is ready for testing, and document retail coverage separately.
5. Add an explicit Compose overlay/port mappings for development, then update
   deployment documentation when the title is ready for public use.

The integration suite starts both actual router services on loopback, performs
RSA/Blowfish key exchange, creates an account via XIII, logs into GR2 with that
same account, and checks that a GR2 handoff cannot be used on XIII. Existing
XIII wire, NAT, host-update, heartbeat, join and cleanup tests remain in place.
These checks establish server behavior, not GR2 retail acceptance.
