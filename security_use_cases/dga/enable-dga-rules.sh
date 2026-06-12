#!/usr/bin/env bash
# Install/enable DGA detection rules and add logs-dga.dns-* to query-rule indices.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$DIR/enable-dga-rules.py" "$@"
