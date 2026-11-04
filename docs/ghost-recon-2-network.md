# Ghost Recon 2 USA: comparison with XIII

Ghost Recon 2 uses a closely related Ubisoft GS implementation. Several transport primitives are directly compatible with Tubisoft; bootstrap formatting, game identity, lobby integration, and gameplay metadata need a separate profile. Initial findings below come from static/offline investigation of `SLUS-21105`. Local retail tests have now verified bootstrap, key exchange, shared-account sign-in, NAT discovery, ranking startup with no stored records, the Lobby List screen, and entry into an empty parent lobby. A separate owned-disc dedicated worker now accepts a retail client through player setup/Ready. Multi-player gameplay and round transitions remain unverified.

Evidence labels used below:

- **Native execution:** original disc instructions executed against synthetic inputs.
- **Static:** traced instructions, decompilation, or configuration on this disc.
- **Pending:** an interpretation or complete flow that still needs additional tracing/capture.

The dedicated runtime assessment, isolated ISO/ELF launcher, asset adapter and
socket-backed native worker have moved to the separate **gr2-dedicated-server**
project folder. This repository retains shared GS and the
[worker-directory contract](gr2-workers.md). The native worker runs ST01 Assault;
retail discovery, endpoint handoff and player setup have been exercised.

## Executables and reproducibility

The disc boots `SLUS_211.05`, version 1.02. That small ELF is a loader. Its function `0x01400400` reads the selected `.SOZ` file into a staging area, reads a little-endian expanded-size word, expands the following zlib stream to `0x00100000`, and enters `0x00100008`. The multiplayer input is `MP.SOZ`; its expanded size is 5,472,512 bytes. Analyze that image for the linked GS code.

| Input | SHA-256 |
| --- | --- |
| `SLUS_211.05` | `e9e51b3e3b853a91883b6146e029a4bda82d5ba134768499f7ba4cc27d2543b9` |
| `MP.SOZ` | `06535bb03a47675fd50ca1a49c3f927182e6968ce7fa2b0301f052d611ed23c8` |
| Expanded `MP.SOZ` | `25b12620b7e2b162eec22d13a2ac639d5c6a77ca11fdc1444714031141f57c66` |

Use the dedicated Ghidra language `r5900:LE:32:default`. Generic MIPS64 misdecodes EE instructions such as stack `LQ`/`SQ` and creates misleading function boundaries. The multiplayer startup establishes GP `0x0063f770` and clears BSS from `0x00638100` to `0x00783000`; supplying those values improves global references in the raw-image import.

```sh
python tools/extract_gr2.py '/path/to/discs/Ghost Recon 2 (USA).iso'
```

Private analysis inputs and results are under `work/gr2`; the recognized-instruction listing is `work/research/gr2-ee-instructions.txt`. The archive index also allowed selective extraction of `PSX2GAME.INI` and related configuration without copying the entire game archive. Some shipped configuration contains saved-account fields. Raw configurations, values from those fields, game assets, and generated decompilation remain excluded from publication.

## Compatibility map

| Layer | GR2 evidence | Implication for Tubisoft |
| --- | --- | --- |
| Product identity | Setup `0x003dadb0` selects `GHOSTRECON2PS2`, `GR2PS21.0`, and `1.0`. | Select a GR2 profile and isolate room discovery by product/version. Some configuration contains inherited PC/Rainbow Six identifiers; use the actual setup path. |
| Bootstrap | HTTP on port 80 to `gsconnect.ubisoft.com`, with `user` and `dp` parameters. Sectioned INI parser. | Add a GR2 response renderer and product allowlist entry. |
| GS frame | Same six-byte header; native field/length readers matched 160 synthetic headers. | Reuse `frame.py`, subject to full message-flow verification. |
| GS data | String/list/binary helpers; numeric helper formats decimal strings. | Reuse the existing data model where message schemas match. |
| Payload transform | Same index-plus-`0x89` XOR and diagonal permutation structure. | Strong reuse candidate for `gsxor.py`; XOR stage verified by native execution. |
| Key exchange | Public/cipher-key handlers, type `0xdb`; initialization selects a 512-bit RSA key and a 16-byte cipher key. Blowfish implementation/table present. | Reuse candidate for `crypto.py`; complete encrypted-message interoperability remains untested. |
| Account/wait flow | `0x66` login, `0x5d` wait-address request, `0x4d` wait login, `0x13` player-info request. | Existing core handlers cover these message families; check response contents and identity handoffs against GR2. |
| Lobby | Five-field `0xd2` login and a 20-field group-record reader. | Shared GS schema is promising. GR2's create/register request, discovery filters, player data, and callbacks still need mapping. |
| TCP liveness | Empty `0x3a` heartbeats and the same independent receive clock; constructors use 180 seconds. | Retain the return heartbeat fix on each authenticated connection. |
| Reliable UDP | Twelve-byte framing, `0x3040` family, doubled receive-ring size, byte-identical checksum. | Reuse the transport principles, even-length finalization, and modulo-20 sequencing when advertising a ten-packet window. |
| NAT service | `0xdd`, request subtype 1, port-ID/address parsers with u8/u32/u16 fields. | Strong reuse candidate for `nat.py`; verify callback address conversion and real socket ports. |
| Gameplay | PS2-specific Unreal driver, configurable server/client ports, `SERVERPING` control-message handling; original PS2 multiplayer description specifies dedicated servers. | GS authentication/directory support does not implement the dedicated gameplay server. GR2 needs its own endpoint, room metadata and gameplay protocol. |
| Extra services | Real chat-login code and ranking-result callbacks, plus friends/ignore/message UI hooks. | Additional feature work beyond XIII's tested path. Their presence does not prove each is required for basic hosting. |

## Bootstrap: a concrete difference

Function `0x004c58e0` resolves the bootstrap host, connects to TCP 80, builds the request, and reads a response into a zeroed 1,460-byte allocation until receive returns no more data. The request is assembled as:

```http
GET /gsinit.php?user=<user>&dp=GHOSTRECON2PS2 HTTP/1.1
HOST: gsconnect.ubisoft.com

```

The actual line endings are CRLF. `0x003db420` passes the response into the GS INI reader, enumerates routers and NAT servers, and reads `RouterLauncherPortN` separately. `0x0051e670` looks up keys under the **Servers** section. The constructor/parser at `0x0051d330` tracks sections before inserting key/value pairs. A sectionless XIII response should not be treated as compatible with that lookup.

A candidate local response body is:

```ini
[Servers]
RouterIP0=192.0.2.10
RouterPort0=30000
RouterLauncherPort0=30001
NATServerIP0=192.0.2.10
NATServerPort0=30002
```

These are example deployment addresses/ports, not recovered original infrastructure. GR2's wrapper requires both a nonempty router list and a nonempty NAT list before returning success. It also enumerates `IRCIPN`/`IRCPortN`; the final success check in this function does not require an IRC entry. Advertise extra services only when their handlers exist.

The profile dispatcher now serves GR2's sectioned response when the development profile is enabled, using its own listener ports. The `user` query value must not substitute for authenticated identity. Avoid recording the complete request URI because it can contain an account name.

## Transport and crypto findings

The frame-length reader is `0x004fa4a0`. Accessors `0x004fa4d0` through `0x004fa510` recover property, priority, type, sender, and receiver from the same byte positions as XIII. Validator `0x004fa680` requires at least six bytes and accepts declared sizes through 3,000,000 bytes. This does not imply the server should raise its own bounded listener limit.

The data helpers distinguish binary and string fields. In particular, `0x0051a720` formats an integer using a decimal format and delegates to string insertion `0x0051a280`; numeric-looking lobby fields are not automatically native-width binary integers. Receive helper `0x0051b310` reverses this through decimal parsing.

`0x005096e0` reconstructs the diagonal grid and then calls XOR loop `0x005098e0`. That loop applies `byte ^ ((index + 0x89) & 255)`, matching Tubisoft. Public-key and cipher-key readers are `0x00500ba0` and `0x00500cc0`; send paths include `0x00500f50`/`0x00501150`. Initialization around `0x00501d28`–`0x00501d78` requests a 16-byte cipher key and sets RSA generation to 512 bits. The complete public-key blob, block-word order, padding, trailer, and response envelope should receive an end-to-end comparison before declaring the existing crypto implementation GR2-compatible.

The GR2 checksum at `0x00514bf0` is **byte-for-byte identical across all 152 bytes** to XIII's `0x01d520a0`. The odd-length branch reaches an unaligned `LHU` at `0x00514c44`. Tubisoft's existing external zero padding and checksum recalculation address the same mechanism. SYN processing at `0x00515a30` doubles the negotiated window for its sequence ring, just as XIII does.

Private offline execution used the owned disc code and synthetic data:

| Check | Result |
| --- | --- |
| Complete header length/field reads | 160 cases matched `GSHeader` |
| Even-finalized reliable-UDP checksums | 40 cases matched `finish_datagram` |
| Odd-length inputs | 10 expected alignment faults reproduced at `0x00514c44` |
| Index-XOR stage | 130 lengths matched the existing transform's XOR rule |

The frame-length reader's `memcpy` dependency was stubbed; the tested leaf routines were original instructions. No network or real account data was used. The diagonal permutation and full crypto handshake have static evidence but are not part of those execution counts.

## Account, lobby, and liveness

Login constructor `0x004ca300` emits `0x66` with three strings and a one-byte binary boolean. That has the same outer shape as XIII's primary sign-in. Wait-address constructor `0x004ca580` sends empty `0x5d`; `0x004ca470` sends `0x4d` with a string; `0x004ca680` sends `0x13` with a string.

Lobby login `0x004e21a0` builds `0xd2` using five fields, with boolean/port-like numbers passed through decimal-string formatting. Group reader `0x004d0ab0` consumes 20 fields, including the binary game-data slot, capacities/counts, version strings, and two final address strings. This is a useful shared-record boundary; it does not validate GR2's interpretation of game flags, room type, opaque description, or join notifications.

GR2's dedicated-server advertisement and client join paths still need tracing. Retained host/create methods and XIII's launcher `0xd5` layout do not establish that the retail PS2 client offers hosting. Do not enable GR2 rooms by merely changing the accepted product constant. Dedicated gameplay, registration, game-start/join and room player-info payloads remain implementation gates.

### Local shared-account and discovery follow-up

A retail GR2 client completed the RSA/cipher-key exchange and sent encrypted
primary login `0x66` with three strings and a binary field. The service verified
an existing local XIII account in the common SQLite database, returned success,
and answered `0x5d`. GR2 then opened a fresh connection, exchanged keys again,
and completed `0x4d` wait-module login. This establishes shared credential use
and encrypted GS interoperability for that run. The next `0xd1` message reached
the profile's deliberate unsupported-lobby boundary, explaining the client
remaining on “Logging in to Ubi.com.”

Discovery now has a capability separate from hosting/joining. Callback
`0x004d3bd0` selects operation 21 and delegates to `0x004cfcd0`; that parser
requires a `0xd1` envelope, outer decimal 38 for success, and nested operation
21. Parent-group notification parser `0x004d01b0` recognizes decimal 53.
The folder reader `0x004d0d90` consumes 14 fields, distinct from the 20-field
child-game reader `0x004d0ab0`. The GR2 adapter supplies its own product/name
in that folder and requires the discovery product `GHOSTRECON2PS2`.

The common handler returns the discovery success and parent notification, then
supports parent-address lookup, authenticated lobby login and empty-list
refresh. Real-socket synthetic tests cover the whole sequence and confirm
GR2 room joins still fail at the explicit unsupported boundary. A subsequent
retail run accepted discovery and proceeded to friends login `0x4e`, then sent
an empty `0x54` ignore-list request. The previously unhandled empty request
closed the connection, leaving the login screen waiting.

GR2 sender `0x004cece0` constructs empty `0x54`. Completion readers
`0x004cf740` and `0x004cc1a0` accept `0x26` with a single binary operation-ID
field, `[binary 0x54]`, without requiring list fields. With no stored ignore
entries, the shared handler returns that completion after friends login;
friends disconnect clears this connection's presence state without signing
out the account. This implements an empty ignore list, not friend management
or messaging. The native login state machine `0x004a9ef0` calls the ignore
request through `0x003d98c0` and then starts the player-info stage. Regression
coverage follows discovery, friends login, ignore completion, and continued
player-info/discovery requests, and rejects ignore requests before friends
login or after disconnect. The next retail run accepted that completion,
requested player info, and sent `0xde` with one string before the server
closed on that unhandled operation. That run also completed NAT port and
address discovery, including acknowledgement of both responses.

### Language-specific login text (`0xde`)

Sender `0x004caab0` sends `0xde` with one string. The login state machine
passes `en`, `de`, `fr`, `es`, or `it`, selected from the game's language.
Reader `0x004cbe40` verifies the standard success envelope with binary
operation ID `0xde`, then requires a nested list at field 1 and two strings
at nested fields 0 and 1, each bounded to a 513-byte buffer. A bare success
acknowledgement is insufficient. Game callback `0x003e32c0` marks completion
and copies these strings into two separate buffers. The GR2 adapter supplies
`["", ""]` because no service notices are configured, yielding
`0x26 [binary 0xde, ["", ""]]`. The language request is only accepted after
authenticated wait-module login; XIII retains its unsupported boundary.

The adjacent player-info parser `0x004cb080` reads seven strings, matching
the existing response's outer structure. The next retail run accepted the
two-text reply, completed NAT discovery, and requested `ladderquery` using
`0xcc`. The missing proxy directory handler then closed the router socket.

### Ranking proxy startup (`0xcc`)

GR2 initializes ranking queries as part of sign-in. Shared proxy mechanics
live in `ubisoft.proxy`; GR2 selects its service name and empty table schema.
The existing per-title router port also accepts the proxy connections, keeping
accounts shared and service state isolated between enabled games.

| Step | Native evidence | Implemented response |
| --- | --- | --- |
| Lookup | `0x004ef7b0` sends `0xcc ["1", ["ladderquery", "0", "0"]]`; `0x004eb1f0` reads the service/version/instance and server list. | `0xcc ["38", ["1", ["ladderquery", "0", "0", [[server-id, host, port]]]]]`. |
| Select | `0x004e7f90` sends operation 2; `0x004ec280` reads the selected ID and starts the proxy socket. | `0xcc ["38", ["2", [server-id]]]`. |
| Authenticate | `0x0050ca30` sends plain `0x66` with username and SDK version, route 8 to 11. | Consume a short-lived, single-use authorization for that exact peer/account/version, issued by the already authenticated router's service selection; `0x26 [binary 0x66, []]`. |
| Redirect | `0x0050ce40` sends empty `0x5d`; `0x0050cff0` reads ticket, address and decimal port, closes and reconnects. | `0x26 [binary 0x5d, [ticket, host, port]]`. Tickets fit its 16-byte buffer, expire, bind to the peer, and redeem once. |
| Redeem | `0x0050cff0` sends `0x4d` with the ticket; `0x0050d290` marks the transport ready. | `0x26 [binary 0x4d, []]`; a normal account handoff cannot redeem a proxy ticket. |
| Report completion | `0x004ecf10` sends `0xcc [["3", server-id]]` on success or nested operation 4 on failure. | Consume without another acknowledgement. This single-list shape differs from lookup and selection. |
| Query | `0x0050c6d0` sends `0xcc ["1281", transport-request-id, application-query]`. `0x004efe90` constructs the application query. | `0xcc ["1281", transport-request-id, ["38", empty-table]]`. |

The application query has operation 1 and a nested application ID, product,
version, ladder, row selection and column/sort/filter lists. GR2's adapter
accepts its own product and ladders 0–4. `0x004c6a70` reconstructs the SDK
result and appends the **transport** request ID; this must not be replaced by
the application's separate ID. `0x004f09a0` correlates that result and passes
the table to `0x004f4fd0`.

The empty table is `["1", [application-query-id, "0", [], []]]`: table type 1,
the original application's query ID, zero total rows, no column definitions
and no rows. Constructor `0x004f4980` stores its first integer at offset 8;
accessor `0x004f4de0` returns that integer as the callback's query ID. Using
zero there caused all ten retail queries to complete under ID zero, leaving
the game's actual requests pending. This field must also remain distinct
from the outer transport request ID. The game callback `0x004067e0` completes
the query and converts missing player rows into its local `-10` status.
Login state machine `0x004a9ef0` allows that status for the rough-rank queries;
the top-list reader `0x00406220` accepts an empty iteration. This follows the
game's unranked-player path without inventing scores. Persistent rankings,
stat submission and gameplay remain unimplemented.

Offline execution of the original `0x004f4de0` accessor matched 11 synthetic
IDs, including zero and the largest 32-bit value, read from table offset 8.
That leaf check confirms the ID accessor. The next retail run completed
the ten callbacks: rough rank used the native `-10` unranked status, the
empty top list completed successfully, and the user reached the lobby menu.

Real-socket regression coverage follows the retail startup sequence through
proxy lookup, selection, account authorization, redirect, reconnect, ten
queries and subsequent directory traffic. It rejects unselected accounts,
wrong versions, reused login grants, cross-title tickets and ticket reuse;
separate checks cover peer binding, expiry, capacity and malformed queries.
The retail client accepted the proxy and ranking replies and subsequently
requested a separate lobby-server connection.

The first fresh-boot retail attempt accepted lookup and selection and opened
the proxy socket, but the initial server handler incorrectly interpreted its
second string as a password. Native `0x004c8740` stores the primary username
at SDK offset 4, password at `0x14`, and version at `0x25`. Proxy setup
`0x004c99f0` passes offsets 4 and `0x25` to `0x004eb140`, so the wire fields
are **username/version**. Live inspection of that non-secret version member
confirmed the configured SDK version. Tests and implementation now use these
native semantics; the earlier password-based smoke check did not establish
retail proxy compatibility. SQLite credentials are verified on primary login;
proxy authorization is then bound to that verified router session's selected
account, peer and title version, rather than accepting an arbitrary name or
borrowing another account at the same source address.

A later retry did not reach the new proxy handler: the client retained proxy
state 2 (lookup pending) after a previous server disconnect. Read-only live
inspection found that state and a nonzero query counter; the emulator log
showed no intervening game boot. `0x004efe90` queues queries while in state 2
and calls lookup sender `0x004ef7b0` only from state 1. Returning to the login
menu therefore did not exercise the newly implemented service. During local
development, fully stop the game and boot it again after an interrupted
lookup, then verify the fresh lookup in server logs. This observation does
not justify modifying the game or its emulator network settings.

### Entering the parent lobby (`23`)

The **Lobby List** screen's `Ghost Recon 2` entry is the service's parent
lobby. It is a directory container for game rooms and remains present
when there are no advertised games. Selecting that entry is not a gameplay
join: the retail client obtained its lobby address with operation 3,
completed five-field `0xd2` lobby login, then sent `0xd1 ["23", [group-id,
password, numeric-option]]`. The previously unsupported operation 23 closed
the directory connection and sent the user back to sign-in.

Sender `0x004d1610` builds those three fields. Completion reader
`0x004d4430` checks the standard lobby success envelope and reads the group
ID from nested field 0, with optional text at field 1. Callback
`0x004dd0a0` dispatches that result separately from game-room operation 24.
The GR2 adapter now validates its public parent group and returns
`["38", ["23", ["1", ""]]]`, followed by the parent's group-info notification
and its actual child-room list. The shared handler requires an authenticated
lobby-server connection. Hosting/joining game rooms remains disabled while
that title-specific implementation is incomplete. Real-socket tests enter
and refresh the empty parent, preserve heartbeats, reject a parent join on
the router-only connection, and retain the unsupported game-room boundary.
The next retail attempt accepted the parent-join reply and immediately
published its player record with operation 42. That uncovered a separate
capability error: the server only accepted player data after joining a game
room, so it rejected the parent-lobby update and disconnected the client.

Game callback `0x003e1430` marks the parent join complete and calls
`0x003dd930`, which publishes exactly 28 bytes from its GS player record and
marks completion at offset `0x184` pending. The GR2 profile validates that
fixed record size. The shared handler retains the opaque record for the
current parent membership and replies `["38", ["42"]]`. Reader
`0x004db070` uses the common operation-success parser; game callback
`0x003dd8b0` marks that publication complete on success without emitting a
further request. Parent data does not enter the game-room endpoint code.
Leaving the parent clears its state, and updates require an active parent
membership. Synthetic socket coverage now includes join, publication,
repeated publication, refresh and heartbeat; state checks reject anonymous,
pre-join, wrong-size and post-leave updates. The next retail test entered
the parent lobby and displayed no available games, as expected with no
registered rooms. The server accepted join and player publication at
20:45:34 UTC on 2026-11-03, then answered heartbeats on both wait and lobby
connections. Read-only inspection confirmed both parent join (`0x11c`)
and player publication (`0x184`) had success status 6 with zero errors;
the ranking proxy had no pending queries. The server logged the join and
publication replies within the same millisecond as their respective
requests; the user's perceived entry delay is not yet attributed.

The TCP receive pump `0x0050dfb0` updates socket offset `0x70` only when data arrives and compares it with timeout offset `0x74`. Timeout sets error `0x97`. Constructors including `0x004f3110` and `0x0050c300` pass `0xb4` (180 seconds). Send pump `0x004ff7a0` independently constructs empty `0x3a` messages. The same liveness separation that caused XIII's three-minute disconnect therefore exists in GR2; outgoing client traffic does not satisfy its receive deadline.

## Retail lobby menu and dedicated gameplay

The retail lobby screen shows **Join Game**, **Search Game**, and **Player
List**, with **No Game Available** in the empty list. A Create option is
absent. This is consistent with Ubisoft's original PS2 multiplayer
technology description, which explicitly describes a dedicated-server
solution for gameplay and separately describes peer distribution for voice.
See [Ubisoft's 2004 multiplayer details, reproduced by WorthPlaying](https://worthplaying.com/article/2004/10/27/news/20183-ghost-recon-2-ps2xbox-multiplayer-details-trailer/).

Native menu setup `0x00323550` selects `P_lobby` and `P_lobby_matchlist`;
its parent-page path does not construct a Create action or branch on a GS
permission to reveal one. The executable also retains `B_creatserver`
handlers and separate create panels (for example `0x0049b090` and
`0x004a0e70`). Those retained paths alone do not prove that hosting is
reachable in the shipped PS2 UI. The screenshot and the original technology
description invalidate the earlier assumption that users should create
peer-hosted matches here. No client patch or speculative directory flag
change was made.

The next implementation boundary is a real dedicated gameplay endpoint,
its directory advertisement and the client's join handshake. An invented
room record without a compatible game server would only move failure to
joining. The current shared account, ranking startup and parent lobby are
working prerequisites; they do not simulate a GR2 match. Whether the
retained server code can provide a practical server runtime requires
separate investigation.

## NAT and gameplay

NAT request builder `0x0051ff90` sends `0xdd` with subtype 1 and a nested request ID plus three product/version strings. Port-ID parser `0x0051fe50` and address parser `0x0051fef0` read u8 request ID, u32 value, and u16 port from decimal fields. Callbacks `0x0051f8c0` and `0x0051f920` feed the subsequent probe/address path.

The game-facing completion callback `0x00471620` stores the returned address and port and signals its waiting request. It has an address-conversion branch controlled by whether the bootstrap NAT hostname matched the legacy NAT hostname. An IP-based local bootstrap takes the direct-storage branch; capture/compare the actual game callback before changing endianness globally.

`PSX2GAME.INI` selects `PSX2NetDrv.PSX2NetDriver` and defines `ServerGamePort=3658`, `ClientGamePort=1000`. Configuration loader `0x0023da10` reads both; URL constructors `0x0023cd20`/`0x0023d7c0` carry them as separate fields. URL overrides and NAT can change the reachable endpoint, so the observed game socket remains authoritative. The inherited `DEFAULT.INI` port 7777 is not sufficient evidence for this PS2 path.

Control handler `0x001f8960` has `SERVERPING` and `SERVERPINGANSWER` branches; a server-ping branch sets up its answer through the existing connection interface. Those are engine control messages, not proof of an unframed ASCII UDP protocol. Keep directory liveness, the NAT mapping, the browser query, and the actual Unreal connection as distinct concerns. No evidence in this investigation establishes a Ubisoft gameplay relay.

Chat is an active integration path: `0x003e7ee0` iterates the bootstrap's IRC endpoints and attempts a chat login. Ranking callback `0x004067e0` dispatches rough-rank, dynamic-level, detailed-player, top-list, and filtered-ladder results. Friends, ignore, and messaging have menu/hooks beyond the generic SDK string table. Their request/response schemas and mandatory/optional behavior still need tracing.

## How to extend Tubisoft

1. Add an explicit product/profile registry. Keep account storage, GS frame/data/crypto codecs, bounded reliable transport, and NAT discovery shared. Select profiles using verified product fields, and enforce game/version isolation when listing or joining rooms.
2. Give each profile a bootstrap renderer. Preserve XIII's existing format while GR2 receives the sectioned response and its own identifiers. Keep bootstrap account names out of logs.
3. Trace GR2's dedicated gameplay endpoint, directory advertisement, join, player-info and room-update paths. Assess whether the retained server code offers a practical runtime. Add its room-data/endpoint codec under `ubisoft.games`; retain common group records where schemas agree. Keep per-game ports and masks out of shared handlers.
4. Retain credential-based launcher identity and bidirectional TCP heartbeats. Handoffs still need an explicit session model; source-IP correlation alone must not become a cross-title account identity.
5. Exercise bootstrap/account sign-in against an isolated local instance, then dedicated-server discovery, two-client joining, round transition, and server departure. Compare captures with the native readers before widening support. Friends/chat/rankings should have separately tracked coverage and game-scoped persistent data where required.

The service now separates title adapters from common accounts and transport. GR2 directory discovery has its own capability and parent record, while dedicated gameplay and room joining remain unavailable. A working GR2 match still needs a compatible gameplay server and retail validation.
