# Rainbow Six 3 USA (PS2): GS compatibility notes

Tom Clancy's Rainbow Six 3 for PS2 (`SLUS-20883`) links the same Ubisoft GS SDK
family as Ghost Recon 2. Its sign-in sequence, bootstrap dialect, ranking proxy
and lobby records match GR2 closely. Its game-hosting path instead resembles
XIII's launcher registration. Everything below is **static** evidence from the
owned disc's executables. No retail client has been run against Tubisoft yet.

Evidence labels follow [the GR2 notes](ghost-recon-2-network.md):
**Static** (traced instructions/data on this disc), **Capture** (a related
title's client traffic, used only for comparison) and **Pending**.

## Executables and reproducibility

`SLUS_208.83` is a 143 KB loader linked at `0x01400000`. Like GR2's loader, it
expands a `.SOZ` file: a little-endian expanded-size word followed by one zlib
stream. `MP.SOZ` expands to 5,593,216 bytes. Pointer voting against string
offsets gives a load address of `0x00100000`. Startup at `0x00100198`
clears BSS from `0x00655880` to `0x007c9800` and sets GP to `0x0065cf70`.
Use those values with Ghidra's `r5900:LE:32:default` language.

| Input | SHA-256 |
| --- | --- |
| `SLUS_208.83` | `85847d677495cb971c9673e1c0f8b7c7093dfd2eb38a5750f252e647c550628b` |
| `MP.SOZ` | `731aec681af456bc77393c03bf5d9d441d12a304ca17f29fc4785ca3226aea27` |
| Expanded `MP.SOZ` | `0f86683517934e17af5a0cfc642d2f7946a924a24b5714052a1c79f0ecab285b` |

```python
import struct, zlib
raw = open("MP.SOZ", "rb").read()
image = zlib.decompress(raw[4:])
assert len(image) == struct.unpack("<I", raw[:4])[0]
```

The image is unsymbolized. The debug name table at `0x00440670` maps
message types to SDK names. Its types match the existing XIII/GR2
numbering (`0x26` GSSUCCESS, `0x3a` STILLALIVE, `0x4d` LOGINWAITMODULE,
`0x5d` JOINWAITMODULE, `0xd1` LOBBY_MSG, `0xd2` LOBBYSERVERLOGIN).
Keep extracted images, captures and listings outside the repository.

## Identity and bootstrap

| Item | Evidence | Value |
| --- | --- | --- |
| Product (`dp`) | Setup `0x003ff3d0` → setter `0x003ffde0`; getter `0x003ffe60` is appended after `&dp=` by `0x00561da0` | `RAINBOWSIX3PS2US` |
| SDK/login version | Setter `0x003ffd50`; getter `0x003ffe30` is the third primary-login string (`0x00407120`) | `RSPS21.0` |
| Game version | Setter `0x003ffcf0` | `1.0` |

`0x00561da0` resolves `gsconnect.ubisoft.com`, connects to TCP 80 and sends:

```http
GET /gsinit.php?user=<user>&dp=RAINBOWSIX3PS2US HTTP/1.1
HOST: gsconnect.ubisoft.com

```

Reader `0x003ff9c0` enumerates routers (type 0), NAT servers (type 3) and
IRC servers (type 4) through `0x00469f20`. That lookup uses section name
GP−`0x7880` = `Servers`, with keys `RouterIP%d`, `RouterPort%d`,
`NATServerIP%d`, `NATServerPort%d`, `IRCIP%d` and `IRCPort%d`.
`RouterLauncherPort%d` is read separately and defaults to 40005. Success
requires a nonempty router list and NAT list. The bootstrap response is
therefore the same sectioned dialect as GR2:

```ini
[Servers]
RouterIP0=192.0.2.10
RouterPort0=30020
RouterLauncherPort0=30021
NATServerIP0=192.0.2.10
NATServerPort0=30022
```

The NAT branch compares the NAT hostname with `gsnat.ubisoft.com`, as GR2
does. Its address-conversion branch remains **Pending** a live callback.

## Sign-in sequence

The game's online state machine `0x00541c70` logs each stage. In order:
LOGIN → LOGIN LOBBY → LOGIN FRIEND → GET PERSONAL INFORMATION → LOGIN CHAT →
NAT → LADDER (conditional) → DEDICATE → DEDICATE LOBBY. This is the same
shape as GR2's sign-in.

| Stage | Native sender / reader | Wire shape | Tubisoft handler |
| --- | --- | --- | --- |
| Key exchange | `0x00446610`, `0x00446830` (type `0xdb`, route 8→2) | Public key, then cipher key | Shared |
| Primary login | `0x00410220` via encrypted sender `0x0043af30` | `0x66` with username, password, `RSPS21.0`, one-byte binary | Shared 4-field path |
| Wait address | `0x004104f0` | Empty `0x5d` | Shared |
| Wait login | `0x004103b0` | `0x4d [username]` | Shared |
| Discovery | `0x00417500` | `0xd1 ["21", [product]]` | `R6Profile.discovery_login` |
| Folder record | Reader `0x00416f00` (14 fields); child reader `0x00416c20` (20 fields) | Same layout as GR2 | `R6Profile.parent_lobby` |
| Friends login | `0x00412650` | `0x4e` with two 4-byte binaries | Shared |
| Ignore list | `0x00414b40` | Empty `0x54` | Shared |
| Player info | `0x00410610` | `0x13 [username]` | Shared |
| Notices | Sender `0x00410aa0`; reader `0x00411f80` | `0xde [language]`; reply needs `[binary 0xde, [text, text]]`, each ≤ 0x201 bytes | `R6Profile.login_notices` |
| Ladder lookup/select | `0x004372d0`, `0x0042f2b0` | `0xcc ["1", ["ladderquery","0","0"]]`, then operation 2 | Shared proxy directory |
| Proxy login | `0x00452810` (route 8→11) | Plain `0x66 [username, version]`, then `0x5d`/`0x4d` | Shared proxy handoff |
| Ranking query | Serializer `0x004379d0` | `["1", [app-id, product, u32, u32, [selection 0–3, values], [cols, sort, filter]]]` | `R6Profile.ranking_table` (see below) |
| Lobby address | `0x00429300` | `0xd1 ["3", ["1"]]` | Shared |
| Lobby login | `0x00428f30` | `0xd2` with five fields (string, number, string, string, number) | Shared discovery path |

The language branches differ from GR2. `0x005129a8` selects `en`, `ge`,
`fr`, `es` and `it`; `0x00542dd4` selects `en`, `de`, `fr`, `es` and `it`.
The profile accepts both German codes.

The primary login object layout matches GR2: username at offset 4,
password at `0x14` and version at `0x25` (`0x0040dc30`). The proxy login
copies the version, so the profile's SDK version must stay `RSPS21.0`.

## Ladder stage requirements

The first retail run (Tubisoft in Docker, PCSX2) signed in, discovered the
parent folder, completed NAT and the proxy handoff, and received all eight
ranking replies. The game then disconnected and showed "Service is not
available right now". Empty tables were the cause.

Sign-in issues eight queries:

| Issuer | Selection | Columns | Result parser | Empty table |
| --- | --- | --- | --- | --- |
| `0x00485e80`, ladders 0–3 | type 1 `[alias, 1]` | none | `0x004849b0` | Accepted as status −10 |
| `0x00485db0`, ladder 0 | type 3 `[0, count]`, sorted by `GLOBAL_RANK` | `ALIAS`, `GLOBAL_RANK`, `RATING` | `0x00485410` | Accepted (zero rows) |
| `0x00485f50`, ladders 1–3 | type 2 `[alias]` | `ALIAS`, `LEVEL` | `0x00485250` | **Rejected** |

Callback `0x00485940` marks a result successful only when its parser
succeeds, and otherwise stores −10. The LADDER stage of `0x00541c70` tolerates
−10 for the type-1 entries (`0x00485780`) but requires success for the top
list and the three type-2 entries (`0x00485760`, `0x00485810`). Parser
`0x00485250` reads row 0 and needs `ALIAS` (string) and `LEVEL` (integer).

Deserializer `0x0043d330` reads `["1", [query-id, total, columns, rows]]`.
Each column is a two-string list (field name ≤ 128 bytes, second name ≤ 32
bytes). The first string is the lookup key (`0x0043d190`). Each row is a list
of strings, one per column. The profile now returns one row per requested
alias for type-2 queries, with `ALIAS` set and every other field `0`, and keeps
the other selections empty. No stats are stored or invented beyond those
unranked defaults.

## Entering the parent lobby

The second retail run passed the LADDER stage and reached the lobby list.
Selecting **Rainbow Six 3** sent lobby address `3`, five-field `0xd2`, then
`0xd1 ["23", ["1", "", "256"]]`. The profile did not yet implement operation
23, so the server closed the lobby connection and the game disconnected.

Lobby operations are issued through `0x0042a1d0` with the operation number
in `a3`; completion readers check the envelope with `0x00415d50`/`0x00415da0`.

| Operation | Sender | Fields | Reader |
| --- | --- | --- | --- |
| 23 parent join | `0x004177e0` | group ID, password, option | `0x0041a730`: group ID, optional string |
| 42 player data | `0x00419980` (from `0x004013a0`) | one 24-byte binary (GR2: 28) | `0x00421710`: envelope only |
| 24 game join | `0x004179d0` | number, string, number, number, string | `0x0041ab90` |
| 12 create | `0x00417dd0` | 11 values incl. two binaries | `0x0041ba60` |
| 8 leave, 9 refresh | `0x00417c00`, `0x004197e0` | group ID / group, number | `0x0041dd10`, `0x0041a2c0` |

Other issued operations: 10, 15, 17, 30, 31, 33, 34, 35, 44, 45, 70. The
profile now accepts the public parent join (`["1", ""]` reply) and the 24-byte
player record. Game-room create and join (12, 24) remain unsupported. Note that
R6 can create rooms through the lobby server (operation 12), as Splinter Cell
Chaos Theory does, in addition to the launcher `0xd5` path below.

## Creating a game (lobby operation 12)

The third retail run entered the empty parent lobby and selected Create Game.
The client sent `0xd1 ["12", [...]]` with eleven values on the lobby-server
connection, not the launcher `0xd5` registration. Sender `0x00417dd0` builds:
parent ID, room name, product, three u16 values, game data (binary), password,
two version strings and additional data (binary). Its caller `0x00404080`
fills the u16 values from its own new entry: the group type (`+0x00`, 5 in
retail), the player limit (`+0xc8`) and a constant 0 (`+0xd0`). A Create Game
with six players therefore sends `5`, `6`, `0`. An earlier version of the
profile read these as players, spectators and flags, so the list showed a
maximum of 5.

Reader `0x0041ba60` expects `["38", ["12", [room-id, text, parent-id]]]`;
`0x004284f0` files the new room under that parent. A failure (`39`) carries
the error text at the same index. Owner operations 15, 17, 30, 31 and 33 each
have a reader that only checks the envelope and reads the room ID.

`tubisoft` now creates an active room for the creating lobby connection
(with the creator's group type), answers the owner's join (`[room-id, ""]`, reader `0x0041ab90`), withholds
GAME_STARTED from the owner, accepts the owner updates above (operation 33
supplies the game port and local address), lists the room on refresh and
removes it when the owner leaves or disconnects. Password-protected rooms are
rejected.

The fourth run showed the owner sending `0xd1 ["34", [room-id]]` about three
seconds after creating its room, while the match loaded. Operations 34, 35,
44, 45 and 70 (senders `0x00419440`, `0x00419270`, `0x004184b0`,
`0x00418320`, `0x00418640`) carry only the room ID and have no completion
reader. Rejecting 34 had closed the owner's lobby connection and removed the
room before a second PC could list it. The profile now accepts these reports
without a reply. In that run every client also appeared from the same source
address, because Docker's port forwarding replaced the real client addresses;
guest joins need the real public/LAN addresses.

## Listing a hosted game

With real client addresses, the second PC still showed **No Game Available**
although the server listed the room. A PCSX2 save state of that PC showed the
room had reached the game's own list: the lobby list object (global
GP−`0x4768`, vector at `+0x1a4`) held one entry for room 1000, added by the
group-new handler `0x00404780`. That handler only accepts a room whose
product is `RAINBOWSIX3PS2US`, versions are `1.0`/`RSPS21.0` and game data is
exactly 84 bytes, which all matched.

The entry's addresses were the problem. The host ran on the server PC, so its
connections reached the container from the Docker bridge gateway. The room
record carried that gateway address, NAT discovery reported it to the host,
and the host embedded it in the last eight bytes of its 84-byte game data
(IPv4 and little-endian game port). Its own local address was PCSX2's
emulated `192.0.2.100`. Neither is reachable from another PC, so the entry
was never shown.

`ubisoft.hostalias` now reports clients that arrive from the container's
default gateway at `TUBISOFT_ADVERTISE_IP` (`TUBISOFT_HOST_ALIAS=auto`,
active only inside a container). Router rooms, handoffs, NAT replies and the
XIII UDP host login use the reported address; replies still go to the real
source. The R6 profile also ignores the emulated `192.0.2.0/24` local address.

With correct addresses the list was still empty. The next save state showed
the pinger (`0x0046a690`) had measured the host at 4 ms, so reachability was
not the cause. The match-list filler `0x004e1ea0` (`P_lobby_matchlist`)
applies these checks to every entry:

- It skips the player's own room.
- If the game data's word at `+0x48` is nonzero (the R6 host sets it to 1),
  `0x00401720` must find the room owner (`+0x34`) in the lobby member list
  (`+0x1b0`), filed under the room's ID and lobby server ID. Otherwise the
  room is hidden.
- When a search is active, it also applies the search filters.

The server never sent member records, so the guest's member list was empty
and every player-hosted room was hidden. Members come from operation 50
(reader `0x004237f0`; callback `0x004034a0`):

```
["50", [name, flag, group ID, address, local address, player data, u16]]
```

The callback files the member with that one group and the connection's lobby
server ID. A later record for the same name replaces the earlier one
(`0x00403070`). Operation 51 (reader `0x00423ea0`) carries `[name, group ID]`.
When the player data is the 24-byte parent record (IPv4 and port first) and
the receiver owns its current room, the callback sends `PERMIT PING`
(`0x0050e2a0`) to that address. Operations 66 (`0x00425800`, `[name, data]`)
and the operation-12 result callback (`0x00403f60`) can do the same.

The R6 profile now keeps a per-service directory of parent members. A member
is recorded at operation 23 and announced to the others once operation 42
supplies its player data. Each member's group is the room it hosts or has
joined, otherwise `1`. On parent join, the server sends the joiner the
records it already has. Room creation, joining or leaving a room, and a closed
room re-announce the member's group. Leaving the parent or disconnecting
sends operation 51. Room records now carry the owner's sign-in name exactly
as the game sent it (`Room.owner_name`), because both `0x00401720` and the
owner check `0x00401180` compare names byte for byte. **Pending:** a retail
check with two PCs.

## Player counts and joining

In the eighth retail run the game was listed but showed `0/5` instead of
`1/6`. A guest joining from the second PC lost its lobby connection: the
server rejected its in-room player data (operation 42) because the profile
had no R6 player-port parser. The reverse direction reached the match even
though the same rejection occurred.

The list's players column is entry `+0xcc` / `+0xc8` (filler `0x004e1ea0`).
The group-new handler always starts `+0xcc` at 0 and ignores the record's
current-player field. Only the member callbacks change it: `0x004034a0`
increments it (or `+0xd4` when the member's flag character is nonzero), and
`0x00403220` (operation 51) decrements it. Both do so **only for group IDs
of 0 or less**. The same sign test chooses between the "in game room" and
"in lobby" state bits (`0x00405090`, `0x004050c0`) for the player's own
record. Operation-51 handling for the player itself leaves the whole lobby
for a positive ID. The group-change callback `0x00401dd0` (operation 57)
also treats IDs of 0 or less as games. This SDK therefore gives game rooms
non-positive IDs, and `Num` fields are parsed with `atoi` and written with
`%d`, so they can be negative.

The profile now:

- numbers R6 rooms `-1000`, `-1001`, … (`negative_room_ids`). The router
  accepts a leading `-` in join (24) and additional-info (46) requests;
- sends other parent members the new game's record (`53`, children only)
  when it is created, then the owner's member record with the room's ID, so
  the owner is counted;
- sends a joining guest the members already in the room, so they enter its
  room member list (`+0x1bc`, via `0x00403070` -> `0x00401810`);
- on leaving a room, sends `51 [name, room]` before re-announcing the member
  in the parent, and sends `55 [room]` to parent members when a room closes
  (reader `0x0041b820` -> `0x00403b40`);
- accepts in-room player data from R6 guests as a member update. The join
  callback `0x00404300` republishes it through `0x004013a0`;
- no longer sends GAME_STARTED. R6's callback for it (`0x00402520`, reached
  from reader `0x004168e0`) is empty.

The ninth retail run confirmed the count, hosting from either PC and joining
in both directions, with both players in the match. Names over other players
were still not drawn. The guest's save state shows the GS side is complete.
The current room is `-1001`, and the host appears in both the lobby and room
member lists, filed under `-1001` with lobby server ID 1. Both names also
exist as Unreal strings in the match. The client builds its own travel URL
with `?Name=` and its GS name (`0x0020af90`, using `0x003ffe50`), and the
server takes no part in that. Drawing names is UnrealScript HUD logic
(`SetIdentifyTarget`, the server option `ShowNames`), so it is most likely a
game-mode or option effect rather than a lobby-protocol gap.

## Launcher hosting path (XIII-like)

The launcher client (global GP−`0x46f0`) logs in with three strings
(`0x004539b0`) and registers a room with `0xd5` (`0x00453ca0`). Its body is
`["12", <number>, [16 values]]`: string, number, string, string, number,
two numbers, two binaries, three strings, number, local address string,
port number and a final binary. That matches XIII's 16-field registration.
Host operations 17 (`0x00454a50`) and 45 (`0x00454c40`) also match XIII's
host-update subtypes. Child records use the 20-field reader `0x00416c20`.

R6 also has DEDICATE and DEDICATE LOBBY sign-in stages, so the retail
client may look for dedicated servers too. The `0x00541c70` branches
that choose between them are **Pending**.

`supports_rooms` remains false. Before enabling it, map the join request,
game-start (`56`) fields, player-info blob and member notifications from
this disc. Do not reuse XIII's group flag `0x08`, four-byte player port or
member-event layout until the R6 readers confirm them.

## Comparison capture

A Splinter Cell Chaos Theory PS2 client capture (client-to-server direction
only) shows the same order in a later title: key exchange,
encrypted `0x66`, `0x5d`, `0x4d`, discovery `21`, friends `0x4e`, notices
`0xde`, `ladderquery` lookup/select/report, proxy `0x66`/`0x5d`/`0x4d`,
`1281` ranking queries, lobby address `3`, five-field `0xd2`, parent join
`23` and 28-byte player data `42`. The capture is not R6 evidence. It
supports the order and helps interpret R6's static readers. The captured
account names and addresses are not reproduced here.

## Implemented profile

`ubisoft.games.r6` registers slug `r6`, product `RAINBOWSIX3PS2US`, SDK
version `RSPS21.0`, default ports 30020 TCP/UDP, 30021 TCP and 30022 UDP,
the `[Servers]` bootstrap, discovery, empty notices, the ladder proxy and
ranking tables, parent-lobby join and the 24-byte parent player record. Rooms
are created through lobby operation 12, and parent members are announced with
operations 50 and 51. Guest joins remain incomplete.

```sh
TUBISOFT_GAMES=xiii,r6 ...
docker compose -f compose.yaml -f deploy/compose.r6.yaml --env-file .env up -d --build
curl --noproxy '*' 'http://127.0.0.1:18080/gsinit.php?dp=RAINBOWSIX3PS2US'
```

`tests/test_r6_profile.py` covers the static shapes. It also runs the
real-socket sequence above: shared XIII/R6 account, discovery, notices with
`ge`, proxy ranking query and lobby login. A second real-socket test checks
that a guest receives the room owner as a member and that the owner receives
the guest's player data and departure.

## Next retail checks

1. Boot R6 in PCSX2 with DNS for `gsconnect.ubisoft.com` pointed at the
   instance. Confirm the bootstrap request and sign-in through the ladder
   stage in the server logs.
2. Confirm the LADDER stage now succeeds with the type-2 `ALIAS`/`LEVEL`
   rows and see whether `LEVEL` 0 displays sensibly in the menus.
3. Record the first `UnsupportedOperation` log after LADDER. It shows which
   DEDICATE or lobby request the profile needs next.
4. Trace that operation's sender and reader in `MP.SOZ` before implementing
   it. A read-only PCSX2 RAM dump of the online state is useful when a reader
   depends on runtime objects.
