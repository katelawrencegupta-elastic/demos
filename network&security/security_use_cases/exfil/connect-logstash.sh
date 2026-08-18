#!/usr/bin/env bash
# Attach logstash to the shared demos network so generators can reach it as `logstash`.
set -euo pipefail
docker network inspect demos >/dev/null 2>&1 || docker network create demos
if docker ps --format '{{.Names}}' | grep -qx logstash; then
  docker network connect demos logstash 2>/dev/null || true
  echo "logstash is on network demos ($(docker inspect logstash --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}'))"
else
  echo "warning: logstash container is not running" >&2
  exit 1
fi
