"""Six-byte GS frame header, independently of message contents."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

HEADER_SIZE = 6
MAX_FRAME_SIZE = 3_000_000


@dataclass(frozen=True)
class GSHeader:
    size: int
    property: int
    priority: int
    message_type: int
    sender: int
    receiver: int

    @classmethod
    def decode(cls, data: bytes) -> "GSHeader":
        if len(data) != HEADER_SIZE:
            raise ValueError("GS header must be six bytes")
        size = int.from_bytes(data[:3], "big")
        if not HEADER_SIZE <= size <= MAX_FRAME_SIZE:
            raise ValueError("invalid GS frame length")
        return cls(size, data[3] >> 6, data[3] & 0x3F, data[4], data[5] >> 4, data[5] & 0x0F)

    def encode(self) -> bytes:
        if not HEADER_SIZE <= self.size <= MAX_FRAME_SIZE:
            raise ValueError("invalid GS frame length")
        if not (0 <= self.property <= 3 and 0 <= self.priority <= 63
                and 0 <= self.message_type <= 255
                and 0 <= self.sender <= 15 and 0 <= self.receiver <= 15):
            raise ValueError("GS header field is out of range")
        return (self.size.to_bytes(3, "big")
                + bytes(((self.property << 6) | self.priority, self.message_type,
                         (self.sender << 4) | self.receiver)))


async def read_frame(reader: asyncio.StreamReader, *, maximum_size: int = MAX_FRAME_SIZE) -> tuple[GSHeader, bytes]:
    header = GSHeader.decode(await reader.readexactly(HEADER_SIZE))
    if header.size > maximum_size:
        raise ValueError("frame exceeds listener resource limit")
    return header, await reader.readexactly(header.size - HEADER_SIZE)
