# XIII USA PS2 network investigation

## Disc and address identity

The inspected image identifies itself as `XIII`, publisher `UBISOFT`, and boots `SLUS_206.77` version 1.01. The following hashes identify the files behind the addresses below:

| File | SHA-256 |
| --- | --- |
| `SLUS_206.77` | `54dc3aa01f47cf68dde0557b167e59990ce3902e155ec09bc0fed485dd588ada` |
| `OVL/NET_M.OVL` | `b51f636a27527e304640130203ea1de54f70ce105a3bdd4ec04806c487aaf779` |
| `OVL/DNAS_M.OVL` | `95f377be33d5cc064f631a72e4b330f98d5315d99489b794c812307f094b6a2e` |

The main binary is a little-endian MIPS/EE ELF. Its first load segment maps file offset `0x100` to virtual address `0x00100000`. `NET_M.OVL` begins with an `MWo3` header containing `0x01cee500`; instructions and string references are consistent with the complete file being mapped at that address. `DNAS_M.OVL` has the same signature and contains `0x01bdc480`. The overlay loader should be examined before treating every header field as understood.

## What the disc establishes

* `PSX2GAME.INI` selects `PSX2NetDrv.PSX2GSMatchMakingSubsystem`; its Unreal game port is configured as `7777`. This port is a gameplay configuration value, not proof of a Ubisoft service port.
* The ELF contains `gsconnect.ubisoft.com` (file `0x2c2c10`) and HTTP request components `GET `, `/gsinit.php?dp=`, ` HTTP/1.1`, and `HOST: ` (file `0x2e7f98` onward). The code referencing the hostname is near virtual `0x0039f2c4`; the path is referenced near `0x0039f430`.
* The bootstrap function is `0x0039f2c0`. Its port conversion receives `0x50` (80); it constructs `GET /gsinit.php?dp=<argument> HTTP/1.1\r\nHOST: gsconnect.ubisoft.com\r\n\r\n`, sends it, and reads until the connection closes. The caller passes the game identifier global initialized to `XIIIPS2US` at `0x0037be30`–`0x0037be38`.
* The parser at `0x0039f210` searches the received buffer for each key, advances to `=`, and copies bytes until CR or LF. The bootstrap starts at index zero and searches for the router triplet `routerip%d`, `routerport%d`, `routerlauncherport%d`, and the NAT pair `natserverip%d`, `natserverport%d`. A router entry is stored only when all three keys are found; a NAT entry requires both. The code scans missing indices through 11; the behavior after a present index 11 deserves separate review. Values are copied to `Engine.MatchMakingServers` entries. The code parses the entire received buffer, so the response should be short and each value terminated by a newline. These conclusions are static and await a retail-client capture.
* The client initializes adjacent globals to `XIIIPS2US`, `XIIIPS21.0`, and `1.0` at `0x0037be30`–`0x0037be54`. The first is used as the bootstrap `dp` value. The second and third are passed into online setup; the exact version semantics need confirmation.
* The network overlay contains message names such as `CONNECTIONREQUEST`, `NEWUSERREQUEST`, `LOGINWAITMODULE`, `LOGINFRIENDS`, `CREATESESSION`, and `JOINSESSION`. It also contains references to encrypted messages, public and cipher key messages, `clSRPGSClient`, router login, and a wait module. These names establish investigation targets, not their wire format or proof that every feature is used by XIII.
* `DNAS280.IMG` and `DNAS_M.OVL` establish a DNAS client component. Compatibility with the neighboring TSFP replay data must be checked against XIII's actual DNAS request; it is not established by the shared platform.

## Relationship to TSFP

`../tsfp-online-server` documents a client-proven DNS, DNAS, EA FESL, theater and messenger path for TSFP. The DNS and DNAS mechanisms and operational setup are useful research references. XIII's observed Ubisoft bootstrap and SDK message vocabulary give no evidence that it speaks EA FESL. Keep platform authentication, Ubisoft service framing and identity, and game-specific lobby metadata as separate components once their interfaces are supported by evidence. Do not copy replay data, keys, certificates, or upstream code without checking its configuration and license.

## Next evidence needed

1. Confirm the `XIIIPS2US` bootstrap request and response with the retail client. Select local router and launcher ports and establish their behavior from the client; original port numbers are not required when the bootstrap advertises replacements.
2. Trace key exchange, login fields, and router responses against captures; see [the deeper workflow](xiii-online-workflow.md).
3. Run a clean XIII client in a controlled network with DNS directed locally and capture its bootstrap and DNAS traffic. Confirm DNAS response availability for this disc, then compare observed traffic to the static findings. Avoid retaining credentials or account secrets in public fixtures.
4. Implement a shared Ubisoft protocol core only after a minimal client exchange is understood; represent XIII's product identifiers and lobby payloads in a separate game profile. Verify with the retail client, then investigate a second title before claiming cross-game compatibility.

## Network overlay leads

A separate raw-binary Ghidra import at `0x01cee500` finds a length check at `0x01d5bbe0`: it requires at least 6 available bytes, calls `0x01d5ba00` to derive a length from the first three bytes, and accepts derived lengths from 6 through 3,000,000. The length helper copies the three bytes into bytes 1–3 of a zeroed little-endian word, then `0x01cf3cc8` reverses the word bytes: this yields a big-endian 24-bit value. The adjacent accessors at `0x01d5ba30`–`0x01d5ba70` read the remaining bytes as a two-bit property, six-bit low field, one-byte message type, and two four-bit endpoint fields. The serializer at `0x01d5bf00` writes the complete frame length, including the six-byte header. Transport variants still need comparison with a capture.

`0x01d62260` is associated with `Read Public Key Msg` and accesses message properties indexed 0, 1, and 2. `0x01d62380` is associated with `Read Cipher Key Msg` and accesses the same property indices. `0x01d8d860` logs router login success when its status byte is `0x26`; the context and full status mapping remain unknown. These functions are leads from a standalone overlay import, where calls to the main ELF are unresolved, so decompiler types and control flow must be checked against instructions and live traffic.

A detailed map of the [online workflow and implementation boundaries](xiii-online-workflow.md) supersedes the initial leads above.
