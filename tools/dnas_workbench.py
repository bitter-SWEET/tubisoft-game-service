#!/usr/bin/env python3
"""Offline DNAS preservation tools. Never installs packets or changes a server.

Inputs are private disc/capture material; outputs are exclusive, mode-0600 files.
The transport codec follows the public DNASrep wire parameters, independently
implemented with standard CBC primitives. A reversible transport is not proof
that a title accepts a fabricated authentication response.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct

from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.ciphers import Cipher, modes

CONNECT_BYTES = 0x148
CHECK_FIELD = slice(0x3c, 0x50)  # Isolated by TSFP experiments; verify per title.
SESSION_FIELD = slice(0xc8, 0xe8)
# Public protocol parameters, not an operator key or a title-authentication blob.
OUTER_KEY = bytes.fromhex("eb711416cb0ab016ae190174b5ce63397b01b91880145e34")
OUTER_IV = bytes.fromhex("c510a6400a9b022f")
# Build fingerprints and addresses only. No retail bytes are distributed.
OVERLAY_PROFILES = {
    "gr2-usa": {
        "sha256": "a1a20871763f219f39d68c4d3b3a6910a507156de713ce238bb76e1f6b3396e4",
        "base": 0x01dce400, "code_limit": 0x70480,
        "decoders": (0x01df9af8, 0x01e33858), "flush_cache": 0x001172a0,
    },
}


def request_identity(request: bytes) -> str:
    if len(request) < 0x134:
        raise ValueError("i-connect request must contain at least 308 bytes")
    return request[0x2c:0x34].hex() + "_" + request[:4].hex()


def _session_material(request: bytes) -> tuple[bytes, bytes]:
    request_identity(request)
    material = hashlib.sha1(request[0x48:0x134]).digest() + hashlib.sha1(request[0x34:0x134]).digest()[:12]
    return material[:24], material[24:32]


def _cbc(value: bytes, key: bytes, iv: bytes, *, decode: bool) -> bytes:
    cipher = Cipher(TripleDES(key), modes.CBC(iv))
    worker = cipher.decryptor() if decode else cipher.encryptor()
    return worker.update(value) + worker.finalize()


def transport(response: bytes, request: bytes, *, decode: bool = False) -> bytes:
    """Wrap/unwrap the known 328-byte i-connect dialect without altering fields."""
    if len(response) != CONNECT_BYTES:
        raise ValueError("this codec requires a 328-byte i-connect response")
    key, iv = _session_material(request)
    result = bytearray(response)
    if decode:
        result[0x28:0x148] = _cbc(result[0x28:0x148], OUTER_KEY, OUTER_IV, decode=True)
        result[SESSION_FIELD] = _cbc(result[SESSION_FIELD], key, iv, decode=True)
    else:
        result[SESSION_FIELD] = _cbc(result[SESSION_FIELD], key, iv, decode=False)
        result[0x28:0x148] = _cbc(result[0x28:0x148], OUTER_KEY, OUTER_IV, decode=False)
    return bytes(result)


def candidate(template: bytes, check_field: bytes) -> bytes:
    """Insert an externally recovered value; this does not derive or validate it."""
    if len(template) != CONNECT_BYTES or len(check_field) != 20:
        raise ValueError("candidate requires a 328-byte template and a 20-byte check-field file")
    result = bytearray(template)
    result[CHECK_FIELD] = check_field
    return bytes(result)


def compare(first: bytes, second: bytes) -> dict:
    if len(first) != CONNECT_BYTES or len(second) != CONNECT_BYTES:
        raise ValueError("comparison requires two unwrapped 328-byte responses")
    ranges = []
    for offset, (left, right) in enumerate(zip(first, second)):
        if left != right:
            if ranges and ranges[-1][1] == offset:
                ranges[-1][1] += 1
            else:
                ranges.append([offset, offset + 1])
    return {"bytes": len(first), "changed_ranges": ranges,
            "tsfp_check_field_equal": first[CHECK_FIELD] == second[CHECK_FIELD],
            "session_field_equal": first[SESSION_FIELD] == second[SESSION_FIELD]}


def rom_modules(image: bytes) -> list[tuple[str, bytes]]:
    """Read the ROMDIR layout used by the examined DNAS300 IOP images."""
    if image[:6] != b"RESET\0" or image[0x10:0x17] != b"ROMDIR\0":
        raise ValueError("not a supported IOP ROMDIR image")
    if len(image) < 0x20:
        raise ValueError("truncated ROMDIR header")
    directory_bytes = struct.unpack_from("<I", image, 0x1c)[0]
    if not 0x30 <= directory_bytes <= len(image) or directory_bytes % 16:
        raise ValueError("invalid ROMDIR size")
    offset = 0
    result = []
    names = set()
    for entry in range(0, directory_bytes, 16):
        name, _, size = struct.unpack_from("<10sHI", image, entry)
        name = name.split(b"\0", 1)[0]
        if not name:
            break
        if not re.fullmatch(rb"[A-Z0-9_]{1,10}", name) or name in names or offset + size > len(image):
            raise ValueError("invalid module name or image bounds")
        names.add(name)
        raw = image[offset:offset + size]
        if raw.startswith(b"\x7fELF"):
            result.append((name.decode("ascii"), raw))
        offset += (size + 15) & ~15
    return result


def recover_overlay(raw: bytes, profile_name: str) -> tuple[bytes, dict]:
    """Run a known build's own code decoder, not its authentication routine.

    The only stub is FlushCache. All transforms execute native instructions in
    an isolated Unicorn address space. Recognized metadata is bounds checked;
    an unknown build or non-returning native call is refused.
    """
    profile = OVERLAY_PROFILES[profile_name]
    if hashlib.sha256(raw).hexdigest() != profile["sha256"]:
        raise ValueError("overlay fingerprint does not match the selected build")
    try:
        from unicorn import Uc, UcError, UC_ARCH_MIPS, UC_MODE_MIPS64, UC_MODE_LITTLE_ENDIAN
        from unicorn.mips_const import (UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2,
                                       UC_MIPS_REG_A3, UC_MIPS_REG_SP, UC_MIPS_REG_RA, UC_MIPS_REG_PC)
    except ImportError as exc:
        raise ValueError("overlay recovery requires the optional research dependencies") from exc
    base = profile["base"]
    machine = Uc(UC_ARCH_MIPS, UC_MODE_MIPS64 | UC_MODE_LITTLE_ENDIAN)
    machine.mem_map(0, 0x02000000)
    machine.mem_write(base, raw)
    # jr ra; nop, used only for the two cache-maintenance calls.
    machine.mem_write(profile["flush_cache"], struct.pack("<II", 0x03e00008, 0))
    recovered = set()
    blocks = []
    for _ in range(6):
        image = bytes(machine.mem_read(base, len(raw)))
        pending = []
        for offset in range(0x80, profile["code_limit"] - 20, 4):
            flag, third, seed, second, pad = struct.unpack_from("<5I", image, offset)
            length = third ^ second
            address = base + offset + 20
            if (address in recovered or flag or pad or seed & 1
                    or third < 0x10000 or second < 0x10000 or not 4 <= length <= 0x10000
                    or length % 4 or offset + 20 + length > profile["code_limit"]):
                continue
            # Match the actual native callsite. Similar-looking tables are not
            # protection records, and the two code namespaces use different
            # decoder implementations despite sharing this metadata layout.
            calls = []
            for site in range(max(0x80, offset - 0x80), offset, 4):
                instruction = struct.unpack_from("<I", image, site)[0]
                target = (instruction & 0x03ffffff) << 2
                if instruction >> 26 == 3 and target in profile["decoders"]:
                    calls.append(target)
            if calls:
                pending.append((calls[-1], (address, second, third, seed)))
        if not pending:
            break
        if len(recovered) + len(pending) > 512:
            raise ValueError("unexpected number of protected blocks")
        for decoder, arguments in pending:
            for register, value in zip((UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2, UC_MIPS_REG_A3), arguments):
                machine.reg_write(register, value)
            machine.reg_write(UC_MIPS_REG_SP, 0x01000000)
            machine.reg_write(UC_MIPS_REG_RA, 0x00080000)
            try:
                machine.emu_start(decoder, 0x00080000, count=1000000, timeout=1000000)
            except UcError as exc:
                raise ValueError("native overlay decoder faulted") from exc
            if machine.reg_read(UC_MIPS_REG_PC) != 0x00080000:
                raise ValueError("native overlay decoder did not return within its bound")
            recovered.add(arguments[0])
            blocks.append({"address": arguments[0], "bytes": arguments[1] ^ arguments[2], "decoder": decoder})
    else:
        raise ValueError("protected-block recovery exceeded its pass limit")
    if not blocks:
        raise ValueError("no protected blocks recovered")
    return bytes(machine.mem_read(base, len(raw))), {
        "profile": profile_name, "base": base, "decoded_blocks": blocks,
        "authentication_derivation": "not executed", "retail_acceptance": "not tested",
    }


def read_private(path: Path, maximum: int = 1024 * 1024) -> bytes:
    with path.open("rb") as stream:
        value = stream.read(maximum + 1)
    if len(value) > maximum:
        raise ValueError("input exceeds workbench size limit")
    return value


def write_private(path: Path, value: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value)
    return {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    inspect = sub.add_parser("identity", help="show only a request's replay lookup identity")
    inspect.add_argument("request", type=Path)
    inventory = sub.add_parser("inventory", help="search all gateways without printing payloads")
    inventory.add_argument("store", type=Path)
    inventory.add_argument("--identity", required=True)
    for name in ("wrap", "unwrap"):
        codec = sub.add_parser(name, help="apply/remove the known request-bound transport")
        codec.add_argument("request", type=Path)
        codec.add_argument("response", type=Path)
        codec.add_argument("--output", type=Path, required=True)
    build = sub.add_parser("candidate", help="insert a separately recovered check value; acceptance is unverified")
    build.add_argument("template", type=Path)
    build.add_argument("check_field", type=Path)
    build.add_argument("--output", type=Path, required=True)
    diff = sub.add_parser("compare", help="compare plaintext templates without exposing their fields")
    diff.add_argument("first", type=Path)
    diff.add_argument("second", type=Path)
    extract = sub.add_parser("disc-input", help="extract an explicitly verified sector range from an owned ISO")
    extract.add_argument("iso", type=Path)
    extract.add_argument("--sector", type=int, required=True)
    extract.add_argument("--count", type=int, required=True)
    extract.add_argument("--output", type=Path, required=True)
    iop = sub.add_parser("iop-modules", help="extract ELF modules from a private ROMDIR image")
    iop.add_argument("image", type=Path)
    iop.add_argument("--output-directory", type=Path, required=True)
    overlay = sub.add_parser("recover-overlay", help="execute a fingerprinted build's native code decoder offline")
    overlay.add_argument("image", type=Path)
    overlay.add_argument("--profile", choices=OVERLAY_PROFILES, required=True)
    overlay.add_argument("--output", type=Path, required=True)
    overlay.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.operation == "identity":
            result = {"lookup": request_identity(read_private(args.request))}
        elif args.operation == "inventory":
            if not re.fullmatch(r"[0-9a-f]{16}_[0-9a-f]{8}", args.identity):
                raise ValueError("invalid lookup identity")
            paths = sorted(p for p in args.store.rglob(args.identity) if p.is_file())
            result = {"matches": [{"file": str(p.relative_to(args.store)), "bytes": p.stat().st_size} for p in paths]}
        elif args.operation in ("wrap", "unwrap"):
            result = write_private(args.output, transport(read_private(args.response),
                                   read_private(args.request), decode=args.operation == "unwrap"))
        elif args.operation == "candidate":
            result = write_private(args.output, candidate(read_private(args.template), read_private(args.check_field)))
            result["retail_acceptance"] = "unverified"
        elif args.operation == "compare":
            result = compare(read_private(args.first), read_private(args.second))
        elif args.operation == "disc-input":
            if args.sector < 0 or not 1 <= args.count <= 512:
                raise ValueError("invalid or excessive sector range")
            with args.iso.open("rb") as stream:
                stream.seek(args.sector * 2048)
                raw = stream.read(args.count * 2048)
            if len(raw) != args.count * 2048:
                raise ValueError("disc does not contain the requested sector range")
            result = write_private(args.output, raw)
        elif args.operation == "iop-modules":
            modules = rom_modules(read_private(args.image))
            if args.output_directory.exists():
                raise ValueError("module output directory must be new")
            args.output_directory.mkdir(parents=True, mode=0o700)
            result = {"modules": [{"name": name, **write_private(args.output_directory / (name + ".irx"), raw)}
                                  for name, raw in modules]}
        else:
            raw, report = recover_overlay(read_private(args.image), args.profile)
            if args.output.exists() or args.report.exists() or args.output.resolve() == args.report.resolve():
                raise ValueError("overlay output and report must be separate new files")
            result = write_private(args.output, raw)
            write_private(args.report, (json.dumps(report, indent=2) + "\n").encode())
            result.update(profile=args.profile, decoded_blocks=len(report["decoded_blocks"]),
                          authentication_derivation="not executed", retail_acceptance="not tested")
        print(json.dumps(result, indent=2))
    except (OSError, ValueError):
        parser.exit(1, "DNAS workbench failed: check input format/bounds and use a new output path. No payload printed.\n")


if __name__ == "__main__":
    main()
