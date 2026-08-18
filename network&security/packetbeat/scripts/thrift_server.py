#!/usr/bin/env python3
"""Minimal Thrift RPC server for Packetbeat demo traffic."""

import sys

sys.path.insert(0, "/app/thrift/gen")

from ping.Ping import Processor
from thrift.protocol import TBinaryProtocol
from thrift.server import TServer
from thrift.transport import TSocket, TTransport


class PingHandler:
    def ping(self, msg):
        return f"pong:{msg}"


def main() -> None:
    handler = PingHandler()
    processor = Processor(handler)
    transport = TSocket.TServerSocket(host="127.0.0.1", port=9090)
    tfactory = TTransport.TBufferedTransportFactory()
    pfactory = TBinaryProtocol.TBinaryProtocolFactory()
    server = TServer.TSimpleServer(processor, transport, tfactory, pfactory)
    server.serve()


if __name__ == "__main__":
    main()
