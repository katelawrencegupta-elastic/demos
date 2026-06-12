#!/usr/bin/env python3
"""Send a DHCPv4 DISCOVER packet on loopback for Packetbeat capture."""

import random
import socket
import struct


def mac_bytes() -> bytes:
    return bytes([0x02] + [random.randint(0, 255) for _ in range(5)])


def build_discover(xid: int, client_mac: bytes) -> bytes:
    packet = struct.pack("!BBBBI", 1, 1, 6, 0, xid)
    packet += client_mac + (b"\x00" * 10)
    packet += b"\x00" * 64
    packet += b"\x00" * 128
    packet += struct.pack("!I", 0x63825363)
    packet += b"\x00" * 16
    packet += b"\x00" * 64
    packet += b"\x00" * 128
    packet += b"\x63\x82\x53\x63"
    packet += b"\x35\x01\x01\xff"
    return packet


def main() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 68))

    xid = random.randint(0, 0xFFFFFFFF)
    packet = build_discover(xid, mac_bytes())
    sock.sendto(packet, ("127.0.0.1", 67))


if __name__ == "__main__":
    main()
