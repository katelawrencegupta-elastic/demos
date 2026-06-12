#!/usr/bin/env bash
set -euo pipefail

export LOGSTASH_HOST="${LOGSTASH_HOST:-172.17.0.2}"
export LOGSTASH_PORT="${LOGSTASH_PORT:-5044}"

envsubst '${LOGSTASH_HOST} ${LOGSTASH_PORT}' \
  < /etc/packetbeat/packetbeat.yml.template \
  > /etc/packetbeat/packetbeat.yml

/usr/local/bin/start-services.sh
sleep 15
/usr/local/bin/wait-for-services.sh

echo "Starting Packetbeat (output -> ${LOGSTASH_HOST}:${LOGSTASH_PORT})" >&2
packetbeat --environment container -e -c /etc/packetbeat/packetbeat.yml &
PACKETBEAT_PID=$!

cleanup() {
  kill "${PACKETBEAT_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

/usr/local/bin/generate-traffic.sh &
TRAFFIC_PID=$!

wait "${PACKETBEAT_PID}"
kill "${TRAFFIC_PID}" 2>/dev/null || true
