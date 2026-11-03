#!/usr/bin/env python3
"""Check that a second PC can reach the private XIII lab services.

Run on the second PC with Python 3: python lan_preflight.py 192.0.2.10
This checks service reachability, not the PS2 emulator's direct game traffic.
"""
from __future__ import annotations

import argparse
import ipaddress
import socket
import struct
import urllib.request


def skip_name(packet: bytes, pos: int) -> int:
    while True:
        if pos >= len(packet):
            raise ValueError("truncated DNS name")
        size = packet[pos]
        if size & 0xc0 == 0xc0:
            if pos + 2 > len(packet):
                raise ValueError("truncated DNS pointer")
            return pos + 2
        if size & 0xc0:
            raise ValueError("invalid DNS label")
        pos += 1
        if size == 0:
            return pos
        pos += size


def dns_addresses(host: str) -> list[str]:
    query_id = 0x7833
    query = struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0)
    query += b"\x09gsconnect\x07ubisoft\x03com\x00" + struct.pack("!HH", 1, 1)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(3)
        sock.connect((host, 53))
        sock.send(query)
        packet = sock.recv(4096)
    if len(packet) < 12:
        raise ValueError("truncated DNS response")
    ident, flags, questions, answers, _, _ = struct.unpack_from("!HHHHHH", packet)
    if ident != query_id or not flags & 0x8000 or flags & 15:
        raise ValueError("invalid DNS response or server error")
    pos = 12
    for _ in range(questions):
        pos = skip_name(packet, pos) + 4
    result = []
    for _ in range(answers):
        pos = skip_name(packet, pos)
        if pos + 10 > len(packet):
            raise ValueError("truncated DNS answer")
        kind, klass, _, size = struct.unpack_from("!HHIH", packet, pos)
        pos += 10
        if pos + size > len(packet):
            raise ValueError("truncated DNS answer data")
        if kind == 1 and klass == 1 and size == 4:
            result.append(socket.inet_ntoa(packet[pos:pos + size]))
        pos += size
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="IPv4 address of the XIII server PC")
    host = str(ipaddress.IPv4Address(parser.parse_args().host))
    failed = False
    try:
        addresses = dns_addresses(host)
        ok = host in addresses
        print(f"DNS UDP 53: {'OK' if ok else 'FAIL'} (gsconnect resolves to {', '.join(addresses) or 'no IPv4 address'})")
        failed |= not ok
    except (OSError, ValueError) as exc:
        print(f"DNS UDP 53: FAIL ({exc})")
        failed = True
    for port, name in ((80, "bootstrap"), (443, "DNAS"), (30000, "router"), (30001, "launcher")):
        try:
            with socket.create_connection((host, port), timeout=3):
                print(f"{name} TCP {port}: OK")
        except OSError as exc:
            print(f"{name} TCP {port}: FAIL ({exc})")
            failed = True
    try:
        request = urllib.request.Request(f"http://{host}/gsinit.php?dp=XIIIPS2US")
        # Do not send a local lab request through a desktop's HTTP proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=3) as response:
            body = response.read(4096).decode("ascii")
        settings = dict(line.split("=", 1) for line in body.splitlines() if "=" in line)
        expected = {"routerip0": host, "routerport0": "30000", "routerlauncherport0": "30001",
                    "natserverip0": host, "natserverport0": "30002"}
        ok = all(settings.get(key) == value for key, value in expected.items())
        print(f"XIII bootstrap addresses: {'OK' if ok else 'FAIL'}")
        failed |= not ok
    except (OSError, ValueError, UnicodeError) as exc:
        print(f"XIII bootstrap addresses: FAIL ({exc})")
        failed = True
    print("UDP 30000, NAT discovery on UDP 30002, and direct gameplay require an in-game test.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
