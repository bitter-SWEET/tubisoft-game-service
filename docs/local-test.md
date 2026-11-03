# XIII beta tester guide

Only the USA PS2 release (`SLUS-20677`, CRC `FCD97245`) has been tested. Use a disc image you own and a distinct test account on each PC. The addresses in this repository are documentation examples, not deployed servers; obtain the actual server/DNS address privately from the operator.

## Network setup

1. Use PCSX2's Ethernet support with an appropriate adapter/API for that PC. The successful LAN test used Sockets.
2. Set PCSX2's intercepted DHCP DNS to the operator's DNS address. In the **saved PS2 network profile**, select automatic DNS so it uses that DHCP response.
3. A saved manual DNS entry can take precedence over the DHCP DNS list. A profile pointing at PCSX2's internal resolver can therefore bypass the operator's DNS. A title-specific hosts override is not required for the verified DNS path.
4. Fully stop and boot the game after network changes. Confirm DNAS completes, then create or sign in with a unique game-only password. Do not reuse an existing Ubisoft or email password.

Optional service check, from a checkout or with the standalone script:

```sh
python tools/lan_preflight.py 192.0.2.10
```

Replace the example address. This checks DNS, bootstrap, and TCP reachability, not complete peer UDP behavior. The public beta does not require your address to be enrolled.

## Two-player test

1. Sign in on both PCs with different accounts.
2. Host a public game without a password on the first PC. Refresh the server list on the second.
3. Select and join the game. Verify both clients can move, see each other, and interact in combat.
4. Let a time/frag-limited round finish. The game keeps the hosted room open and returns players to readiness; press Fire to ready for another round. A finished round is distinct from closing the hosted game.
5. Close only the hosted game. The service should remove its room and notify joined clients. The native game may display a generic connection error or a sign-in screen; the observed guest has continued heartbeats and refreshed an empty list on its existing GS connection afterward.
6. Reconnect and create another room. Record any stale room, failure to register, or unexpected timeout.

## What is verified

Two independent PCs joined one hosted match and played in combat. Both completed NAT discovery using their real game UDP sockets. The host accepted member/player-info notifications and sent its own peer-opening packets. Live additional-info updates continued, and host exit removed the room. Leave/friends-disconnect cleanup now retains the service connection.

Normal ready prompts were verified against the disc's scripts. Successful repeated rounds, long-duration transport rollover, password-protected games, persistence of lifetime stats, and arbitrary Internet NAT combinations remain incomplete or unverified. Do not interpret a room listing or successful NAT lookup as proof that peers can exchange gameplay.

## Reporting issues

Report the game serial/CRC, PCSX2 version, whether the PCs share a LAN or public NAT, the action taken, and the exact on-screen message. Give the operator a test time so they can correlate pseudonymous logs. Do not post passwords, usernames used elsewhere, keys, databases, memory cards, or unredacted captures.
