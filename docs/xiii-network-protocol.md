# XIII PS2 network protocol: implementation map

Scope: the US disc, identified in [xiii-ps2-network.md](xiii-ps2-network.md), with its original ELF and `NET_M.OVL`. Addresses are EE virtual addresses; the network overlay is loaded at `0x01cee500`. Decompiler parameters are numbered starting at one. Some arguments passed on the MIPS stack are not reconstructed correctly by Ghidra, so an argument number is a trace aid, not a stable API definition.

**Evidence:** *Observed* means seen during the local PCSX2 session, *client* means established from the game code but not yet exercised end to end, and *candidate* means borrowed or inferred and requiring a XIII capture. This is a detailed implementation map, not a complete protocol specification. Host creation, second-client room listing, lobby join, and both clients' NAT discovery have been observed. After host-side member and player-info notifications were added, the user confirmed two-player combat in the same match on separate PCs. Match-end transitions, persistent statistics, and Internet traversal remain unverified or incomplete.

## What runs and what is shared

| Component | Role | Current state |
| --- | --- | --- |
| Bootstrap | Select profile by `dp` and advertise GS endpoints. | XIII consumed the local response. `routerlauncherport0` is actually used when hosting. |
| Router | Account creation, player authentication, handoff. | Account creation and login observed. Passwords are stored as salted scrypt hashes. |
| Wait module | Player info and entry point for lobby discovery. | Login, player-info request and parent-group discovery observed. |
| Lobby server | Room list, memberships and group events. | Second-client listing, joining, and combat have been observed. Room-close notifications and sustained lifecycle reliability need validation after the latest fixes. |
| Launcher / registration service | Select a parent group, register, update and remove a hosted room. | XIII requested parent groups, sent `0xd5`, and proceeded to host login after the experimental success response. A narrow score update is implemented experimentally; complete updates and explicit removal are not. |
| NAT helper | Report the external address and port seen from the game socket. | Both retail clients completed the control/token/address exchange after enabling UDP 30002 in bootstrap. Peer traversal remains unverified. |
| Game host | Simulation and Unreal networking on the player's PS2/emulator. | User confirmed two players sharing a match and interacting in combat on separate LAN PCs. |

The first five Ubisoft roles can share framing, codecs, account storage, session state, and group/room management. A product profile must supply identifiers, advertised endpoints, allowed versions, parent groups, and game-specific metadata; it must not make the shared service interpret XIII fields as if they were universal. A single process can host several roles, but their separate connections and state must still be represented. The experimental implementation currently multiplexes these roles on TCP 30000 and 30001 for convenience.

The GS protocol does not itself establish that a room is reachable. Preserve room ownership and the advertised endpoint, then test the PS2's direct game UDP path separately. Do not claim peer hole punching or relay support from the existence of the NAT helper.

## Observed connection and status sequence

| Step | Client request | Server behavior / confidence |
| --- | --- | --- |
| Bootstrap | HTTP `GET /gsinit.php?dp=XIIIPS2US` to `gsconnect.ubisoft.com:80`. | Local response consumed; three router keys are required, including launcher port. |
| Key exchange | GS `0xdb` subtype `1`, 260-byte public-key record; subtype `2`, RSA-encrypted cipher key. | Both directions accepted by XIII. The first encrypted account/login frame was decoded with the **client-generated** Blowfish key. |
| Create account | Encrypted `0x01`, seven strings. | XIII displayed account-created after success `0x26` with binary request ID `0x01`; the local store persists the account. |
| Router login | Encrypted `0x66`, three strings and one binary flag. | Local password verified; success payload `[binary 0x66]` led to `0x5d`. |
| Router handoff | `0x5d`, no data. | Success `0x26` payload `[binary 0x5d, [address string, four-byte little-endian port]]` led to a new connection. |
| Wait-module login | Key exchange, then `0x4d` containing the username. | `0x26`, `[binary 0x4d]` led to player info. |
| Player info | `0x13`, username string. | `0x26`, `[binary 0x13, [username, username, empty, empty, empty, empty, empty]]` led to discovery. The semantic meaning of all seven fields is not independently confirmed. |
| Discovery | `0xd1`, `["21", [product string]]`. | Sending `0xd1` `["38", ["21"]]` followed by a parent-group notification led to subtype `3`. `0x01d70fa0` is the sender called by XIII's server-list operation; `21` is read from global `0x00437334`. |
| Lobby handoff | `0xd1` subtype `3`, one group/server ID. | `0xd1` `["38", ["3", [id, address, port as decimal string]]]` caused a separate connection. The connection did **not** repeat key exchange. |
| Lobby-server login | `0xd2`, five strings. | `0x26` `["210", [server-id field]]` led to subtype `9`. The exact role of every request field remains open. |
| Group info | `0xd1` subtype `9`. | A group notification `["53", ["1", "256", parent-record, []]]` led to a screen where the user said refresh appeared to work. No hosted rooms were present. |
| Keepalive | `0x3a`, empty. | Client sent it on both established connections approximately every 31 seconds; the local service keeps the connections open without responding. |
| Hosting | Launcher TCP 30001, key exchange, encrypted `0x66` with three strings, then plain `0xd9` and `0xd5`. | A launcher login success needs `[binary 0x66, [string]]`. XIII accepted the candidate parent list and registration reply, then sent a host login over UDP. |
| Host UDP login | SYN, SYN-ACK, ACK, then `0xd2` in a padded reliable-datagram packet. | XIII acknowledged the experimental `0x26` reply and the user reported that the match loaded. This confirms the handshake and response for that session, not the complete transport or room lifecycle. |

`0x26` is success and `0x27` failure for these GS callbacks. Do not infer that all success messages have the same payload: the router, lobby, launcher and nested lobby operations visibly use different shapes. The general transport and crypto details, including length trailer and the limitations of the lab authentication, are in [crypto research](ubisoft-crypto-research.md) and [local test](local-test.md).

## Friends login and connection liveness

In the observed session, XIII sent `0x4e` on its existing wait connection after discovery. Overlay function `0x01d6ccf0` constructs that message with two four-byte binary values; the meanings of those values are not yet known. A separate [independent GS implementation](https://github.com/michal-kapala/ubi-gs/blob/master/gsm.py) names message 78 (`0x4e`) `LOGINFRIENDS` and responds with success and a one-byte message ID, matching the local candidate response. This is useful corroboration from another title, not confirmation that XIII accepts the response; it has not yet been exercised by XIII. The same implementation names message 58 (`0x3a`) `STILLALIVE`, consistent with the approximately 31-second messages observed on XIII's connections. Presence and actual friends-list operations have not been tested.

The original [XIII USA PS2 manual](https://www.videogamemanual.com/PS2/XIII%20%28USA%29.pdf) describes creating and browsing games, joining, filters, and passwords, but its online-play section does not describe a friends-list screen. An older [Ubisoft-published PC game manual](https://www.mogelpower.de/manuals/Rainbow_Six_Rogue_Spear_Black_Thorn_English_Manual.pdf) describes a Game Service friends list and a PC game-zone website; this establishes a historical Ubisoft feature but not that XIII PS2 exposed it or shared its exact service behavior. Some extracted XIII assets contain Xbox Live friends APIs and should not be mistaken for evidence of a PS2 friends interface.

## Launcher and registration

### Parent-group selection

`0x00380150` prepares registration, initializes the game network driver, and connects through the router's configured launcher port. If a caller did not provide a positive gameplay port and no configuration value exists, it uses `0x1e61` (7777). That is a default, not a guarantee that the socket is reachable from another network.

After launcher login, `0x01d64b30` sends type `0xd9`, with two GS strings: decimal subtype `12`, and the supplied product string. The value `12` is the 32-bit constant at main-image global `0x00437304`. `0x01d65750` handles the reply. For success it requires an outer field at index 1 that is a list of entries. For each entry it reads:

| Entry index | Decoder / required form | Status |
| --- | --- | --- |
| 0 | decimal string converted to integer | Client evidence; likely one group identifier. |
| 1 | decimal string converted to integer | Client evidence; likely another group/server identifier. |
| 2 | string copied into a 33-byte buffer | Group name. |
| 3 | decimal string converted to integer | Client evidence; usage/capacity meaning not proven. |
| 4 | optional decimal string; defaults to `1001` if missing | Client evidence; meaning not proven. |

The callback is invoked for each entry and once more with a zero/end marker. XIII proceeded to `0xd5` after the lab sent `[binary 0xd9, [["1", "1", "XIII", "0", "8"]]]`. The numeric fields' meanings remain only partially understood; a parent group is not itself a running game.

### Create / register request

`0x00380d50` continues the host path and calls the launcher wrapper `0x00383f80` → `0x01d64da0`. The latter selects a parent from its internal list if the supplied IDs are zero, builds a GS list and sends type `0xd5`. The sender reads main-image global `0x00437308`, whose value is also `12`.

The following wire shape follows the calls that append data. A live request confirmed the three outer fields and the 16 nested field types, but the contents and all meanings have not been independently checked. `S(n)` means a decimal number serialized as a GS string, not a binary integer. `B` is a GS binary field. The integer-to-string helpers `0x01d587d0` and `0x01d58810` both call the string appender using the `"%d"` format at `0x00437158`.

```text
type 0xd5, plain GS data:
  ["12", S(selected-parent-id-1),
    [ string-at-launcher-object+8,
      S(selected-parent-id-2), string(arg4), string(arg5),
      S(arg6 & 0xffff), S(arg7), S(arg8),
      B(arg10/arg11), B(arg14/arg15), string(arg9),
      string(arg17), string(arg18), S(flags),
      string-from-connection, S(arg16 & 0xffff), B(arg12/arg13) ]]
```

The order is explicit in `0x01d64da0`. The host call at `0x00380e38`–`0x00380ea8` supplies more detail that Ghidra's high-level call omitted: arg4 is the room name, arg5 is `XIIIPS2US`, arg6 is `6`, arg7 comes from an object field initialized to `16`, arg8 is the spectator-limit argument, and arg9 is the password string. The first binary field is built from the script's `Info`, followed by `?` and the requested player limit, then `:` and the selected game port. The middle binary field in the wire list is constructed from an empty string with length 1; the last binary field comes from `AdditionalInfo` and its length. Arg16 is the game port, args17–18 are `1.0` and `XIIIPS21.0`, and arg20 comes from the dedicated-server boolean. This mapping follows the PS2's argument registers and stack at the wrapper `0x00383f80`; verify pointer conversion, terminators and lengths against a real packet before treating it as a finalized serializer. The connection-derived string remains unidentified.

Flags start at `0x2010`, become `0x2810` for arg19, and OR `0x4000` for arg20. The XIII caller passes zero for arg19 and the dedicated-server flag for arg20. The visible `16` is a distinct SDK capacity field; the script-requested player limit is also embedded in the XIII-specific binary data, so a server must preserve both rather than silently merging them.

`0x01d64740` routes a `0xd5` result to `0x01d65580`. Its success form requires payload index 1 to be a nested list containing, in order: a string, a decimal string parsed as a 16-bit value, a decimal string parsed as a 32-bit value, and another string. Its failure form instead reads a four-byte binary error at index 0 of the nested list. The callback `0x00383120` passes the first two success values to `0x00384010` → `0x01d659c0`, which opens another service connection, then passes the third value and the current username to `0x00384070` → `0x01d65b20`, which sends `0xd2` with two strings. In the observed run this connection used **UDP**, unlike the earlier five-field player lobby login over TCP. The experimental service sent a GS success carrying `"210"` and two identifiers inside an SRP-like datagram; XIII acknowledged it and loaded the match. This confirms the tested response is sufficient for that transition, not the complete identity, room, or transport semantics.

### Host lifecycle in the embedded scripts

The disc's `XIIIMenuMultiGSRegisterServerMsgBox` calls `RegisterMyGameServer(name, maxPlayers, 0, "", info, "", -1, false)`, then polls `IsMyGameServerRegistered`. Only on success does it travel to the game URL. A dedicated-server script passes a real listening port and `true`, and retries after failure. In the game, `IStartMatch()` is used when the host joins its own room. While hosting, player names and integer scores are encoded as `name=score` entries separated by `?` and sent as additional information; a forced update is scheduled approximately every 29 seconds. The menu/game script calls `UnregisterMyGameServer` on teardown. These script observations identify lifecycle requirements but do not yet establish each underlying GS update/remove packet.

The SDK includes concrete follow-on senders, although their exact callers and reply behavior still need live confirmation:

| Sender | GS request | Client-side construction |
| --- | --- | --- |
| `0x01d65b20` | `0xd2` | Sends two strings: supplied identity and a decimal numeric argument, on the registration component's connection. This is a separate constructor from the observed five-string lobby login. |
| `0x01d65c70` | `0xd1`, subtype `31` | Starts a nested record with an ID and update mask. A `0x206` mask appends a numeric field; `0x08` and `0x10` append numeric fields; `0x20` appends a string; `0x40`, `0x400`, and `0x80` append binary fields; `0x100` appends a numeric field. Only fields selected by the mask are serialized. |
| `0x01d662c0` | `0xd1`, subtype `17` | Sends two decimal strings in a nested list. A comparison implementation labels this match start. |
| `0x01d664b0` | `0xd1`, subtype `45` | Sends one decimal string in a nested list. A comparison implementation labels this match finish. |

Subtypes `31`, `17`, and `45` are read from the main-image 32-bit constants at `0x0043730c`, `0x00437310`, and `0x00437314`. Treat the comparison names as leads: this establishes constructed messages, not that every path is exercised or that another title's response format is correct.

## XIII-specific room information

The console host builds its game-description string as:

```text
gameTypeIndex?mapIndex?fragLimit?timeLimit?privateFlag
```

The list UI splits `GameDesc` on `?`, uses the first two fields to select the game type and map labels, and treats `Y` in field 5 as private. The registration script passes this string as the `Info` argument, with an initially empty `AdditionalInfo`. This is XIII content; the common lobby layer should retain it as an opaque string and let the XIII profile validate and present it. The experimental [XIII profile](../src/ubisoft/games/xiii.py) implements exactly these five script fields and rejects ambiguous extra delimiters; the common service should retain the original raw string if a profile cannot decode it. Do not equate the string's private flag with a proven GS password policy.

For the registration/list bridge, the executable wraps that script string as `gameType?map?fragLimit?timeLimit?private?requestedMaxPlayers:port`. Its room callback at `0x00381a80` searches for `:`, removes the port suffix, then, when it finds exactly five `?` separators, reads the final suffix as a player-limit value and removes it before retaining the description. This supports the constructor analysis above from both the host and discovery sides. The function also creates or updates a `0x68`-byte local server record and stores the recovered port separately. `HostDescription` in the XIII profile implements the candidate text wrapper with stricter input validation than the game's permissive parser. Neither this text-level codec nor the static trace proves the encoding or length of the containing GS binary field until a live registration is captured.

Room records need, at minimum, a stable room ID and parent/lobby-server IDs, owner session, display name, game/profile ID, player limits and counts, game description, current additional info, reachable endpoint(s), and state/expiry. Registration, update, list, and delete should all operate on the same authoritative record. The precise wire fields and persistence policy are still open.

## Discovery, joining, and match traffic

The discovery operation `0x0037ea30` clears the prior list. `0x01d8cf80` starts discovery or refreshes cached parent groups. `0x01d8c8b0` is a `NewLobby` callback: it creates the cached parent-group container only when a parent is delivered, then requests group data if discovery is active. This explains why the first empty notification alone did not initialize a usable refresh state. The observed parent notification is a candidate record layout adapted from another GS implementation, not proof that all its flags and fields are correct for XIII.

On a selected record, `0x0037f750` constructs an `unreal://` URL from the record and sets up the game driver. `0x01d8d110` resets discovery, stores the requested IDs, password and product/version, then begins the join path. The sender `0x01d71280` builds nested lobby subtype `24` with five string/decimal fields; `0x01d714b0` uses subtype `8` for a leave-like operation, and `0x01d71820` requests subtype `9` group information. The join reply parser `0x01d72af0` reads the group ID from the inner nested result list, and leave parser `0x01d75c70` similarly reads an ID. The local service now sends candidate success envelopes `['38', ['24', [room-id]]]` and `['38', ['8', [room-id]]]` for active public rooms, with per-connection membership cleanup. Neither has been verified by XIII, and the code paths do not establish all required notifications, password behavior, or membership transitions. In particular, do not assume Heroes V's opaque room blob or event sequence applies to XIII.

The child-group parser `0x01d706c0` expects the 20 fields currently emitted by `Room.group_fields()` with matching string, decimal and binary types. Discovery callback `0x01d8c780` checks configuration bit `0x08` before forwarding a room. After the service added that bit to advertised registration flags, the second PC displayed the room. The host's `0x00380ff0` call selects the `0x400` binary update field for the script's `AdditionalInfo`; the UDP probe stores that field and sends candidate success replies for subtype `31`, and for match start/finish subtypes `17` and `45`. These replies do not implement arbitrary update masks or complete SRP reliability.

### Completing the server-details query

The disc script `XIIIMenuMultiGSGetServerInfoMsgBox` first requests additional information, then joins the lobby room. The observed second client sends subtype `46`, then subtype `24`, then subtype `42`. Parser `0x01d7c250` accepts additional-info success as `['38', ['46', [room-id, binary-additional-info]]]`. Parser `0x01d79660` delegates subtype `42` success to `0x01d6f840`, which accepts `['38', ['42']]`. The service replies to both and stores bounded player-info bytes. A subsequent live run still timed out on the details screen, so these acknowledgments alone do not complete the join.

The join-completion callback is reached by a separate subtype **56** notification:

```text
type 0xd1: ['56', [decimal-room-id, binary-game-data,
                    decimal-uint16-game-port, host-address, alternate-address]]
```

The trace is explicit: dispatcher `0x01d6a1a0` selects `0x01d7c790` for decimal 56; it calls parser `0x01d77a80`, then callback-interface virtual offset `0x80`. The main executable's interface table at `0x0041321c` resolves that slot to thunk `0x0037cbf0`, which adjusts the object pointer and enters `0x01d8cdf0`. That callback invokes virtual offset `0x16c` on the matchmaking object. Its table at `0x004131a8` resolves to thunk `0x0037ce80` and game callback `0x00382670`. This game callback stores both host addresses and the port, and sets the `0x80` completion bit at object offset `0x27c`. It does not use the opaque binary game data.

The experimental service now emits subtype 56 once after the joined client supplies its player info. It uses the registered game port and observed host PC address, an empty binary field, and an empty alternate address. A live guest advanced from querying into joining after this change, then reported lost connection. Room/member notifications, NAT traversal and successful peer gameplay remain unverified; this event does not establish that the guest can reach the host's UDP socket.

### Reliable UDP empty segments

Live hosts repeatedly sent 12-byte packets with flags `0x3040`, zero payload length and a non-sentinel sequence, while the old service sent no reply. The client transmitter at `0x01d5326c` queues such empty segments in its reliable-send window. Its ACK constructor `0x01d52140` sets zero payload length, flags `0x3044`, sequence `0xffff`, and the acknowledged peer sequence at byte offset 10. The service now uses that form for empty non-ACK segments, without consuming an outgoing GS data sequence or replacing the cached retransmission response. ACK-only packets receive no reply. Live host logs then advanced through new empty-segment sequences at roughly 30-second intervals instead of repeatedly sending the same sequence. Explicit FIN removes the host room; idle cleanup remains a fallback.

### Host-side peer opening

A fresh two-PC run completed NAT discovery for the host at `192.0.2.10:7777` and the guest at `192.0.2.20:64510`. The host registered and the guest completed lobby player-info setup, but PCSX2 on the host logged `UDP: Unexpected packet, dropping`. PCSX2 v2.8.2's [fixed-port receiver](https://github.com/PCSX2/pcsx2/blob/v2.8.2/pcsx2/DEV9/Sessions/UDP_Session/UDP_FixedPort.cpp) asks its child sessions to accept each source address; [unicast sessions](https://github.com/PCSX2/pcsx2/blob/v2.8.2/pcsx2/DEV9/Sessions/UDP_Session/UDP_Session.cpp) accept the remote IP they have previously sent to. Merely opening a host port through NAT discovery is insufficient for that backend.

The game's own peer-opening callback supplies the missing path. Host dispatcher `0x01d66750` accepts type `0xd1`, subtype 50 through `0x01d66be0`, which reads member fields at indices 0 (name), 1 (numeric flag), 3 and 4 (addresses), 5 (binary data), and 6 (numeric field). Virtual offset `0x28` in the host interface table at `0x00413430` reaches thunk `0x0037cf70` and game callback `0x00383400`. It creates the named member and a parallel peer-address entry. The parser does not read index 2; the lab fills it with the room ID and uses zero defaults for the unconfirmed numeric fields.

Subtype 66 reaches `0x01d672e0`, reading `[member-name, binary-player-info]`. Its virtual offset `0x44` resolves through `0x0037cf00` to `0x00383b00`. That callback finds the named member, consumes the first native u32 of player info as a UDP port, stores its low 16 bits, and calls `0x0037d060` to send the four bytes at `0x003ddad8`: `NAT\0`. Periodic function `0x0037d540` repeats peer-opening packets. Subtype 51 reaches `0x01d66e00`, virtual offset `0x30`, and `0x00383880`, removing the named member and peer entry.

The service now forwards subtype 50 followed by subtype 66 over the owning host's reliable UDP channel when a guest supplies player info. It preserves the opaque blob; the XIII profile validates its observed four-byte port shape. The two ordered GS frames share a bounded UDP payload and are retried with the same sequence until ACK or a retry limit. Subsequent player-info changes send subtype 66, and guest leave/disconnect sends subtype 51. Notifications do not replace the cached reply to a client request. The first deployment wrapped host sequences at ten; the live ACK audit below found that assumption was incorrect. Unit tests cover routing, ordering, port preservation, retries, and ACK cancellation. The subsequent run described below verified retail acceptance and combat.

The next live run acknowledged the member/player-info notification and the user confirmed two-player combat. During that session subtype 31 updates continued to be accepted. One remaining startup defect was identified: the host's self-join uses an empty player-info blob, and applying the guest port validator to that update closed the host's auxiliary TCP lobby connection. The staged correction exempts the room owner from guest peer-port validation and forwards no self-directed peer event; a regression test verifies the empty update is acknowledged and the lobby stays usable. It was not deployed during the active match. No persistent leaderboard or lifetime-stat store is implemented. The normal match-end and room-removal observations must be recorded separately from combat success.

### Audit during the first working match

| Flow | Evidence and current limitation |
| --- | --- |
| Live score/player-list information | Host subtype 31, mask 1024, continued during combat and is stored as room additional info in memory. It is not a persistent account-stat submission. |
| Match start/finish | Narrow subtype 17 and 45 handlers exist and have tests. This session did not establish a complete normal results-screen flow; the host self-join issue above can prevent its start acknowledgment. |
| Persistent results/rankings | No leaderboard or lifetime-stat database exists. No separate results submission was identified in this session. Presence of unused SDK stats functions does not establish that XIII requires them. |
| Member cleanup | Guest lobby closure generated host subtype 51, but that notification was not ACKed. The sequence defect below affects this observation; host room cleanup and user-visible results need a separate test. |

The host ACKed server data sequences 1 through 9, then stopped ACKing when the service incorrectly wrapped at 10. Native handshake function `0x01d52ee0` stores the advertised window at object offset `0x1ee`, doubles it into receive-ring size `0x236`, and initializes its advancing window using that ring. Thus the advertised ten-packet window requires a **20-slot sequence ring**. The staged fix uses modulo 20 in both host and NAT outgoing data sequences. A regression verifies progression through 9, 10, …, 19, 0; notification tests also cross 19 to zero. The active server was deliberately left untouched while the user completed the match; retail validation of these lifecycle corrections remains pending.

The user reported a normal round-end/ready prompt, then manually closed the hosted game; the guest returned to sign-in after a connection-failed message. Disc scripts confirm that this round-end prompt is expected: `XIIIMPGameInfo.MatchOver.Timer` transitions to `PendingMatch` after four seconds, marks players unready, and retains the host. `XIIIMPScoreBoard` displays the fire/ready prompt while waiting for the next round. A finished round therefore does not require deleting its hosted room.

`PlayerStats.Timer` sends current counters to the player controller through the game's replicated `STATS` message. The inspected `XIIIMPPlayerController.StatUpdate` path submits persistent stats only when an Xbox Live manager exists, initialized under the Xbox platform branch. This does not establish a missing Ubisoft stats endpoint for the observed PS2 flow. The GS room's additional-info score list remains distinct from persistent account statistics.

### Closing a hosted room while retaining sign-in

The service now observes authoritative room removal, sends joined TCP lobby clients `['55', [decimal-room-id]]`, clears their room membership, and retains the authenticated connection so they can refresh again. This applies to room removal triggered by host UDP FIN or the existing idle fallback, without inventing a new logout. Regression coverage verifies that a guest receives the removal event and then refreshes the empty parent lobby on the same signed-in connection; wrong-owner and duplicate removals produce no extra events.

The client path is `0x01d6a1a0` → `0x01d7bd10` → parser `0x01d73780`, which reads the nested room ID and removes the SDK's cached group through `0x01d7ef80`. Its notification callback uses interface offset `0x34` at table `0x0041321c`, resolving through `0x0037cd20` to the no-op `0x0037c340`. Consequently this is the supported group-removal event, but the trace does not establish that it changes the game's disconnect wording. The disc has a generic `ConnectionFailed=Connection failed with the server.` string; game UI text is not modified.

After the user closed the test match, the room-removal notification, empty owner player-info acceptance, and modulo-20 transport correction were deployed together. All 23 tests passed. A fresh host-exit test is still required to verify the retail guest stays signed in; the user-visible error text must be recorded separately from service-session retention.

The next host-exit test confirmed host UDP FIN, authoritative room removal, and a subtype 55 notification written to the joined guest's existing TCP connection. Roughly six seconds later the guest sent empty type `0x5c` and lobby subtype 8, and the user reported the generic connection-failed message followed by sign-in. Thus adding the room-removal event did not retain the retail UI's signed-in state. Type `0x5c` is constructed by client function `0x01d6cbd0`, reached through friends-disconnect wrapper `0x01d83c50`; it is part of the client's cleanup path. These observations are consistent with native host-loss cleanup but do not prove behavior against the original service. The lab still treats `0x5c` and the observed leave-group variant as unhandled and closes their connections, so that limitation must not be described as a fully verified graceful exit. No further UI or game changes were made; longer sequence-wrap tests and cleanup-message handling remain follow-up work.

Follow-up service correction: empty `0x5c` now disconnects only the optional friends channel logically, without a fabricated result or router logout. Subtype 8 accepts the connection's own room, its previously removed room, the local parent, or reset sentinel; it clears only that connection's membership and acknowledges the requested group. Repeated leave after room removal is idempotent, and an unrelated group does not close the authenticated connection. The existing 23-test suite was expanded to exercise friends disconnect followed by heartbeat and removed-room/reset leave followed by refresh, and passed before deployment. These server corrections are deployed; the retail UI outcome after them remains untested. The wording and return to sign-in therefore remain an observation with an unresolved original-service baseline, not a confirmed required behavior.

The cleanup retest verified the corrected server path. Host FIN removed the room and sent subtype 55 to both joined clients. Both clients then sent friends-disconnect and subtype 8 with reset group `0`, which the server accepted without dropping sign-in. Heartbeats continued afterward on the existing connections, and the guest successfully refreshed a parent-group list containing zero rooms. The user still described the visible screen as the login screen. Therefore that UI report does not indicate a server-enforced logout in this run; client navigation and original-service UI behavior remain separate questions. An additional-info request for the just-removed room was also observed and currently receives no result, a remaining stale-query edge case. No further service restart or game changes were made for this observation.

The game socket is UDP; the existing configuration supplies default port 7777. `0x0035ed80` creates and binds it, `0x0035ea60` sends, and `0x0035e520` receives and associates datagrams with peer addresses. The executable's connection code exposes the following Unreal control-message strings:

```text
HELLO REVISION=0 MINVER=%i VER=%i NET=%i MODE=%i
CHALLENGE VER=%i MODE=%i CHALLENGE=%i STATS=%i
NETSPEED %i
LOGIN RESPONSE=%i URL=%s
WELCOME LEVEL=%s LONE=%i [optional additional text]
JOIN
```

The sending/receiving code is at `0x00234740`, `0x002349b0`, `0x00213740`, and `0x00236e40`; it also handles version mismatch, upgrade, failure and challenge checks. These are game-control strings, not proof that the text appears as an unframed UDP payload or a complete ordering of every version and download branch. The packet/channel encoding and the host's acceptance checks still need a two-client capture and targeted tracing. GS room registration is not a substitute for hosting that UDP game.

## NAT observations

When both NAT bootstrap keys are available, `0x0037e500` can initialize the NAT helper. Host path `0x00383070` and join path `0x0037f750` call `0x01d8e0f0` with different contexts; `0x0037d0c0` bridges a NAT probe into the game driver's socket. A negative helper result can lead the host code into a fallback path. This explains an optional branch, not a guarantee that NAT can be omitted for Internet play.

`0x01d8f6a0` constructs GS type `0xdd`, subtype 1, with nested `[request-id, string, string, string]`. The request identifier is an 8-bit decimal string; the remaining strings' meanings are not yet confirmed. `0x01d8f3d0` dispatches subtype 2 to port-ID parser `0x01d8f560` and subtype 3 to address parser `0x01d8f600`. Both read nested decimal strings into 8-, 32-, and 16-bit values.

The port-ID callback `0x01d8ef90` retains the helper's configured server address and stores the response's 16-bit probe port. It converts the 32-bit value to a four-byte network-order token. Periodic function `0x01d8f040` sends that token through a callback that reaches the game's UDP sender `0x0035ea60`. Thus subtype 2 is `['2', [request-id, token-number, probe-port]]`; its 32-bit field is a token, not the destination IP. The server must observe the token arriving from the game socket before reporting its reachable port.

Address callback `0x01d8eff0` supplies `[u32-address, u16-port]` to main callback `0x00383c60`. The host path continues registration with the observed port; the guest path continues joining. Main function `0x00382670` compares that address with native `inet_aton` output. The conversion at `0x01d2a5b0` establishes the little-endian numeric representation of IPv4 bytes used in subtype 3: `['3', [request-id, native-address-number, observed-game-port]]`. The helper continues periodic probes after completion, so echoes also preserve the socket mapping.

The experimental [NAT responder](../src/ubisoft/nat.py) implements these payloads over the existing 12-byte SRP transport. It correlates opaque tokens with control sessions and requires the game probe to come from the same source IP. It echoes probes and retries the same address response until acknowledged. A synthetic live check verified the deployed bootstrap and a separate game socket's observed port; the retail game's acceptance, transport edge cases, and two-client gameplay remain to be tested. This is address discovery and mapping maintenance, not a gameplay relay or a complete Internet traversal service.

The first retail attempt with NAT enabled reached the control handshake and subtype 1 lookup but produced no correlated game probe, so creation stalled before room registration. Review of checksum routine `0x01d520a0` found that odd-length packets start with a signed `lb`, followed by unsigned halfwords and 32-bit folding. The shared checksum now reproduces that behavior, including nonzero seeds with the high bit set in their low byte; this correction has regression vectors but is not yet established as the cause of that live timeout. Bounded control-header diagnostics distinguish reply acknowledgment from request retransmission on the next attempt.

An open-beta client likewise completed account creation, sign-in, and the NAT control handshake, then sent its subtype 1 lookup without a subsequent logged reply acknowledgment or game-socket probe. It never sent room registration; a separate client completed these steps and hosted successfully. This identifies the stalled stage, not whether the reply was lost, rejected, or left unprocessed by the client. Duplicate room display names are allowed for separate owners and use distinct room IDs. NAT diagnostics now record reply subtype, length, sequence and acknowledgment, explicit port/address reply acknowledgments, and aggregate lookup milestones when a control session ends. Probe tokens and account fields are not logged.

## Remaining work before a complete testable service

1. Confirm remaining `0xd5` field meanings and failure codes using synthetic, redacted traces. The live request's field types and the host-login transition have been observed; do not commit credentials, session keys, or decrypted account messages.
2. Implement one shared authoritative room registry: create/ownership, listing and child notifications, update, unregister, cleanup on disconnect, and match-state transitions. Verify with two independently connected clients; an empty list alone is insufficient.
3. Decode the remaining XIII callback payloads for room creation, group info, join, leave and error responses. Tie the script's `Info` and `AdditionalInfo` strings to their actual GS fields. Cover split/coalesced frames and timeout/disconnect cases.
4. Test LAN host and join with the unmodified game. Record lobby message metadata and the first game-socket datagrams separately, then verify actual bidirectional game traffic and cleanup.
5. Implement and verify NAT discovery only from a captured XIII request/response; then repeat with clients on separate networks and document reachability. Do not represent an unverified address as usable.
6. Replace lab-only IP/username correlation with an explicitly modeled, authenticated session handoff after its original wire format is known. Handle duplicate accounts, invalid passwords, rate limits and persistent lifecycle intentionally before any shared deployment.
7. Add a second owned Ubisoft GS title and compare SDK versions, endpoint bootstrap, crypto and opaque metadata before claiming cross-title support.

The headless decompilation outputs for the focused targets are in ignored `work/research/`; they contain reconstructed client code and should not be published. [DumpInstructions.java](../ghidra/DumpInstructions.java) exported all instructions currently recognized by Ghidra in the analyzed images: 160,257 in the network overlay and 693,889 in the main executable, including their recognized function-entry markers. These listings do not include data or instructions Ghidra failed to identify, and they do not by themselves explain runtime behavior.

The [call-graph inventory script](../ghidra/FlowInventory.java) followed statically resolved calls two levels from the selected roots: the overlay inventory contains 122 functions, 489 resolved call sites and 14 indirect call sites; the main-image inventory contains 171 functions, 1,294 resolved call sites and 287 indirect call sites. Those counts describe this bounded search, not complete coverage. In particular, virtual calls, unresolved overlay-to-main calls, asynchronous callbacks and runtime-dependent branches require manual tracing or live evidence. The source files in `ghidra/` and this document provide reproducible targets without shipping disc contents. See [workflow notes](xiii-online-workflow.md) for command examples and broader context.
