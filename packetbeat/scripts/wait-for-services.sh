#!/usr/bin/env bash
set -euo pipefail

wait_for_port() {
  local host="$1"
  local port="$2"
  local label="$3"
  local attempts="${4:-60}"

  for _ in $(seq 1 "${attempts}"); do
    if nc -z "${host}" "${port}" 2>/dev/null; then
      echo "${label} ready on ${host}:${port}" >&2
      return 0
    fi
    sleep 1
  done

  echo "Timed out waiting for ${label} on ${host}:${port}" >&2
  return 1
}

wait_for_udp_port() {
  local port="$1"
  local label="$2"
  local attempts="${3:-30}"

  for _ in $(seq 1 "${attempts}"); do
    if ss -ulnp 2>/dev/null | grep -q ":${port} "; then
      echo "${label} ready on UDP port ${port}" >&2
      return 0
    fi
    sleep 1
  done

  echo "Timed out waiting for ${label} on UDP port ${port}" >&2
  return 1
}

wait_for_port 127.0.0.1 80 "HTTP"
wait_for_port 127.0.0.1 443 "TLS"
wait_for_port 127.0.0.1 53 "DNS" || true
wait_for_port 127.0.0.1 3306 "MySQL" || true
wait_for_port 127.0.0.1 5432 "PostgreSQL" || true
wait_for_port 127.0.0.1 6379 "Redis" || true
wait_for_port 127.0.0.1 11211 "Memcache" || true
wait_for_port 127.0.0.1 5672 "AMQP" 90 || true
wait_for_port 127.0.0.1 27017 "MongoDB" 90 || true
wait_for_port 127.0.0.1 9042 "Cassandra" 180 || true
wait_for_port 127.0.0.1 9090 "Thrift" || true
wait_for_udp_port 5060 "SIP" || true

if ! mountpoint -q /mnt/nfs; then
  mount -t nfs -o vers=3,nolock,tcp 127.0.0.1:/srv/nfs /mnt/nfs 2>/dev/null || true
fi

echo "All services ready." >&2
