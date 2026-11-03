"""Bounded access controls for the restricted beta listener."""
from __future__ import annotations

from collections import deque
import asyncio
import ipaddress
import time


def networks(value: str) -> tuple[ipaddress.IPv4Network, ...]:
    result = tuple(ipaddress.IPv4Network(item.strip()) for item in value.split(",") if item.strip())
    if not result:
        raise ValueError("at least one allowed IPv4 CIDR is required")
    return result


class AccessPolicy:
    def __init__(self, allowed_cidrs: str, *, maximum_connections: int = 128, per_ip: int = 16):
        self.allowed = networks(allowed_cidrs)
        self.maximum_connections = maximum_connections
        self.per_ip = per_ip
        self.active: dict[str, int] = {}
        self.attempts: dict[str, deque[float]] = {}
        self.authentication: dict[str, deque[float]] = {}
        self.hash_slots = asyncio.Semaphore(2)

    def _take(self, table: dict[str, deque[float]], ip: str, limit: int, seconds: int) -> bool:
        now = time.monotonic()
        for key, entries in list(table.items()):
            if not entries or entries[-1] <= now - seconds:
                del table[key]
        if ip not in table and len(table) >= 2048:
            return False
        entries = table.setdefault(ip, deque())
        while entries and entries[0] <= now - seconds:
            entries.popleft()
        if len(entries) >= limit:
            return False
        entries.append(now)
        return True

    def acquire(self, ip: str) -> bool:
        address = ipaddress.IPv4Address(ip)
        if not any(address in network for network in self.allowed):
            return False
        if sum(self.active.values()) >= self.maximum_connections or self.active.get(ip, 0) >= self.per_ip:
            return False
        if not self._take(self.attempts, ip, 30, 10):
            return False
        self.active[ip] = self.active.get(ip, 0) + 1
        return True

    def release(self, ip: str) -> None:
        remaining = self.active.get(ip, 0) - 1
        if remaining > 0:
            self.active[ip] = remaining
        else:
            self.active.pop(ip, None)

    def allow_authentication(self, ip: str) -> bool:
        return self._take(self.authentication, ip, 10, 60)
