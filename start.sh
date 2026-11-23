#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo "Uruchamiam Photo Organizer AI pod adresem: http://127.0.0.1:8765"
exec /Users/krzysztofjarzyna/.local/bin/uv run uvicorn app:app --host 127.0.0.1 --port 8765
