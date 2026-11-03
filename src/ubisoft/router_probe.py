"""Observe GS frame headers on an isolated listener; does not reply to clients."""
from __future__ import annotations

import argparse
import asyncio
import logging

from . import data, gsxor
from .bootstrap import port_number
from .frame import read_frame

LOG = logging.getLogger("ubisoft.router_probe")


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, timeout: float) -> None:
    peer = writer.get_extra_info("peername")
    LOG.info("connection from %s", peer)
    try:
        while True:
            header, payload = await asyncio.wait_for(read_frame(reader), timeout=timeout)
            LOG.info("peer=%s size=%d property=%d priority=%d type=0x%02x sender=%d receiver=%d",
                     peer, header.size, header.property, header.priority,
                     header.message_type, header.sender, header.receiver)
            if header.property == 0 and header.message_type == 0xDB:
                try:
                    fields = data.decode(gsxor.decrypt(payload))
                    subtype = fields[0] if fields and fields[0] in ("1", "2", "3") else "unknown"
                    nested = fields[1] if len(fields) > 1 and isinstance(fields[1], list) else []
                    key_length = len(nested[2]) if len(nested) > 2 and isinstance(nested[2], bytes) else None
                    LOG.info("key exchange peer=%s subtype=%s binary_length=%s", peer, subtype, key_length)
                except (ValueError, IndexError, TypeError):
                    LOG.info("key exchange peer=%s could not decode GS data", peer)
    except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError, ValueError) as exc:
        LOG.info("connection closed peer=%s reason=%s", peer, type(exc).__name__)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError:
            pass


async def serve(args: argparse.Namespace) -> None:
    server = await asyncio.start_server(lambda r, w: handle(r, w, args.timeout), args.bind, args.port)
    LOG.info("listening on %s; this probe does not send responses", server.sockets[0].getsockname())
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=port_number, default=30000)
    parser.add_argument("--timeout", type=float, default=15, help="seconds to wait for each frame")
    args = parser.parse_args()
    if not 0 < args.timeout <= 300:
        parser.error("timeout must be between 0 and 300 seconds")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
