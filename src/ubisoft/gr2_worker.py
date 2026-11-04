"""Trusted GR2 worker advertisements, driven by fresh native-runtime health."""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path
import re
import struct
import time

from .games.base import RoomSpec

SCHEMA = 'tubisoft-gr2-worker-v1'
MAX_AGE = 5


def game_description(address: str, port: int, template: bytes) -> bytes:
    """0x003e3010 accepts exactly 0x54 bytes; endpoint is at 0x4c/0x50."""
    ip = ipaddress.IPv4Address(address)
    if ip.is_unspecified or ip.is_multicast or ip.is_loopback or int(ip) == 0xffffffff:
        raise ValueError('unusable worker address')
    if type(port) is not int or not 1 <= port <= 65535 or len(template) != 84:
        raise ValueError('invalid worker description')
    result = bytearray(template)
    # This worker runs the verified ST01 Assault configuration without a password.
    result[0x10:0x20] = bytes(16)
    # +0x48 selects peer-hosted discovery when nonzero. The dedicated path is
    # zero; 0x004669a0 otherwise requires an owner membership from 0x003ddeb0.
    for offset, value in ((0x20, 0), (0x24, 0), (0x2c, 1), (0x30, 1), (0x48, 0)):
        struct.pack_into('<I', result, offset, value)
    result[0x4c:0x50] = ip.packed
    struct.pack_into('<H', result, 0x50, port)
    return bytes(result)


def read_worker(path: Path, profile, now: float | None = None):
    """Missing, expired, malformed or stopped workers are absent from discovery."""
    try:
        if profile.slug != 'gr2' or not profile.supports_rooms or path.is_symlink():
            return None
        if path.stat().st_size > 4096:
            return None
        value = json.loads(path.read_text())
        if (not isinstance(value, dict) or value.get('schema') != SCHEMA or value.get('ready') is not True
                or value.get('map') != 'st01_map' or value.get('mode') != 'assault'):
            return None
        updated = value['updated']
        current = time.time() if now is None else now
        if type(updated) not in (int, float) or not 0 <= current-updated <= MAX_AGE:
            return None
        run_id = value['run_id']
        if not isinstance(run_id, str) or not re.fullmatch('[a-f0-9]{32}', run_id):
            return None
        players, capacity = value['players'], value['capacity']
        if type(players) is not int or type(capacity) is not int or not 0 <= players <= capacity <= 16 or capacity < 1:
            return None
        template = bytes.fromhex(value['description'])
        info = game_description(value['address'], value['port'], template)
        address = str(ipaddress.IPv4Address(value['address']))
        spec = RoomSpec('Tubisoft GR2 Assault', profile.product, '6', '1', '8', str(capacity), '0',
                        info, info, str(value['port']), profile.game_version, profile.sdk_version, address)
        return {'run_id': run_id, 'players': players, 'address': address, 'spec': spec, 'profile': profile}
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return None
