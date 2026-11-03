"""Bounded GS data-list subset used by public-key messages.

Strings use UTF-8 with surrogate escape to preserve unrecognized bytes. Binary
values are represented as bytes, and nested lists as Python lists. The outer
list has no delimiters on the wire. Other client data types are not supported.
"""
from __future__ import annotations

MAX_PAYLOAD = 65535
MAX_DEPTH = 16
MAX_ITEMS = 1024


def decode(data: bytes) -> list:
    if len(data) > MAX_PAYLOAD:
        raise ValueError("GS data exceeds the local payload limit")
    items_seen = 0

    def parse(offset: int, depth: int, nested: bool) -> tuple[list, int]:
        nonlocal items_seen
        if depth > MAX_DEPTH:
            raise ValueError("GS data nesting is too deep")
        values = []
        while offset < len(data):
            tag = data[offset]
            offset += 1
            if tag == ord("]"):
                if not nested:
                    raise ValueError("unexpected GS list terminator")
                return values, offset
            items_seen += 1
            if items_seen > MAX_ITEMS:
                raise ValueError("too many GS data items")
            if tag == ord("s"):
                end = data.find(b"\x00", offset)
                if end < 0:
                    raise ValueError("unterminated GS string")
                values.append(data[offset:end].decode("utf-8", errors="surrogateescape"))
                offset = end + 1
            elif tag == ord("b"):
                if offset + 4 > len(data):
                    raise ValueError("truncated GS binary length")
                size = int.from_bytes(data[offset:offset + 4], "big")
                offset += 4
                if size > len(data) - offset:
                    raise ValueError("truncated GS binary value")
                values.append(data[offset:offset + size])
                offset += size
            elif tag == ord("["):
                child, offset = parse(offset, depth + 1, True)
                values.append(child)
            else:
                raise ValueError(f"unsupported GS data tag 0x{tag:02x}")
        if nested:
            raise ValueError("unterminated GS nested list")
        return values, offset

    result, _ = parse(0, 0, False)
    return result


def encode(values: list) -> bytes:
    items_seen = 0

    def render(items: list, depth: int) -> bytes:
        nonlocal items_seen
        if depth > MAX_DEPTH:
            raise ValueError("GS data nesting is too deep")
        output = bytearray()
        for value in items:
            items_seen += 1
            if items_seen > MAX_ITEMS:
                raise ValueError("too many GS data items")
            if isinstance(value, str):
                raw = value.encode("utf-8", errors="surrogateescape")
                if b"\x00" in raw:
                    raise ValueError("GS strings cannot contain NUL")
                output.extend(b"s" + raw + b"\x00")
            elif isinstance(value, bytes):
                if len(value) > MAX_PAYLOAD:
                    raise ValueError("GS binary exceeds the local payload limit")
                output.extend(b"b" + len(value).to_bytes(4, "big") + value)
            elif isinstance(value, list):
                output.extend(b"[" + render(value, depth + 1) + b"]")
            else:
                raise TypeError("GS values must be strings, bytes, or lists")
            if len(output) > MAX_PAYLOAD:
                raise ValueError("GS data exceeds the local payload limit")
        return bytes(output)

    if not isinstance(values, list):
        raise TypeError("GS outer data must be a list")
    return render(values, 0)
