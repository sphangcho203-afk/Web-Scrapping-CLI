#!/usr/bin/env bash
set -euo pipefail

URL="${1:-https://example.com}"
ih monitor "$URL" --state .internet-hands/example.json
