# Ghost Recon 2 USA: comparison with XIII

Ghost Recon 2 uses a closely related Ubisoft GS implementation. Several transport primitives are directly compatible with Tubisoft; bootstrap formatting, game identity, lobby integration, and gameplay metadata need a separate profile. This is a static/offline investigation of `SLUS-21105`, not a successful GR2 connection to the service. The deployed XIII service was unchanged during this investigation.

Evidence labels used below:

- **Native execution:** original disc instructions executed against synthetic inputs.
- **Static:** traced instructions, decompilation, or configuration on this disc.
- **Pending:** an interpretation or complete flow that still needs additional tracing/capture.

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
| Gameplay | PS2-specific Unreal driver, configurable server/client ports, `SERVERPING` control-message handling. | Player-hosted game traffic remains separate from Ubisoft service traffic. GR2 needs its own endpoint and metadata handling. |
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

The current bootstrap rejects a `dp` other than `XIIIPS2US`. Both that dispatch and the per-game response format need changing before a GR2 client can use it. The `user` query value must not substitute for authenticated identity. Avoid recording the complete request URI because it can contain an account name.

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

GR2's registration must still be traced from the game-facing host/create method through the selected SDK sender and completion callback. XIII's launcher `0xd5`/registration layout is currently enforced in `rooms.py`; do not enable GR2 by merely changing the accepted product constant. The exact GR2 parent discovery, registration, game-start/join and player-info payloads remain implementation gates.

The TCP receive pump `0x0050dfb0` updates socket offset `0x70` only when data arrives and compares it with timeout offset `0x74`. Timeout sets error `0x97`. Constructors including `0x004f3110` and `0x0050c300` pass `0xb4` (180 seconds). Send pump `0x004ff7a0` independently constructs empty `0x3a` messages. The same liveness separation that caused XIII's three-minute disconnect therefore exists in GR2; outgoing client traffic does not satisfy its receive deadline.

## NAT and peer gameplay

NAT request builder `0x0051ff90` sends `0xdd` with subtype 1 and a nested request ID plus three product/version strings. Port-ID parser `0x0051fe50` and address parser `0x0051fef0` read u8 request ID, u32 value, and u16 port from decimal fields. Callbacks `0x0051f8c0` and `0x0051f920` feed the subsequent probe/address path.

The game-facing completion callback `0x00471620` stores the returned address and port and signals its waiting request. It has an address-conversion branch controlled by whether the bootstrap NAT hostname matched the legacy NAT hostname. An IP-based local bootstrap takes the direct-storage branch; capture/compare the actual game callback before changing endianness globally.

`PSX2GAME.INI` selects `PSX2NetDrv.PSX2NetDriver` and defines `ServerGamePort=3658`, `ClientGamePort=1000`. Configuration loader `0x0023da10` reads both; URL constructors `0x0023cd20`/`0x0023d7c0` carry them as separate fields. URL overrides and NAT can change the reachable endpoint, so the observed game socket remains authoritative. The inherited `DEFAULT.INI` port 7777 is not sufficient evidence for this PS2 path.

Control handler `0x001f8960` has `SERVERPING` and `SERVERPINGANSWER` branches; a server-ping branch sets up its answer through the existing connection interface. Those are engine control messages, not proof of an unframed ASCII UDP protocol. Keep directory liveness, the NAT mapping, the browser query, and the actual Unreal connection as distinct concerns. No evidence in this investigation establishes a Ubisoft gameplay relay.

Chat is an active integration path: `0x003e7ee0` iterates the bootstrap's IRC endpoints and attempts a chat login. Ranking callback `0x004067e0` dispatches rough-rank, dynamic-level, detailed-player, top-list, and filtered-ladder results. Friends, ignore, and messaging have menu/hooks beyond the generic SDK string table. Their request/response schemas and mandatory/optional behavior still need tracing.

## How to extend Tubisoft

1. Add an explicit product/profile registry. Keep account storage, GS frame/data/crypto codecs, bounded reliable transport, and NAT discovery shared. Select profiles using verified product fields, and enforce game/version isolation when listing or joining rooms.
2. Give each profile a bootstrap renderer. Preserve XIII's existing format while GR2 receives the sectioned response and its own identifiers. Keep bootstrap account names out of logs.
3. Map GR2's host/create, discover, join, player-info, and room-update callbacks. Add its opaque room-data/endpoint codec under `ubisoft.games`; retain the common group record where the traced schemas agree. Keep per-game ports and masks out of shared handlers.
4. Retain credential-based launcher identity and bidirectional TCP heartbeats. Handoffs still need an explicit session model; source-IP correlation alone must not become a cross-title account identity.
5. Exercise bootstrap/account sign-in against an isolated local instance, then host/discovery, two-client joining, round transition, and room removal. Compare captures with the native readers before widening support. Friends/chat/rankings should have separately tracked coverage and game-scoped persistent data where required.

The current service has concrete XIII-specific gates in `bootstrap.py`, `rooms.py`, and `router.py`, in addition to the title codecs already in `games/xiii.py`. Those boundaries are the initial refactor targets. This investigation supports reusing much of the GS foundation; a working GR2 lobby and peer match still need their own implementation and retail validation.
