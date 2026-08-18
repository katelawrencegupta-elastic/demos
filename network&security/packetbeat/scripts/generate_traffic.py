#!/usr/bin/env python3
"""Generate synthetic traffic for all Packetbeat-supported demo protocols."""

import os
import socket
import subprocess
import sys
import time

sys.path.insert(0, "/app/thrift/gen")

import memcache
import mysql.connector
import pika
import psycopg2
import pymongo
import redis
from cassandra.cluster import Cluster
from ping.Ping import Client
from thrift.protocol import TBinaryProtocol
from thrift.transport import TSocket, TTransport


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def icmp_v4() -> None:
    run(["ping", "-c", "1", "-W", "1", "127.0.0.1"])


def icmp_v6() -> None:
    run(["ping6", "-c", "1", "-W", "1", "::1"])


def dhcp_v4() -> None:
    subprocess.run([sys.executable, "/usr/local/bin/generate_dhcp.py"], check=False)


def dns() -> None:
    run(["dig", "@127.0.0.1", "+time=1", "+tries=1", "demo.local", "A"])
    run(["dig", "@127.0.0.1", "+time=1", "+tries=1", "packetbeat.test", "A"])
    # NXDOMAIN responses surface as DNS errors in the Network Errors panel.
    run(["dig", "@127.0.0.1", "+time=1", "+tries=1", "missing.demo.local", "A"])
    # Public resolvers give server IPs that GeoIP can place on map panels.
    run(["dig", "@8.8.8.8", "+time=2", "+tries=1", "google.com", "A"])
    run(["dig", "@1.1.1.1", "+time=2", "+tries=1", "elastic.co", "A"])


def http() -> None:
    run(["curl", "-fsS", "--max-time", "2", "http://127.0.0.1/"])
    # Dashboard "Network Errors over Time" needs non-OK status in protocol streams.
    run(["curl", "-sS", "--max-time", "2", "-o", "/dev/null", "http://127.0.0.1/client-error"])
    run(["curl", "-sS", "--max-time", "2", "-o", "/dev/null", "http://127.0.0.1/server-error"])


def tls() -> None:
    run(["curl", "-fsSk", "--max-time", "2", "https://127.0.0.1/"])


def amqp() -> None:
    try:
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(host="127.0.0.1", port=5672, heartbeat=30)
        )
        channel = connection.channel()
        channel.queue_declare(queue="packetbeat-demo", durable=False, auto_delete=True)
        channel.basic_publish(exchange="", routing_key="packetbeat-demo", body=b"packetbeat demo")
        connection.close()
    except Exception:
        pass


def cassandra() -> None:
    try:
        cluster = Cluster(["127.0.0.1"], port=9042, connect_timeout=2)
        session = cluster.connect()
        session.execute("SELECT release_version FROM system.local")
        cluster.shutdown()
    except Exception:
        pass


def mysql() -> None:
    try:
        conn = mysql.connector.connect(
            host="127.0.0.1",
            port=3306,
            user="demo",
            password="demo",
            connection_timeout=2,
        )
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception:
        pass


def postgresql() -> None:
    try:
        conn = psycopg2.connect(
            host="127.0.0.1",
            port=5432,
            dbname="demo",
            user="demo",
            password="demo",
            connect_timeout=2,
        )
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        conn.close()
    except Exception:
        pass


def redis_proto() -> None:
    try:
        client = redis.Redis(host="127.0.0.1", port=6379, socket_connect_timeout=2)
        client.ping()
        client.set("packetbeat:demo", "1", ex=30)
        client.get("packetbeat:demo")
    except Exception:
        pass


def thrift_rpc() -> None:
    try:
        transport = TSocket.TSocket("127.0.0.1", 9090)
        transport = TTransport.TBufferedTransport(transport)
        protocol = TBinaryProtocol.TBinaryProtocol(transport)
        client = Client(protocol)
        transport.open()
        client.ping("packetbeat")
        transport.close()
    except Exception:
        pass


def mongodb() -> None:
    try:
        client = pymongo.MongoClient("127.0.0.1", 27017, serverSelectionTimeoutMS=2000)
        client.admin.command("ping")
        client.packetbeat_demo.demo.insert_one({"demo": True, "ts": time.time()})
    except Exception:
        pass


def memcache_proto() -> None:
    try:
        client = memcache.Client(["127.0.0.1:11211"], socket_timeout=2)
        client.set("packetbeat:demo", "1", time=30)
        client.get("packetbeat:demo")
    except Exception:
        pass


def nfs() -> None:
    run(["rpcinfo", "-p", "127.0.0.1"])
    run(["showmount", "-e", "127.0.0.1"])
    if os.path.ismount("/mnt/nfs"):
        run(["cat", "/mnt/nfs/hello.txt"])


def sip() -> None:
    request = (
        "OPTIONS sip:demo@127.0.0.1 SIP/2.0\r\n"
        "Via: SIP/2.0/UDP 127.0.0.1:5062\r\n"
        "From: <sip:client@127.0.0.1>\r\n"
        "To: <sip:demo@127.0.0.1>\r\n"
        "Call-ID: packetbeat-demo-client\r\n"
        "CSeq: 1 OPTIONS\r\n"
        "Max-Forwards: 70\r\n"
        "Content-Length: 0\r\n"
        "\r\n"
    ).encode()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2)
    try:
        sock.sendto(request, ("127.0.0.1", 5060))
        sock.recvfrom(4096)
    except Exception:
        pass
    finally:
        sock.close()


GENERATORS = [
    ("ICMPv4", icmp_v4),
    ("ICMPv6", icmp_v6),
    ("DHCPv4", dhcp_v4),
    ("DNS", dns),
    ("HTTP", http),
    ("TLS", tls),
    ("AMQP", amqp),
    ("Cassandra", cassandra),
    ("MySQL", mysql),
    ("PostgreSQL", postgresql),
    ("Redis", redis_proto),
    ("Thrift-RPC", thrift_rpc),
    ("MongoDB", mongodb),
    ("Memcache", memcache_proto),
    ("NFS", nfs),
    ("SIP/SDP", sip),
]


def main() -> int:
    interval = float(os.environ.get("TRAFFIC_INTERVAL", "5"))
    print(f"Generating Packetbeat demo traffic every {interval}s", flush=True)

    while True:
        for name, generator in GENERATORS:
            try:
                generator()
                print(f"  generated {name}", flush=True)
            except Exception as exc:
                print(f"  {name} failed: {exc}", flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
