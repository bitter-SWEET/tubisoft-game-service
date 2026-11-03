"""Minimal gsinit bootstrap responder based on the XIII USA PS2 client.

This only provides service addresses. It does not implement a Ubisoft router.
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import logging
from urllib.parse import urlsplit, parse_qs

LOG = logging.getLogger("ubisoft.bootstrap")
MAX_REQUEST = 8192


def port_number(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def ipv4_address(value: str) -> str:
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError as exc:
        raise argparse.ArgumentTypeError("address must be an IPv4 address") from exc


def response(body: bytes, status: bytes = b"200 OK") -> bytes:
    return (b"HTTP/1.0 " + status + b"\r\nContent-Type: text/plain\r\nContent-Length: "
            + str(len(body)).encode("ascii") + b"\r\nConnection: close\r\n\r\n" + body)


def bootstrap_body(router_ip: str, router_port: int, launcher_port: int,
                   nat_ip: str | None, nat_port: int | None) -> bytes:
    lines = [f"routerip0={router_ip}", f"routerport0={router_port}",
             f"routerlauncherport0={launcher_port}"]
    if nat_ip is not None and nat_port is not None:
        lines.extend((f"natserverip0={nat_ip}", f"natserverport0={nat_port}"))
    return ("\r\n".join(lines) + "\r\n").encode("ascii")


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, body: bytes) -> None:
    try:
        request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
        if len(request) > MAX_REQUEST:
            raise ValueError("request too large")
        first_line = request.split(b"\r\n", 1)[0].split(b" ")
        if len(first_line) != 3 or first_line[0] != b"GET":
            result = response(b"Bad request\r\n", b"400 Bad Request")
        else:
            target = urlsplit(first_line[1].decode("ascii"))
            if target.path == "/healthz":
                result = response(b"ok\n")
            elif target.path != "/gsinit.php" or parse_qs(target.query).get("dp") != ["XIIIPS2US"]:
                result = response(b"Not found\r\n", b"404 Not Found")
            else:
                LOG.info("served gsinit request from %s", writer.get_extra_info("peername"))
                result = response(body)
        writer.write(result)
        await writer.drain()
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError,
            ConnectionError, UnicodeDecodeError, ValueError) as exc:
        LOG.info("bootstrap request closed: %s", type(exc).__name__)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError:
            pass


async def serve(args: argparse.Namespace) -> None:
    body = bootstrap_body(args.router_ip, args.router_port, args.launcher_port, args.nat_ip, args.nat_port)
    server = await asyncio.start_server(lambda r, w: handle(r, w, body), args.bind, args.port, limit=MAX_REQUEST)
    LOG.info("bootstrap listening on %s", ", ".join(str(s.getsockname()) for s in server.sockets or []))
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1", help="local bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=port_number, default=8080, help="local listener port (client uses 80)")
    parser.add_argument("--router-ip", type=ipv4_address, required=True)
    parser.add_argument("--router-port", type=port_number, required=True)
    parser.add_argument("--launcher-port", type=port_number, required=True)
    parser.add_argument("--nat-ip", type=ipv4_address)
    parser.add_argument("--nat-port", type=port_number)
    args = parser.parse_args()
    if (args.nat_ip is None) != (args.nat_port is None):
        parser.error("--nat-ip and --nat-port must be supplied together")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
