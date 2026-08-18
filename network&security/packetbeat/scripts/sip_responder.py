#!/usr/bin/env python3
"""Minimal SIP/SDP responder for Packetbeat demo traffic."""

import socket


def main() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 5060))

    while True:
        data, addr = sock.recvfrom(4096)
        if not data.startswith(b"SIP/2.0") and b"SIP/2.0" not in data:
            continue

        response = (
            b"SIP/2.0 200 OK\r\n"
            b"Via: SIP/2.0/UDP 127.0.0.1:5060\r\n"
            b"From: <sip:demo@127.0.0.1>\r\n"
            b"To: <sip:demo@127.0.0.1>\r\n"
            b"Call-ID: packetbeat-demo\r\n"
            b"CSeq: 1 OPTIONS\r\n"
            b"Contact: <sip:responder@127.0.0.1:5060>\r\n"
            b"Content-Type: application/sdp\r\n"
            b"Content-Length: 87\r\n"
            b"\r\n"
            b"v=0\r\n"
            b"o=demo 0 0 IN IP4 127.0.0.1\r\n"
            b"s=Packetbeat Demo\r\n"
            b"c=IN IP4 127.0.0.1\r\n"
            b"t=0 0\r\n"
            b"m=audio 4000 RTP/AVP 0\r\n"
        )
        sock.sendto(response, addr)


if __name__ == "__main__":
    main()
