#!/usr/bin/env bash
# scripts/run_local.sh — start the bot locally on :8080 (override with PORT=xxxx).
set -euo pipefail
cd "$(dirname "$0")/.."
export PORT="${PORT:-8080}"
echo "Starting Vera bot on http://0.0.0.0:${PORT}  (Ctrl+C to stop)"
echo "Set VERA_USE_LLM=1 and ANTHROPIC_API_KEY/OPENAI_API_KEY to enable the optional LLM polish pass."
exec python3 bot.py
