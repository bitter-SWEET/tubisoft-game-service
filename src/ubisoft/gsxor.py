"""GS XOR message transform reconstructed from XIII's network overlay."""
from __future__ import annotations

from math import isqrt

# A local resource limit for the diagnostic implementation, not a protocol limit.
MAX_PAYLOAD = 65535


def _positions(length: int) -> tuple[int, list[int]]:
    if not 0 <= length <= MAX_PAYLOAD:
        raise ValueError("GS XOR payload exceeds the local 65535-byte limit")
    side = isqrt(length)
    if side * side < length:
        side += 1
    positions = []
    column = row = 0
    for _ in range(length):
        if column < side:
            if row < 0:
                row, column = column, 0
        else:
            column, row = row + 2, side - 1
        positions.append(column + row * side)
        column += 1
        row -= 1
    return side, positions


def encrypt(data: bytes) -> bytes:
    """XOR each input byte, then emit the occupied diagonal grid row by row."""
    side, positions = _positions(len(data))
    grid = [-1] * (side * side)
    for index, position in enumerate(positions):
        grid[position] = data[index] ^ ((index + 0x89) & 0xFF)
    return bytes(value for value in grid if value != -1)


def decrypt(data: bytes) -> bytes:
    """Rebuild the diagonal grid and reverse the input-position XOR."""
    side, positions = _positions(len(data))
    grid = bytearray(side * side)
    for position, value in zip(sorted(positions), data):
        grid[position] = value
    return bytes(grid[position] ^ ((index + 0x89) & 0xFF)
                 for index, position in enumerate(positions))
