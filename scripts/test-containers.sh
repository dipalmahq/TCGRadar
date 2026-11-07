#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."

# This project name is reserved for disposable tests, separate from app data.
compose=(docker compose -f compose.yaml -f compose.test.yaml -p joyboyz-radar-acceptance --profile test)
cleanup() { "${compose[@]}" down --remove-orphans >/dev/null; }
trap cleanup EXIT
"${compose[@]}" run --rm tests
