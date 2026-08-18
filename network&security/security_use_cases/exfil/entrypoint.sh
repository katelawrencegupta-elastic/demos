#!/usr/bin/env bash
set -euo pipefail

python -u /app/receiver.py &
receiver_pid=$!

cleanup() {
  kill "$receiver_pid" 2>/dev/null || true
}
trap cleanup EXIT

exec python -u /app/generate.py
