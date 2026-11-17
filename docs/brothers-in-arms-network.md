# Brothers in Arms: Road to Hill 30 (PS2): GS compatibility notes

Brothers in Arms: Road to Hill 30 for PS2 (`SLUS-21163`) links the same
Ubisoft GS client library as Rainbow Six 3 and Ghost Recon 2. The game wraps
it in its own `BIAGLClient` class, with debug messages such as
`LoginRcv_LoginRouterResult` and `LobbyRcv_JoinLobbyReply`. Those messages
help when reading the code, but the wire shapes underneath match Rainbow Six
3's. The profile covers sign-in, the MOTD, the ladder proxy, the parent
lobby and its member directory (retail runs 1-3), and player-hosted
matches: two retail clients created, joined (with a password) and played a
full match in run 8. Results feed a stored ladder, whose totals reached the
Stats screen in run 10.

Evidence labels follow [the GR2 notes](ghost-recon-2-network.md):
**Static** (traced instructions or data on this disc), **Retail** (an
unmodified client against Tubisoft) and **Pending**. Sections are **Static**
unless a retail run is named.

## Executables and reproducibility

| Input | SHA-256 |
| --- | --- |
| `SLUS_211.63` | `82146acb1be4c7d88269398daee565c3fab1eed44e921ec92bec04db7d648a39` |
| `MP.SOZ` | `1158d3a0d40f12e6d342ca0bf1742e6c922d0511b955232e33dde1c21c98d973` |

Unlike Rainbow Six 3's file, BiA's `MP.SOZ` is not compressed. It is a plain
MIPS ELF (CodeWarrior "MW MIPS C Compiler 2.4.1.01"), so `ps2re.py soz`
does not apply. Its first program header loads `0x5ec780` bytes at
`0x00100000` with a memory size of `0x722980`. `.reginfo` gives GP
`0x006f4370`, the same value crt0 passes to SetupThread at `0x001001c8`.
Flatten that segment to an image based at `0x00100000` and use GP
`0x006f4370` with `ps2re.py` or Ghidra (`r5900:LE:32:default`):

```python
import struct
raw = open("MP.SOZ", "rb").read()
phoff = struct.unpack_from("<I", raw, 0x1c)[0]
_, offset, vaddr, _, filesz, memsz, _, _ = struct.unpack_from("<8I", raw, phoff)
image = bytearray(memsz)
image[:filesz] = raw[offset:offset + filesz]
assert vaddr == 0x00100000
```

The message-name function `0x004c75d0` maps types to the SDK names. Its
numbering matches XIII, GR2 and R6 (`0x26` GSSUCCESS, `0x3a` STILLALIVE,
`0x4d` LOGINWAITMODULE, `0x5d` JOINWAITMODULE, `0xd1` LOBBY_MSG, `0xd2`
LOBBYSERVERLOGIN). Keep extracted images and listings outside the repository.

## Identity and bootstrap

Pointer table `0x0065fe10` holds the bootstrap host, the request format and
the title's identity:

| Item | Evidence | Value |
| --- | --- | --- |
| Product (`dp`) | `0x0065fe20` → `0x006a36c0` | `BROTHERSINARMSPS2US` |
| SDK/login version | `0x0065fe28` → `0x006a36d8`; passed to the primary login by `0x0051d8bc` | `BIAPS2US1.0` |
| Game version | `0x0065fe30` → `0x006a36e8` | `1.0` |

`0x00530410` formats the request as
`GET /gsinit.php?dp=%s&user=%s HTTP/1.1` with `HOST: gsconnect.ubisoft.com`.
The reader `0x005300b0` uses the same sectioned dialect as GR2 and R6. It
enumerates routers (type 0) and NAT servers (type 3) through `0x004ed130`,
using section `Servers` (`0x006a6878`) and keys `RouterIP%d`,
`RouterPort%d`, `NATServerIP%d` and `NATServerPort%d`. It reads
`RouterLauncherPort%d` separately and defaults it to 40005. It succeeds only
when both lists are nonempty:

```ini
[Servers]
RouterIP0=192.0.2.10
RouterPort0=30030
RouterLauncherPort0=30031
NATServerIP0=192.0.2.10
NATServerPort0=30032
```

The enumerator also knows `CDKeyServerIP%d`, `ProxyIP%d` and `IRCPort%d`.
They are not needed for sign-in.

## Library layout

The login client creates a reply parser with `0x004f03c0` and checks the
reply's type with `0x004f0420`, which accepts `0x26` and `0x27`. Senders
build a GS value list and pass it to `0x00517de0` (plain) or `0x00517e20`
(encrypted). The lobby client's operation sender is `0x00508480`. Reply
readers use typed getters:

| Getter | Reads |
| --- | --- |
| `0x004e91e0`, `0x004e9350` | Nested list |
| `0x004e9740` | String, bounded copy |
| `0x004e9660` | String, unbounded copy |
| `0x004e9890`, `0x004e9970` | 32-bit number |
| `0x004e9b30`, `0x004e9a50` | 16-bit number |
| `0x004e9c10` | 8-bit number |
| `0x004e9d50` | Binary |

The game calls the library through a thunk table at `0x0050b240`-`0x0050b670`.
For example, `0x0050b260` is the primary login, `0x0050b2b0` creates an
account and `0x0050b2c0` requests the MOTD.

## Sign-in sequence

`UGameServiceSubsystem::Tick` (`0x0051d510`) drives sign-in:
LoginSend_Connect → router login → wait module → NAT → MOTD, friends and
player info → lobby. `BIAGLClient::SetLoggedIn` (`0x00528c50`) then
initializes the ladder (`0x00524910`).

| Stage | Native sender / reader | Wire shape | Tubisoft handler |
| --- | --- | --- | --- |
| Key exchange | Library | `0xdb`, as in R6 | Shared |
| Account creation | `0x004f0dc0` (encrypted) | `0x01` with seven strings: SDK version, username, password, four empty strings | Shared |
| Primary login | `0x004ef0c0` → `0x004f07b0` (encrypted) | `0x66 [username, password, BIAPS2US1.0, 1-byte binary]` | Shared 4-field path |
| Wait address | `0x004f0a30` | Empty `0x5d` | Shared |
| Wait login | `0x004f0920` | `0x4d [username]` | Shared |
| Discovery | `0x004f7340` | `0xd1 ["21", [product]]` (21 is GP constant `0x006ec678`) | `BIAProfile.discovery_login` |
| Folder record | Reader `0x004f6d80` (14 fields); child reader `0x004f6aa0` (20 fields) | Same types and bounds as R6 | `BIAProfile.parent_lobby` |
| Friends login | `0x004f2780` | `0x4e` with two 4-byte binaries | Shared |
| Ignore list | `0x004f4d10` | Empty `0x54` | Shared |
| Player info | Sender `0x004f0b30`; reader `0x004f1410` | `0x13 [username]`; reply of seven strings | Shared |
| MOTD | Sender `0x004f0f60` via `0x0051cd40`; reader `0x004f2040` | `0xde [en/fr/de/it/es]`; reply `[0xde, [text, text]]`, each ≤ 0x201 bytes | `BIAProfile.login_notices` |
| Lobby address | `0x005075e0` | `0xd1 ["3", [number]]` | Shared |
| Lobby login | `0x00507230` (encrypted) | `0xd2` with five fields (string, number, string, string, number) | Shared discovery path |
| Parent join | `0x004f7600` | Operation 23 `[group, password, number]` | `BIAProfile.join_parent_lobby` |
| Parent player data | `0x00528cb0` → `0x0050b5d0` → `0x004f93e0` | Operation 42 with **12** bytes (IPv4, port, four more bytes) from player record `+0x68c` | `BIAProfile.parent_player_info` |
| Member joined / left | Readers `0x00502aa0` / `0x00503140` | Operations 50 / 51, R6's shapes | `BIAProfile.lobby_member_event` / `lobby_member_left` |
| Lobby refresh | Tick `0x0051d510` (call `0x0051e048`); join reply `0x0052a500` (call `0x0052abf4`) | Operation 9 `[group, flags]`, flags 0x40 on a timer and 0x1c0 after joining | Shared group record |

The parent player data is shorter than R6's (24 bytes) and GR2's (28 bytes).

### Completing a parent join (Retail run 1)

R6 sends operation 42 after the operation-23 reply. BiA does not.
`LobbyRcv_MemberJoined` (`0x0052bf00`) compares each member's name with the
player's own (`+0x16b`, 16 bytes). Only when they match does it call
`0x00528cb0`, which sends operation 42. Without that event the join times
out ("Join lobby request timed out, leave the lobby now", `0x006a4f00`), the
game shows an error and sends operation 8. Retail run 1 did exactly this:
the server accepted operation 23, no operation 42 followed, and operation 8
came about 2.5 minutes later. The profile sets `self_member_event`, so the
joining player receives its own operation-50 record (without player data)
after the existing members.

Tick's timer re-requests every listed lobby with operation 9. In run 1 that
was about every 0.5 seconds for as long as the player was signed in (708
requests in nine minutes). R6's handler re-sends every known member on each
operation 9, and BiA would show each one as a join message. The profile's
`group_refresh` hook answers that timed refresh (flags 0x40) with the lobby
record alone: no members, and since run 9 no rooms either (see Room player
counts).

### NAT address byte order (Retail run 7)

The NAT server reports the observed address as a decimal 32-bit value.
XIII's callback compares it with `inet_aton` output, so the shared server
sent the in-memory `s_addr` form: first octet in the low byte. BiA's
`CNatService::CBRequestFinished` (`0x0060f230`) stores the word at `+0x98`
and prints it byte 3 first ("Got RAW NAT info"); so do the PERMIT PING
sender (`0x0060eef0`, which formats `%i.%i.%i.%i` from bytes 3-0 and
resolves the string) and `GetCurrentRoomIPAddress` (`0x005279e0`). BiA
therefore reads a host-order integer, first octet in the high byte, and
carried the reversed address into its player data and session info.

In run 7 a capture on PC2 showed PERMIT PING (13 bytes) to PC1's address
with its octets reversed, each within milliseconds of an operation-50
record for PC1. The profile sets `nat_address_byteorder = "big"`; the other
titles keep `"little"`. The `endpoint=` and `host_endpoint=` log lines read
the record in the title's order. Retail run 8 played a full match with the
fix.

### Lobby pings (Retail runs 2, 3 and 13)

When `LobbyRcv_MemberJoined` receives another member with 12 bytes of player
data, it sends `PERMIT PING` (`0x0060eef0`) to the address and port in that
data (`0x0052c010`-`0x0052c060`). It then calls `0x0052b2c0`. If the
member's address equals the player's own (`+0x68c`), that function replaces
it with the member's LAN address string on port 7777 (`0x1e61`). The 12
bytes are most likely the address `CNatService` learned from the NAT server
("Got RAW NAT info", `0x006ae8f0`).

The joining player gets the existing members' data at once. The existing
members get the joiner's data only after its operation 42. In run 2 the
second PC to join could not ping the first; the first could ping the second.
Two explanations remain: BiA pings once, before the first PC has permitted
the second, or the first PC (the Docker host) cannot receive unsolicited
UDP. The operation-42 log line now records `endpoint=<kind>:<port>`. The kind
is `peer` when the data's address equals the connection's (after the host
alias), else `emulated`, `loopback`, `lan-10`, `lan-172`, `lan-192` or
`other`; the address itself is never logged.

Run 3 reversed the join order and the asymmetry stayed with the Docker host
(PC1): both PCs showed PC2 as reachable, and PC2 did not show PC1. Both
records were `peer:7777`, so the server announced each player's own address
and game port. Ordering is ruled out, and so is a wrong record. The
remaining cause is outside the protocol: UDP from PC2 does not reach
PCSX2's port 7777 on the machine that also runs the server (Windows
firewall profile or the WSL2/Docker host path).

That conclusion was wrong. Run 7 found the real cause: the NAT address
byte order (see above), which sent PERMIT PING to an address with its octets
reversed. With the byte-order fix both players showed a green ping to each
other (reported with retail run 13).
The 0x13 player-info reply has seven strings, as in R6. The order in which
BiA files them is **Pending**; R6 needed a save state to find it.

### MOTD

The game shows two MOTD lines, from `GetGameMOTD` and `GetUbiMOTD`. The
profile sends its two `news` items, which `TUBISOFT_BIA_NEWS_1` and
`TUBISOFT_BIA_NEWS_2` can replace (printable ASCII, up to 512 characters).

### Account changes (`0x62`)

BiA's `0x62` sender `0x004f0c40` (encrypted) changes the password. It sends
an empty string, the new password and four strings echoed from player info.
`LoginRcv_PlayerInfo` (`0x005296b0`) sends it after the player chooses a new
password. R6 uses the same message number for its personal-info update,
whose fifth field is a country code. The shared handler now requires
`profile_country_update`, which only R6 sets. BiA's request gets `0x27`
(`LoginRcv_ModifyUserResult: failed`); nothing is stored or logged.
Password changes are **Pending**.

## Ladder

The ladder uses the `ladderquery` proxy service (lookup sender `0x00511c30`),
like GR2 and R6. Queries go through thunks `0x0050b620`-`0x0050b670`:

| Game function | Selection | Columns |
| --- | --- | --- |
| Top list `0x00529360` | Type 3 `[start, count]` (`0x005061b0`) | Table `0x0065feb0`: GLOBAL_RANK, ALIAS, SCORE, RANKED_WINS, RANKED_RNDS |
| Around me `0x005293f0` | Type 1 `[alias, count]` (`0x005060c0`) | Same five |
| Player info `0x00529490` | Type 1 `[alias, 1]`, sorted by GLOBAL_RANK | Table `0x0065fe90`: GLOBAL_RANK, ALIAS, SCORE, ACCURACY, RANKED_RNDS, RANKED_WINS, FRIEND_RNDS, FRIEND_WINS |

The full column list at `0x0065fe40` also names QUERY_RANK, COUNTRY,
COUNTRY_ID, KILLS, DEATHS, FIRED, HITS, ALLY_MATCHES, AXIS_MATCHES and
PLAY_TIME. The ladder is initialized at sign-in, but queries come only from
the menus. They are answered from the stored totals (see Results, Ladder);
a player with no stored match gets the empty table
`["1", [query ID, "0", [], []]]`.

## Lobby operations

The lobby client sends the same operation numbers as R6 through `0x00508480`:
23 (`0x004f7600`), 24 (`0x004f77d0`), 8 (`0x004f79e0`), 12 (`0x004f7b90`),
17 (`0x004f7f30`), 45 (`0x004f80b0`), 44 (`0x004f8220`), 70 (`0x004f8390`),
31 (`0x004f8500`), 30 (`0x004f89b0`), 33 (`0x004f8a60`), 35 (`0x004f8d50`),
34 (`0x004f8f00`), 15 (`0x004f90b0`) and 9 (`0x004f9260`). It also sends 42
(`0x004f93e0`) and 106 (`0x004f9670`, one string, used by JoinFriend
`0x00520bd0`). Room creation (operation 12) has R6's eleven fields: parent,
name, product, three numbers, binary, password, two version strings and a
binary. Unlike R6, BiA offers password-protected matches
(`SetCreateMatchPassword`). Its match results also differ. BiA reports
kills, deaths, shots fired, hits, time, team, type and status per player
(`UGameServiceSubsystem::SubmitMatchResults`). R6 reports twelve ladder
values.

### Reply dispatcher

`0x004ef620` routes `["38" or "39", [operation, data]]` replies by
operation number. "38" is GSSUCCESS (0x26) in decimal and "39" is GSFAIL
(0x27). On failure a reader starts one field later, after a reason code.

| Operation | Handler | Reader |
| --- | --- | --- |
| 8 | `0x00503c00` | `0x004fd510` |
| 9 | `0x005028b0` | `0x004f9cd0` |
| 12 | `0x00502910` | `0x004fb380`: room ID, text, parent ID |
| 15 | `0x00503e40` | `0x004fe940` |
| 17 | `0x00503510` | `0x004fb9a0` |
| 23 | `0x00502a10` | `0x004fa110`: group ID, text |
| 24 | `0x00502980` | `0x004fa540`: room ID, text |
| 30 / 31 / 33 | `0x00503dd0` / `0x00503d60` / `0x00503eb0` | `0x004fe060` / `0x004fdbe0` / `0x004fedc0` |
| 45 | `0x00503690` | Pending |
| 50 / 51 / 53 / 55 / 56 | `0x00502aa0` / `0x00503140` / `0x005013d0` / `0x005034b0` / `0x00503f20` | Pushes |
| 62 / 71 | `0x00503cd0` / `0x00505260` | Pushes |
| 106 | `0x00504ec0` | Friend location, no status field (see Joining a friend) |

Operations 34, 35, 44 and 70 have no reader: they are one-way reports.

## Matches (Retail run 4, then Static)

The menu offers Friendly or Ladder, two or four players, and Protected.
CreateRoom (`0x0051e960`) calls `0x0050b420` with the lobby ID, the name,
the product, group type 5, the player limit, 0 spectators, 0x50 bytes of
session info from `+0x4f4`, the password from `+0x550` and the SDK and
game versions. Retail run 4 showed the eleven field types. The profile
requires a limit of 2-4 and exactly 0x50 bytes of session info.

The match type is not a field of its own. `LobbyRcv_NewRoom` (`0x0052b370`)
ignores a room whose session info is not 0x50 bytes and decodes the map
name, match type, friendly fire and player number mode from it. The entry
constructor `0x00527920` copies it to the room entry at `+0x24`: the host's
NAT address is at `+0x28` and its port at `+0x2c`. The locked flag that
CheckNewRoom (`0x00522460`) tests is bit 4 of `+0x25`, so the host marks
its own room as Protected. The server stores the password with the room
(never logged) and compares it on operation 24.

After the creation reply, `CreateRoomReply` (`0x0052a390`) records a
"wait room", joins with operation 24 at once (`0x0050b490` → `0x004f77d0`,
with the password) and sends PERMIT PING to the lobby members. NewRoom then
reports "The waited room comes" when the room's record arrives. The creator
therefore also receives the new listing (`creator_room_listing`).

A wrong password gets `["39", ["24", ["11", room ID, ""]]]`.
`JoinRoomReply` (`0x0052afc0`) maps reason 11 to its own lobby event
(0x18), reasons 5 and 7 to 0x19, and others to 0x1b, which `JoinRoom` also
fires as FAILEDTOJOINROOM (`0x0051ee18`). In retail run 8 a wrong password
got this reply without a disconnect, and a retry with the right password
joined.

Room updates 15, 17 and 33 and reports 34, 35, 44 and 70 have R6's
shapes. Operation 17 starts a match: the server replies and sends operation
62 `[room, match ID]` to the room (reader `0x004fd990`).

Operation 31 changes room data. Its sender (`0x004f8500`) puts a mask after
the room ID and then only the fields that the mask names, in this order:

| Mask bit | Field |
| --- | --- |
| 0x2, 0x4 or 0x200 | a second mask (bits 0x4000, 0x10 and 0x800) |
| 0x8 | player limit |
| 0x10 | spectator limit |
| 0x20 | name |
| 0x40 | session info (binary) |
| 0x400 | additional info (binary) |

Retail run 8 sent every field (eight in all). Retail run 10's Play Next
Game sent the room ID, mask 0x40 and new session info. The profile had
expected eight fields, so it rejected that message and closed the host's
connection. It now reads the mask. A 0x50-byte session info replaces the
room's, and a player limit of 2-4 replaces the room's limit. The name is
checked but not used. Other mask bits are refused.

Retail run 11 got past that point. Selecting a mission and pressing Play
Next Game then did nothing: the host sent operation 31 132 times in about
35 seconds and finally showed "Can not access game service". The reply is
not what the host waits for. `ChangeMatchMap` (`0x0051fe80`) sets request
14 (`+0x3c`) and sends operation 31. The handler for the 31 reply
(`0x00503d60`) calls lobby callback slot `+0x6c`, which is empty
(`0x0052d3c0`). The request completes when the room's own record arrives
as operation 53 with flags 0x40. Handler `0x005013d0` reads the 20-field
room record and calls `RoomInfo` (`0x0052bad0`, slot `+0x28`). `RoomInfo`
finds the listed room by ID and lobby server and copies the record's
session info into the entry (`+0x24`, a plain copy of the record's
length). If request 14 is pending, it then fires
`GSEVT_MATCH_UPDATEDGAMEINFO`.

The profile's `room_update_event` hook now sends
`["53", [room ID, "64", room record]]` to every parent-lobby member after
an operation 31, the owner included. Other members' listings take the new
session info without being rebuilt, so player counts are kept. Operation
53 with flags 0x100 lists the children instead (`NewLobby`/`NewRoom`, slots
`+0x24`/`+0x20`). `UpdateGameInfoReply` (slot `+0x88`) belongs to operation
41 (handler `0x005044e0`), not to 31. Retail run 12: one operation 31 and
its record were enough, and the host started the next round (operation 17,
a new match ID), whose results were recorded.

Guests connect to the address and port in bytes 4-11 of the session info
(entry `+0x28`/`+0x2c`): `GetCurrentRoomIPAddress` (`0x00526450` →
`0x005279e0`) and `GetCurrentRoomPort` (`0x005264f0` → `0x00527a00`).
CreateRoom fills them from the NAT service (`0x00821940` `+0x98`/`+0x9c`),
i.e. the address the NAT server observed. The server only relays them; the
room-created log line records them as `host_endpoint=<kind>:<port>`.
BiA's GAME_STARTED handler (`0x0052d6f0`) only reports GameConnected for
the current room (`0x0050b5b0`); it does not start the connection.

### Results (Retail run 8)

After operation 62 each player sent operation 44 twice. At the end of the
round the owner sent operation 30 with R6's layout,
`[match ID, 0, entries]`, each entry being name, highest field ID (7), field
count (8), field mask (255) and eight values by field ID.
`SubmitMatchResults` (`0x00524570`) prints them in field order: status (1
win, -1 loss), kills, deaths, shots fired, hits, time, team and match type.
Run 8's two entries were `[1, 0, 5, 35, 2, 600, 1, 0]` and
`[-1, 1, 5, 27, 3, 600, 0, 0]`.

The reply reader (`0x004fe060`) reads one number: `["38", ["30", [match
ID]]]`. Operation 45's reader (`0x00503690`) reads two, which
`LobbyRcv_MatchFinishReply` logs as group ID and lobby server ID:
`["38", ["45", [room ID, "1"]]]`. The final statistics, operation 71
(`0x00505260`), carry `[match ID, status, [[name, [values]], ...]]`.
`LobbyRcv_FinalMatchResults` (`0x0052dd40`, ignored once the player has left
the game map) prints thirteen values per player: SCORE, KILLS, DEATHS,
FIRED, HITS, ACCURACY, RANKED_RNDS, RANKED_WINS, FRIEND_RNDS, FRIEND_WINS,
ALLY_MATCHES, AXIS_MATCHES and PLAY_TIME, the ladder columns after
COUNTRY_ID in table `0x0065fe40`. They are the player's totals, so they need
a stored ladder.

In run 8 the unimplemented results closed the owner's lobby connection.

### Ladder

`games/bia_ladder.py` keeps one row of totals per account in the shared
accounts database (table `bia_ladder`). Operation 30 is validated and
acknowledged; the owner's operation 45 applies the latest results once and
sends every room member operation 71 with each player's thirteen totals.
Players without an account are not stored.

Per match a player adds kills, deaths, shots fired, hits and time. Match
type 0 is Friendly (the player's answer for run 8) and adds a FRIEND round
and, for status 1, a FRIEND win; type 1 is Ladder (retail run 10, after
the player chose a Ladder match) and adds a RANKED round and win the same
way. Team 0 is the Allies and adds
an ALLY match; team 1 is the Axis (run 8: the player on team 1 played Axis)
and any team other than 0 adds an AXIS match. ACCURACY is
hits × 100 ÷ shots fired, rounded down.

Ubisoft's SCORE formula is not in the game. **SCORE is Tubisoft's own**,
chosen by the project owner: 3 points for a Ladder win and 1 for any other
Ladder match; Friendly matches do not change it. The board is ordered by
SCORE, then RANKED_WINS.

Ranking queries are answered from the board with every column (QUERY_RANK,
GLOBAL_RANK, ALIAS, COUNTRY_ID and the thirteen values), the requested ones
first, all integers except ALIAS. A player with no stored match keeps the
empty table.

Retail run 10 played a Friendly match and then a Ladder match (type 1).
Both were recorded, and the Ladder results appeared on the Stats screen.
The ranking queries (selections 1 and 3) returned two rows. **Pending:**
GAME_STARTED (operation 56, whose callback only sends GameConnected) and
room-full checks.

## Room player counts (Retail run 9)

Retail run 9 listed a hosted two-player match as 0/2 instead of 1/2.
`LobbyRcv_NewRoom` (`0x0052b370`) handles a room record whose ID is
already listed by freeing the entry (`0x00531970`) and building a new one.
The entry constructor (`0x00527920`) starts the player count (`+0x1a`) at
0. Only member events change it: `MemberJoined` (`0x0052ca48`) adds one to
the room whose ID equals the member's group, capped at the room limit
(`+0x18`), and `MemberLeft` (`0x0052ce20`) takes one away. Tick refreshes
the group about twice a second with operation 9 and flags 0x40
(`0x0051e048`). The router answered every refresh with the full room list,
so each count went back to 0 within half a second.

The profile's `group_refresh` hook now answers flags 0x40 (`"64"`) with the
lobby record and no rooms. Other refreshes, such as `JoinLobbyReply`'s
0x1c0, get the rooms followed by the known members, so the counts are
rebuilt. Rainbow Six 3 and XIII keep their behaviour. Retail run 10: the
other player saw the hosted match as 1/2. A full room (2/2) needs a third
client to observe, because both players are then in the match.

## Joining a friend (Retail run 9, then Static)

From the friends list, a player can join a friend's game or lobby.
`JoinFriend` (`0x00520bd0`) takes a mode: 0 joins the friend's game and
needs the friend's status to be at least 6; 1 joins the lobby and needs at
least 5. `Friend::UpdateFriend` (`0x00527ca0`, jump table `0x006a38b0`)
maps the GS status of a pushed 0x4a record: 0 → 4, 1 and 7 → 0, 2 → 2,
3 → 3, 6 → 1, 8 → 5, and 9-11 → 7 when the product is
`BROTHERSINARMSPS2US` (4 otherwise). A friend in a room (GS 9 with the
product) can therefore be joined either way. A friend in the lobby reported
as GS 0 (mapped to 4) cannot: in retail run 13, "join friend's lobby"
sent nothing to the server. The profile's `friend_presence` hook now
reports a player in the lobby as GS 8 (mapped to 5) with the product, and
a player in a room as GS 9. Rainbow Six 3 keeps 0 for the lobby. In
retail run 14 (reported, no log saved) the friends list showed a player who
had left the lobby as "Online". That player then joined the lobby from the
friends list, and the friends list then showed them with the status "Lobby".

`JoinFriend` sends operation 106 `[friend name]` on the wait connection.
Retail run 9 sent it while the server had no handler, and the connection
closed. The reply handler (`0x00504ec0`, reached from the dispatcher at
`0x004ef690`) has no status check: it reads `["106", [name, [server, ID],
...]]` and calls callback `0x0052dbd0` with (name, ID, server) for each
pair, then with (name, 0, 0). The callback ignores a name that differs from
the request. It files a positive ID as the friend's lobby (`+0x4d4`, server
`+0x4d8`) and a negative one as the friend's room (`+0x4d0`). The final
call checks what it needs: a lobby join needs the lobby and server, and a
game join needs both and a negative room ID. Anything missing fails with
the game's own event 0x37.

`0x00520ff0` then completes the join. If the player is in another lobby,
it joins the friend's lobby first (`JoinFriendLobby`, `0x005212b0`, runs
after the move). In the same lobby, a game join looks up the listed room
with the friend's room ID and server (`+0x00`/`+0x04` of the entry), fails
with 0x34 for a protected room, and otherwise joins it (`0x0051efa0`). A
lobby join to the player's own lobby fires 0x35 at once. `FireFriendEvent`
(`0x0051c120`) treats 0x35 and 0x36 as the outcome of a friend join and
0x37 as a failure, so 0x35 most likely means "joined the friend's lobby".
Tubisoft has one parent lobby, so a player in it joining a friend's lobby
always ends this way.

BiA therefore numbers rooms like R6 (`negative_room_ids`, from -1000). The
server answers 106 (`friend_joining`) only for a name on the requester's
friends list. It sends the parent lobby `["1", "1"]` and, when the friend
is in a room, `["1", room ID]`. Otherwise the list is empty, and the client
reports that the friend is unavailable. Retail run 10: a player chose to
join a friend's game, received two locations and joined the room
(operation 24) at once.

## Retail runs

1. **Sign-in, lobby join (one PCSX2 client).** Account creation, login, the
   wait module, NAT, discovery, friends, the ignore list, player info, the
   MOTD and lobby login all completed. Joining the lobby showed an error: the
   client never received its own member event (see above). Quick join also
   showed an error. The log has only one operation 23, so Quick Join either
   failed the same way or stopped in the client before joining; with no
   hosted games it cannot find a match anyway
   ("QuickMatch: There is no matches available now", `0x006a17d0`).
2. **Two players in the lobby.** Both joins completed (operation 42 after
   the self event) and each player was announced once. PC1 (the Docker
   host, first to join) showed a green ping to PC2, but PC2 did not to PC1
   (see Lobby pings).
3. **Reversed join order.** PC2 joined first. PC2 still could not ping PC1;
   both PCs could ping PC2. Both records were `peer:7777`. The cause is on
   PC1's side of the network, not in the lobby protocol.
4. **Create Match.** PC2 created a match; operation 12 had the eleven
   field types above and was refused while rooms were unimplemented.
5. **Firewall rule on PC1.** With an inbound UDP 7777 rule on PC1, PC2
   joined first and PC1 second. The server announced each player to the
   other (`peer:7777` records), as in run 3, and the clients sent it no ping
   messages: lobby pings are direct UDP between the clients. Both players
   saw each other in the lobby. PC1 showed a ping to PC2; PC2 showed none to
   PC1. Neither PC shows a ping to itself. A plain UDP listener on PC1
   (PCSX2 closed) received a packet from PC2 on port 7777, so the remaining
   block is specific to PCSX2 on PC1 (for example a program-level firewall
   Block rule, which overrides the port rule).
6. **First match (PC2 hosts, PC1 joins).** PC2 created a two-player match
   (0x50 bytes of session info), received its listing, joined it and sent
   operations 15 and 33 (33 carried port 0). PC1 saw the match and the
   server accepted its operation 24. PC1 then showed a connecting screen
   and left after 60 seconds (operation 8). The lobby part completed; the
   game connection from PC1 to PC2 did not.
7. **Capture on PC2.** Same result as run 6 (`host_endpoint=peer:7777`).
   `tcpdump` on PC2 showed PERMIT PING sent to PC1's address with the
   octets reversed: the NAT address byte order above. It was also the
   cause of the one-way lobby pings of runs 2-5: with the fix, both
   players show a green ping to each other (run 13).
8. **First full match.** With the byte-order fix, PC1 joined PC2's
   protected match after a wrong password (GSFAIL reason 11, then success)
   and both played a full match. The owner's results (operation 30) closed
   its lobby connection because results were unimplemented; see Results.
   Next run: join the lobby with one client, then a second.
9. **Player counts and friends.** PC2 hosted a two-player match and PC1
   joined and left it. The listing showed 0/2 (see Room player counts).
   Adding a friend and the presence updates worked. From the friends list,
   PC1 chose to join PC2's game. The operation-106 request went unanswered
   and PC1's lobby connection closed (see Joining a friend).
10. **Friend joining, Friendly and Ladder.** Joining a friend's game
    worked. A Friendly match and a Ladder match were played, and the Ladder
    results showed on the Stats screen. After the first match the host
    chose Play Next Game. It sent operation 31 with only the session info,
    the server rejected it and closed the host's connection (see Matches).
    The lobby showed a limit of 8 players, a placeholder copied from R6.
    Players cannot create lobbies, so the parent lobby now advertises 100
    (`LOBBY_LIMIT`). Neither the client's JoinLobby nor the server enforces
    it.
11. **Play Next Game, second attempt.** The 31 replies were accepted, but
    the host kept re-sending 31 while it waited for its room's record and
    then reported "Can not access game service" (see Matches).
12. **Next round.** With the room record sent after operation 31, Play
    Next Game started a second round in the same room, and both rounds were
    recorded. The lobby showed a limit of 100. Ladder totals are kept in the
    state volume's accounts database, so earlier runs' results carry over
    across restarts.
13. **Joining a friend in the lobby.** It did not work, and no operation
    106 reached the server: the client refused because the friend's status
    (GS 0) mapped below the lobby threshold (see Joining a friend). Both
    players showed a green lobby ping to each other.
14. **Joining a friend in the lobby, with GS 8 (no log saved).** PC2 left
    the lobby and showed as "Online", then joined the lobby from the friends
    list and showed as "Lobby".
